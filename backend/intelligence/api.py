"""GET-only intelligence API. Reuses the app's session dependency (cookie session, per-request role re-check, revocation). The only POST is /ask (it
writes nothing; it uses the `csrf` dependency anyway so a cross-site page cannot make an executive's browser spend their rate limit or probe answers).
Gate: EXECUTIVE_ROLES only (proposed default ceo, coo, cto: change the tuple to change who may open the executive views). Each metric is
then filtered again by the role's per-module permissions from permissions.py, so a COO or CTO only sees what their role may read; the
rest is reported as `no_permission`. No new permissions are introduced.
All logic lives in IntelligenceService (plain Python, unit-tested); the FastAPI router below only maps requests to it."""
import copy, os, re
from datetime import date, datetime, timezone
from typing import Optional

from . import ai_interface, alerts, ask as ASK, context, metrics, results as R   # noqa: F401  (importing metrics registers every metric)
from .guard import RateLimiter, TTLCache
from .periods import PeriodError, custom, resolve
from .reader import PgReader, ReaderError
from .registry import REGISTRY, Ctx, catalog, compute

EXECUTIVE_ROLES = ("ceo", "coo", "cto")
CACHE_TTL_SECONDS = 30
RATE_LIMIT_PER_MINUTE = 60
METRIC_ID = re.compile(r"^[a-z_]{1,40}\.[a-z_]{1,60}$")      # shape of every registered id; anything else is rejected before lookup
TREND_METRICS = ("tickets.trend", "tasks.trend", "leads.trend", "tickets.flow", "tasks.flow", "leads.flow", "expenses.summary")


class ApiError(Exception):
    def __init__(self, status: int, detail: str): super().__init__(detail); self.status, self.detail = status, detail


