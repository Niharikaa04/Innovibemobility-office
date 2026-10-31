"""GET-only intelligence API. Reuses the app's session dependency (cookie session, per-request role re-check, revocation). There are no
write endpoints, so CSRF does not apply; if a POST (e.g. Ask AI) is added in Stage 3 it MUST use the `csrf` dependency passed in here.
Gate: EXECUTIVE_ROLES only (proposed default ceo, coo, cto: change the tuple to change who may open the executive views). Each metric is
then filtered again by the role's per-module permissions from permissions.py, so a COO or CTO only sees what their role may read; the
rest is reported as `no_permission`. No new permissions are introduced.
All logic lives in IntelligenceService (plain Python, unit-tested); the FastAPI router below only maps requests to it."""
import os
from datetime import date, datetime, timezone
from typing import Optional

from . import ai_interface, alerts, context, metrics, results as R   # noqa: F401  (importing metrics registers every metric)
from .guard import RateLimiter, TTLCache
from .periods import PeriodError, custom, resolve
from .reader import PgReader
from .registry import REGISTRY, Ctx, catalog, compute

EXECUTIVE_ROLES = ("ceo", "coo", "cto")
CACHE_TTL_SECONDS = 30
RATE_LIMIT_PER_MINUTE = 60
TREND_METRICS = ("tickets.trend", "tasks.trend", "leads.trend", "tickets.flow", "tasks.flow", "leads.flow", "expenses.summary")


class ApiError(Exception):
    def __init__(self, status: int, detail: str): super().__init__(detail); self.status, self.detail = status, detail


class IntelligenceService:
    def __init__(self, reader_factory, audit, cache=None, limiter=None, today_fn=None, now_fn=None, extra_location_metrics=None):
        self.reader_factory, self.audit = reader_factory, audit
        self.cache = cache or TTLCache(CACHE_TTL_SECONDS); self.limiter = limiter or RateLimiter(RATE_LIMIT_PER_MINUTE, 60.0)
        self.today_fn = today_fn or date.today; self.now_fn = now_fn or (lambda: datetime.now(timezone.utc).replace(microsecond=0))
        self.extra_loc = extra_location_metrics if extra_location_metrics is not None else (lambda: os.getenv("IOT_EXTRA_LOCATION_METRICS", ""))

    # ---- gates (run on the server for every endpoint; role comes from the verified session, never from the request) ----
    def authorize(self, s):
        if s["role"] not in EXECUTIVE_ROLES:
            self.audit.write("permission_denied", s["id"], None, permission="intelligence.view", role=s["role"]); raise ApiError(403, "You do not have permission to open business intelligence.")
        if not self.limiter.allow(s["id"]): self.audit.write("intelligence_rate_limited", s["id"], None); raise ApiError(429, "Too many requests. Try again in a minute.")

    def periods(self, kind, date_from, date_to):
        try:
            if date_from or date_to:
                if not (date_from and date_to): raise PeriodError("Provide both date_from and date_to, or neither.")
                return custom(date_from, date_to)
            return resolve(kind, self.today_fn())
        except PeriodError as e: raise ApiError(422, str(e))

    def _serve(self, s, endpoint, kind, date_from, date_to, build, extra_key=()):
        self.authorize(s); cur, prev = self.periods(kind, date_from, date_to); today = self.today_fn()
        key = TTLCache.key(s["id"], s["role"], endpoint, cur.start, cur.end, today, *extra_key)       # user AND role are part of every key
        hit = self.cache.get(key)
        if hit is not None: return {**hit, "cached": True}
        with self.reader_factory() as reader:
            ctx = Ctx(reader=reader, role=s["role"], user_id=s["id"], period=cur, prev=prev, today=today, as_of=self.now_fn(), extra_location_metrics=self.extra_loc())
            body = build(ctx)
        body = {**body, "generated_at": ctx.as_of.isoformat(), "cached": False}
        self.cache.put(key, body); self.audit.write("intelligence_view", s["id"], None, endpoint=endpoint)     # endpoint name only: never data, never a question
        return body

    # ---- endpoints ----
    def status(self, s):
        self.authorize(s); return {"roles": list(EXECUTIVE_ROLES), "role": s["role"], "ai": ai_interface.status(), "metrics": len(REGISTRY), "periods": ["last_7d", "last_30d", "wow", "mom"], "max_range_days": 366}
    def catalog(self, s): self.authorize(s); return {"metrics": catalog(s["role"])}
    def context(self, s, period="wow", date_from=None, date_to=None): return self._serve(s, "context", period, date_from, date_to, context.build_context)
    def overview(self, s, period="wow", date_from=None, date_to=None): return self._serve(s, "overview", period, date_from, date_to, alerts.build_overview)
    def alerts(self, s, period="wow", date_from=None, date_to=None): return self._serve(s, "alerts", period, date_from, date_to, lambda c: {"alerts": alerts.build_alerts(c), "gaps": alerts.build_gaps(c)})
    def insights(self, s, period="wow", date_from=None, date_to=None): return self._serve(s, "insights", period, date_from, date_to, lambda c: {"insights": alerts.build_insights(c)})
    def trends(self, s, period="wow", date_from=None, date_to=None): return self._serve(s, "trends", period, date_from, date_to, lambda c: {"trends": {m: compute(m, c).to_dict() for m in TREND_METRICS}})

    def metric(self, s, metric_id, period="wow", date_from=None, date_to=None):
        if metric_id not in REGISTRY: self.authorize(s); raise ApiError(404, "Unknown metric.")
        def build(c):
            res = compute(metric_id, c)
            if res.state == R.NO_PERMISSION:
                self.audit.write("permission_denied", s["id"], None, permission=f"metric:{metric_id}", role=s["role"]); raise ApiError(403, "You do not have permission to view this metric.")
            return {"metric": res.to_dict()}
        return self._serve(s, "metric", period, date_from, date_to, build, extra_key=(metric_id,))


def build_router(dsn, session, csrf, audit, service: Optional[IntelligenceService] = None):
    from fastapi import APIRouter, Depends, HTTPException, Response
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
    @r.get("/metrics/{metric_id}")
    def one_metric(metric_id: str, response: Response, period: str = "wow", date_from: date | None = None, date_to: date | None = None, s=Depends(session)): return call(response, lambda: svc.metric(s, metric_id, period, date_from, date_to))
    return r