class IntelligenceService:
    def __init__(self, reader_factory, audit, cache=None, limiter=None, today_fn=None, now_fn=None, extra_location_metrics=None):
        self.reader_factory, self.audit = reader_factory, audit
        self.cache = cache or TTLCache(CACHE_TTL_SECONDS); self.memos = TTLCache(CACHE_TTL_SECONDS, maxsize=64); self.limiter = limiter or RateLimiter(RATE_LIMIT_PER_MINUTE, 60.0)
        self.today_fn = today_fn or date.today; self.now_fn = now_fn or (lambda: datetime.now(timezone.utc).replace(microsecond=0))
        self.extra_loc = extra_location_metrics if extra_location_metrics is not None else (lambda: os.getenv("IOT_EXTRA_LOCATION_METRICS", ""))

    # ---- gates (run on the server for every endpoint; role comes from the verified session, never from the request) ----
    def require_role(self, s):
        """Role check only (no rate-limit tick). Used as a dependency so a non-executive gets 403 BEFORE the request body is even validated."""
        if s["role"] not in EXECUTIVE_ROLES:
            self.audit.write("permission_denied", s["id"], None, permission="intelligence.view", role=s["role"]); raise ApiError(403, "You do not have permission to open business intelligence.")

    def authorize(self, s):
        self.require_role(s)
        if not self.limiter.allow(s["id"]): self.audit.write("intelligence_rate_limited", s["id"], None); raise ApiError(429, "Too many requests. Try again in a minute.")

    def periods(self, kind, date_from, date_to):
        try:
            if date_from or date_to:
                if not (date_from and date_to): raise PeriodError("Provide both date_from and date_to, or neither.")
                return custom(date_from, date_to)
            return resolve(kind, self.today_fn())
        except PeriodError as e: raise ApiError(422, str(e))

    def _ctx(self, s, reader, cur, prev, today):
        """Context whose metric memo is SHARED between endpoints for the same user + role + period + day (overview, alerts, context and Ask all reuse
        one calculation instead of re-running ~110 queries each). The key holds the user id and the role, so one person's results are never served to
        anyone else; the TTL is the same as the endpoint cache, so nothing is ever older than that."""
        loc = self.extra_loc(); key = TTLCache.key(s["id"], s["role"], "memo", cur.start, cur.end, today, loc)
        memo = self.memos.get(key)
        if memo is None: memo = {}; self.memos.put(key, memo)
        return Ctx(reader=reader, role=s["role"], user_id=s["id"], period=cur, prev=prev, today=today, as_of=self.now_fn(), extra_location_metrics=loc, memo=memo)

    @staticmethod
    def _settle(ctx):
        """A metric that FAILED (unavailable: timeout, outage) is dropped from the shared memo so a transient error is retried, never replayed for the whole TTL."""
        for k in [k for k, v in ctx.memo.items() if getattr(v, "state", None) == R.UNAVAILABLE]: ctx.memo.pop(k, None)

    def _open(self):
        """Every database outage becomes one safe 503: no driver text, host or SQL ever reaches the client."""
        try: return self.reader_factory()
        except ReaderError: raise ApiError(503, "Business data is temporarily unavailable. Try again shortly.")

    def _serve(self, s, endpoint, kind, date_from, date_to, build, extra_key=()):
        self.authorize(s); cur, prev = self.periods(kind, date_from, date_to); today = self.today_fn()
        key = TTLCache.key(s["id"], s["role"], endpoint, cur.start, cur.end, today, *extra_key)       # user AND role are part of every key
        hit = self.cache.get(key)
        if hit is not None: return {**copy.deepcopy(hit), "cached": True}
        try:
            with self._open() as reader:
                ctx = self._ctx(s, reader, cur, prev, today)
                body = build(ctx); self._settle(ctx)
        except ReaderError: raise ApiError(503, "Business data is temporarily unavailable. Try again shortly.")
        body = {**body, "generated_at": ctx.as_of.isoformat(), "cached": False}
        self.cache.put(key, copy.deepcopy(body)); self.audit.write("intelligence_view", s["id"], None, endpoint=endpoint)     # endpoint name only: never data, never a question
        return body

    # ---- endpoints ----
    def status(self, s):
        self.authorize(s); return {"roles": list(EXECUTIVE_ROLES), "role": s["role"], "ai": ai_interface.status(), "metrics": len(REGISTRY), "periods": ["last_7d", "last_30d", "wow", "mom"], "max_range_days": 366,
                                   "ask": {"max_question_chars": ASK.MAX_QUESTION_CHARS, "suggestions": list(ASK.SUGGESTIONS), "answered_by": "registered_metrics"}}
    def catalog(self, s): self.authorize(s); return {"metrics": catalog(s["role"])}
    def context(self, s, period="wow", date_from=None, date_to=None): return self._serve(s, "context", period, date_from, date_to, context.build_context)
    def overview(self, s, period="wow", date_from=None, date_to=None): return self._serve(s, "overview", period, date_from, date_to, alerts.build_overview)
    def alerts(self, s, period="wow", date_from=None, date_to=None): return self._serve(s, "alerts", period, date_from, date_to, lambda c: {"alerts": alerts.build_alerts(c), "gaps": alerts.build_gaps(c)})
    def insights(self, s, period="wow", date_from=None, date_to=None): return self._serve(s, "insights", period, date_from, date_to, lambda c: {"insights": alerts.build_insights(c)})
    def trends(self, s, period="wow", date_from=None, date_to=None): return self._serve(s, "trends", period, date_from, date_to, lambda c: {"trends": {m: compute(m, c).to_dict() for m in TREND_METRICS}})

    def ask(self, s, question, period="wow"):
        """Answer one question from the registry. Order matters: authorise (role + rate limit) -> validate -> resolve -> only then touch the database.
        The question text is never logged, cached or echoed; unsupported/sensitive questions read no data at all."""
        self.authorize(s)
        try: text = ASK.clean_question(question)
        except ASK.QuestionError as e: raise ApiError(422, str(e))
        if period not in ASK.PERIOD_CHOICES: raise ApiError(422, "Unknown period.")
        kind, hit = ASK.resolve(text)
        if kind == "limitation": body, qid = hit, "limitation"
        elif kind == "none": body, qid = ASK.no_match(), "no_match"
        else:
            cur, prev = self.periods(hit.period or period, None, None); today = self.today_fn(); qid = hit.id
            try:
                with self._open() as reader:
                    ctx = self._ctx(s, reader, cur, prev, today)
                    body = hit.run(ctx); self._settle(ctx)
            except ReaderError: raise ApiError(503, "Business data is temporarily unavailable. Try again shortly.")
        self.audit.write("intelligence_ask", s["id"], None, question_id=qid, status=body["status"])      # which catalogue entry answered: never the text typed
        return {**body, "question_id": qid, "ai": {"used": False, "provider": ai_interface.status()["provider"], "message": ai_interface.status()["message"]},
                "answered_by": "registered_metrics", "generated_at": self.now_fn().isoformat()}

    def metric(self, s, metric_id, period="wow", date_from=None, date_to=None):
        if not isinstance(metric_id, str) or not METRIC_ID.match(metric_id): self.authorize(s); raise ApiError(404, "Unknown metric.")
        if metric_id not in REGISTRY: self.authorize(s); raise ApiError(404, "Unknown metric.")
        def build(c):
            res = compute(metric_id, c)
            if res.state == R.NO_PERMISSION:
                self.audit.write("permission_denied", s["id"], None, permission=f"metric:{metric_id}", role=s["role"]); raise ApiError(403, "You do not have permission to view this metric.")
            return {"metric": res.to_dict()}
        return self._serve(s, "metric", period, date_from, date_to, build, extra_key=(metric_id,))


def build_router(dsn, session, csrf, audit, service: Optional[IntelligenceService] = None):
    from fastapi import APIRouter, Depends, HTTPException, Response
    from pydantic import BaseModel, ConfigDict, Field
    class AskIn(BaseModel):
        model_config = ConfigDict(extra="forbid")             # unknown fields are rejected, not ignored
        question: str = Field(min_length=1, max_length=ASK.MAX_QUESTION_CHARS * 2)       # hard transport cap; the service applies the real 300-char rule after trimming
        period: str = "wow"
    svc = service or IntelligenceService(lambda: PgReader(dsn()), audit)
    r = APIRouter(prefix="/api/intelligence")
    def call(response, fn):
        response.headers["Cache-Control"] = "no-store"
        try: return fn()
        except ApiError as e: raise HTTPException(e.status, e.detail)

    @r.get("/status")
    def status(response: Response, s=Depends(session)): return call(response, lambda: svc.status(s))
    @r.get("/catalog")
    def metric_catalog(response: Response, s=Depends(session)): return call(response, lambda: svc.catalog(s))
    @r.get("/context")
    def company_context(response: Response, period: str = "wow", date_from: date | None = None, date_to: date | None = None, s=Depends(session)): return call(response, lambda: svc.context(s, period, date_from, date_to))
    @r.get("/overview")
    def overview(response: Response, period: str = "wow", date_from: date | None = None, date_to: date | None = None, s=Depends(session)): return call(response, lambda: svc.overview(s, period, date_from, date_to))
    @r.get("/alerts")
    def get_alerts(response: Response, period: str = "wow", date_from: date | None = None, date_to: date | None = None, s=Depends(session)): return call(response, lambda: svc.alerts(s, period, date_from, date_to))
    @r.get("/insights")
    def get_insights(response: Response, period: str = "wow", date_from: date | None = None, date_to: date | None = None, s=Depends(session)): return call(response, lambda: svc.insights(s, period, date_from, date_to))
    @r.get("/trends")
    def trends(response: Response, period: str = "wow", date_from: date | None = None, date_to: date | None = None, s=Depends(session)): return call(response, lambda: svc.trends(s, period, date_from, date_to))
    def ask_gate(response: Response, s=Depends(csrf)):
        call(response, lambda: svc.require_role(s)); return s       # authorisation first: validation errors never reveal anything to a non-executive
    @r.post("/ask")
    def ask(body: AskIn, response: Response, s=Depends(ask_gate)): return call(response, lambda: svc.ask(s, body.question, body.period))
    @r.get("/metrics/{metric_id}")
    def one_metric(metric_id: str, response: Response, period: str = "wow", date_from: date | None = None, date_to: date | None = None, s=Depends(session)): return call(response, lambda: svc.metric(s, metric_id, period, date_from, date_to))
    return r
