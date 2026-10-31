"""Ask Your Business: deterministic, server-side question answering over the metric registry.

Design rules (each one is enforced by tests in tests/test_intel_ask.py):
  * The question text is DATA. It is used only to pick one entry from the fixed QUESTIONS catalogue (regex/exact match). It is never
    executed, never interpolated into SQL, never sent to a model and never echoed back, so prompt injection has nothing to act on.
  * Every number in an answer comes from compute() / build_alerts() / build_insights(): the same registry the dashboard cards use, run
    with the SESSION's role. A metric the role may not read, or that is missing/unavailable, becomes an explicit 'unavailable' statement.
    It is never turned into 0.
  * Every answer lists its sources (metric id, state, period, freshness, reliability and the evidence source/method/row count).
  * Questions about things the system does not hold (profit, churn, forecasts, employee ranking, cash) or that ask for sensitive data
    (salaries, credentials, personal contact details) get a 'limitation' answer and read NO data.
  * No AI provider is called. ai_interface.status() reports degraded mode; if a provider is approved later it must be reached only through
    ai_interface.redact_for_ai().
"""
import re
from dataclasses import dataclass
from typing import Callable

from . import alerts as AL
from . import results as R
from .registry import Ctx, compute

MAX_QUESTION_CHARS = 300
PERIOD_CHOICES = ("wow", "mom", "last_7d", "last_30d")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class QuestionError(ValueError):
    """Invalid question input (empty, too long). The message is user-safe."""


def clean_question(text) -> str:
    if not isinstance(text, str): raise QuestionError("The question must be text.")
    t = _CTRL.sub(" ", text).strip()
    t = re.sub(r"\s+", " ", t)
    if not t: raise QuestionError("Type a question first.")
    if len(t) > MAX_QUESTION_CHARS: raise QuestionError(f"Questions may be at most {MAX_QUESTION_CHARS} characters.")
    return t


# ---------------- answer building ----------------
def fmt(n) -> str:
    if n is None: return "unknown"
    if isinstance(n, float) and not n.is_integer(): return f"{n:,.2f}"
    return f"{int(n):,}"


def plural(n, one, many=None) -> str: return f"{fmt(n)} {one if n == 1 else (many or one + 's')}"


def st(kind, text, metric_id=None): return {"kind": kind, "text": text, "metric_id": metric_id}


STATE_TEXT = {R.NO_DATA: "No data recorded", R.NOT_ENOUGH_HISTORY: "Not enough history", R.NO_THRESHOLD: "No threshold configured", R.NO_PERMISSION: "No permission",
              R.NOT_CONFIGURED: "Not configured", R.UNAVAILABLE: "Unavailable", R.PARTIAL: "Partial data", R.AVAILABLE: "Available"}


def gap(r) -> dict:
    """A metric that cannot be used is reported as such: never as zero."""
    msg = f" ({r.message})" if r.message else ""
    return st(R.UNAVAILABLE_INFO, f"{r.label}: {STATE_TEXT.get(r.state, r.state)}{msg}.", r.metric_id)


def source_of(r) -> dict:
    return {"metric_id": r.metric_id, "label": r.label, "state": r.state, "as_of": r.as_of, "period": f"{r.period['start']} to {r.period['end']}" if r.period else None,
            "updated": (r.freshness or {}).get("latest_source_update_at"), "reliability": r.reliability,
            "evidence": [{"source": e.source, "method": e.method, "row_count": e.row_count} for e in r.evidence]}


def answer(title, statements, results, followups=(), link=None, status="answer") -> dict:
    return {"status": status, "title": title, "statements": statements, "sources": [source_of(r) for r in results], "followups": list(followups), "link": link or {}}


def limitation(title, why, needed, followups=()) -> dict:
    return {"status": "limitation", "title": title, "statements": [st(R.UNAVAILABLE_INFO, why), st(R.RECOMMENDATION, needed)], "sources": [], "followups": list(followups), "link": {}}


def _g(ctx, *ids): return [compute(i, ctx) for i in ids]


# ---------------- question handlers (each reads ONLY through the registry) ----------------
def q_attention(ctx):
    a = AL.build_alerts(ctx)
    s = [st(R.FACT, f"#{x['rank']} {x['title']} ({x['severity']}). {x['recommended_next_step']}", x["metric_id"]) for x in a[:5]] or [st(R.FACT, "No alert rule is currently triggered for the metrics your role can read.")]
    s.append(st(R.UNAVAILABLE_INFO, "Ranking uses recorded severity fields only; no SLA or company policy is applied."))
    gaps = [g for g in AL.build_gaps(ctx) if g["state"] in (R.UNAVAILABLE,)]
    if gaps: s.append(st(R.UNAVAILABLE_INFO, f"{len(gaps)} metric(s) could not be read right now, so this list may be incomplete."))
    return answer("What needs attention first", s, [compute(x["metric_id"], ctx) for x in a[:5]], ("What is delayed right now?", "What are the three biggest operational risks?"), a[0]["link"] if a else None)


def q_risks(ctx):
    a = AL.build_alerts(ctx)[:3]
    s = [st(R.FACT, f"#{x['rank']} {x['title']}. Severity basis: {x['severity_basis']}", x["metric_id"]) for x in a] or [st(R.FACT, "No alert rule is currently triggered for the metrics your role can read.")]
    return answer("Top operational risks", s, [compute(x["metric_id"], ctx) for x in a], ("What needs my attention today?", "What information is missing from my dashboard?"), a[0]["link"] if a else None)


def q_delayed(ctx):
    t, k, l, i = rs = _g(ctx, "tasks.overdue", "tickets.overdue", "leads.followups_overdue", "invoices.receivables"); s = []
    s.append(st(R.FACT, f"{plural(t.value, 'task')} past their due date" + (f"; the oldest was due {t.detail['oldest_due_date']}" if t.detail.get("oldest_due_date") else "") + ".", t.metric_id) if t.usable() else gap(t))
    s.append(st(R.FACT, f"{plural(k.value, 'open service ticket')} past their due date" + (f"; the oldest was due {k.detail['oldest_due_date']}" if k.detail.get("oldest_due_date") else "") + ".", k.metric_id) if k.usable() else gap(k))
    s.append(st(R.FACT, f"{plural(l.value, 'lead')} past their follow-up date.", l.metric_id) if l.usable() else gap(l))
    s.append(st(R.CALCULATED, f"{plural(i.detail['overdue_count'], 'invoice')} overdue, balance {fmt(i.detail['overdue_amount'])} (currency as recorded on the invoices).", i.metric_id) if i.usable() else gap(i))
    return answer("What is delayed", s, rs, ("Why has our service backlog increased?", "Which leads need follow-up?"), {"module": "tickets", "filter": {"overdue": True}})


def _insight(ctx, card_id, title, followups):
    card = next((c for c in AL.build_insights(ctx) if c["id"] == card_id), None)
    if not card: return answer(title, [st(R.UNAVAILABLE_INFO, "This analysis could not be built from the data currently available to your role.")], [], followups)
    return answer(title, card["statements"], [compute(m, ctx) for m in card["metric_ids"]], followups, card["link"])


def q_backlog(ctx): return _insight(ctx, "service_backlog", "Service backlog", ("Which service centers have the highest ticket backlog?", "Are any technicians handling a disproportionately large workload?"))
def q_finance(ctx): return _insight(ctx, "receivables_expenses", "Receivables and expenses", ("What is delayed right now?", "What information is missing from my dashboard?"))


def q_approvals(ctx):
    (r,) = _g(ctx, "approvals.pending")
    if not r.usable(): return answer("Pending approvals", [gap(r)], [r])
    s = [st(R.CALCULATED, f"{plural(r.value, 'decision')} waiting across modules.", r.metric_id)] + [st(R.FACT, f"{b['module']}: {b['count']}", r.metric_id) for b in r.breakdown if b["count"]]
    if r.state == R.PARTIAL: s.append(st(R.UNAVAILABLE_INFO, "Some modules were not readable for your role or are not set up: " + " ".join(r.limitations), r.metric_id))
    return answer("Pending approvals", s, [r], ("What needs my attention today?", "What is delayed right now?"), {"module": "approvals"})


def q_centers(ctx):
    (r,) = _g(ctx, "tickets.by_service_center")
    if not r.usable(): return answer("Backlog by service center", [gap(r)], [r])
    s = [st(R.CALCULATED, f"{b['service_center'] or 'Unnamed center'}: {b['open']} open ({b['share_pct']}% of open tickets), {b['overdue']} overdue.", r.metric_id) for b in r.breakdown[:5]]
    if not s: s.append(st(R.UNAVAILABLE_INFO, "No open ticket is linked to a service center.", r.metric_id))
    if r.detail.get("unlinked_open"): s.append(st(R.FACT, f"{plural(r.detail['unlinked_open'], 'open ticket')} have no service center recorded, so they cannot be attributed to any center.", r.metric_id))
    return answer("Backlog by service center", s, [r], ("Why has our service backlog increased?", "Are any technicians handling a disproportionately large workload?"), {"module": "tickets"})


def q_workload(ctx):
    (r,) = _g(ctx, "tickets.technician_workload")
    if not r.usable(): return answer("Technician workload", [gap(r)], [r])
    x = r.detail.get("distribution") or {}; s = []
    if x.get("owners"): s.append(st(R.CALCULATED, f"{x['owners']} technicians hold {x['total']} open tickets (average {x['mean']}); the busiest holds {x['max']} ({x['max_share_pct']}%).", r.metric_id))
    else: s.append(st(R.UNAVAILABLE_INFO, "No open ticket is assigned to a technician.", r.metric_id))
    if r.detail.get("unassigned_open"): s.append(st(R.FACT, f"{plural(r.detail['unassigned_open'], 'open ticket')} are not assigned to anyone.", r.metric_id))
    s.append(st(R.UNAVAILABLE_INFO, "No workload limit is configured, so the system does not label any load as disproportionate. Counts are not weighted by job size.", r.metric_id))
    return answer("Technician workload", s, [r], ("Which service centers have the highest ticket backlog?",), {"module": "technicians"})


def q_leads(ctx):
    f, p = rs = _g(ctx, "leads.followups_overdue", "leads.pipeline"); s = []
    s.append(st(R.FACT, f"{plural(f.value, 'open lead')} past their follow-up date" + (f"; oldest follow-up date {f.detail['oldest_follow_up']}" if f.detail.get("oldest_follow_up") else "") + ".", f.metric_id) if f.usable() else gap(f))
    s.append(st(R.CALCULATED, f"{plural(p.value, 'open lead')} in the pipeline (stage values are user-entered).", p.metric_id) if p.usable() else gap(p))
    return answer("Lead follow-ups", s, rs, ("What is delayed right now?",), {"module": "leads"})


def q_faults(ctx):
    rp, un = rs = _g(ctx, "diagnostics.repeated", "diagnostics.active_unlinked"); s = []
    s.append(st(R.CALCULATED, f"{plural(rp.value, 'vehicle and fault-code pair')} recorded 2 or more times in the period.", rp.metric_id) if rp.usable() else gap(rp))
    s.append(st(R.FACT, f"{plural(un.value, 'active fault')} have no ticket linked.", un.metric_id) if un.usable() else gap(un))
    s.append(st(R.RECOMMENDATION, "Open EVcare.AI Diagnostics to see the vehicles; individual vehicle identifiers are not repeated here."))
    return answer("Repeated faults", s, rs, ("Are any connected IoT devices reporting unusual readings?",), {"module": "diagnostics"})


def q_iot(ctx):
    t, a, c = rs = _g(ctx, "iot.threshold_alerts", "iot.anomalies", "iot.connectivity"); s = []
    s.append(st(R.FACT, f"{plural(t.value, 'reading')} outside limits someone configured ({t.detail.get('critical', 0)} critical, {t.detail.get('warning', 0)} warning).", t.metric_id) if t.usable() else gap(t))
    s.append(st(R.CALCULATED, f"{plural(a.value, 'reading')} flagged by the statistical screen. This is not a company threshold.", a.metric_id) if a.usable() else gap(a))
    s.append(st(R.FACT, f"{plural(c.value, 'device')} beyond their own offline limit; {c.detail.get('never_reported', 0)} never reported.", c.metric_id) if c.usable() else gap(c))
    return answer("IoT and telemetry", s, rs, ("Which vehicles have repeated faults?",), {"module": "iot"})


def _cmp(r) -> str:
    c = r.comparison or {}
    if c.get("state") == R.AVAILABLE:
        p = c.get("pct_change"); return f"Previous period {fmt(c['previous_value'])}" + (f" ({p:+.1f}%)" if p is not None else "") + "."
    return "Not enough history to compare."


def q_compare(ctx):
    tk, ts, ld, ex = rs = _g(ctx, "tickets.flow", "tasks.flow", "leads.flow", "expenses.summary")
    s = [st(R.CALCULATED, "Comparison uses the current month so far against the previous month (month on month).")]
    s.append(st(R.CALCULATED, f"Tickets: {tk.detail['created']} created, {tk.detail['resolved']} resolved, net {tk.detail['net_inflow']:+d}. {_cmp(tk)}", tk.metric_id) if tk.usable() else gap(tk))
    s.append(st(R.CALCULATED, f"Tasks: {ts.detail.get('created')} created, {ts.detail.get('completed')} completed. {_cmp(ts)}", ts.metric_id) if ts.usable() else gap(ts))
    s.append(st(R.CALCULATED, f"Leads: {ld.detail.get('created')} created, {ld.detail.get('converted')} converted. {_cmp(ld)}", ld.metric_id) if ld.usable() else gap(ld))
    s.append(st(R.CALCULATED, f"Approved expenses: {fmt(ex.value)}. {_cmp(ex)}", ex.metric_id) if ex.usable() else gap(ex))
    s.append(st(R.UNAVAILABLE_INFO, "Open-backlog size at an earlier date is not stored, so only flows (created and resolved) can be compared."))
    return answer("This month vs last month", s, rs, ("Why has our service backlog increased?",))


def q_missing(ctx):
    g = AL.build_gaps(ctx)
    s = [st(R.UNAVAILABLE_INFO, f"{x['label']}: {STATE_TEXT.get(x['state'], x['state'])}" + (f" ({x['message']})" if x["message"] and x["message"] != STATE_TEXT.get(x["state"]) else "") + ".", x["metric_id"]) for x in g] or [st(R.FACT, "Every metric your role can read returned data.")]
    return answer("Missing or unavailable information", s, [], ("What needs my attention today?",))


def q_teams(ctx):
    return limitation("Team performance", "No performance target, scoring rule or department mapping exists in the system, so teams cannot be ranked or scored reliably.",
                      "To answer this, someone must define the performance measures (for example on-time completion targets) and map employees to departments. What exists today: technician ticket distribution, and overdue tasks and tickets.",
                      ("Are any technicians handling a disproportionately large workload?", "What is delayed right now?"))


@dataclass(frozen=True)
class Question:
    id: str
    label: str
    patterns: tuple
    run: Callable
    period: str = ""       # non-empty: this question always uses that comparison period, whatever the caller picked


QUESTIONS = (
    Question("attention", "What needs my attention today?", (r"attention", r"review first", r"this morning", r"prioriti[sz]e", r"what should i (do|review)"), q_attention),
    Question("risks", "What are the three biggest operational risks?", (r"biggest.*risk", r"top.*risk", r"three.*risk", r"main risk"), q_risks),
    Question("delayed", "What is delayed right now?", (r"delay", r"overdue", r"late\b", r"behind schedule", r"past (their )?due"), q_delayed),
    Question("backlog", "Why has our service backlog increased?", (r"backlog", r"why.*ticket", r"service.*(increase|grow|rise)", r"overdue.*ticket"), q_backlog),
    Question("approvals", "How many approvals are pending, and where?", (r"approval", r"pending decision", r"awaiting"), q_approvals),
    Question("centers", "Which service centers have the highest ticket backlog?", (r"service cent", r"garage", r"highest.*backlog"), q_centers),
    Question("workload", "Are any technicians handling a disproportionately large workload?", (r"technician", r"workload", r"work ?load", r"disproportion"), q_workload),
    Question("leads", "Which leads need follow-up?", (r"lead", r"follow.?up", r"pipeline"), q_leads),
    Question("finance", "What is happening with our receivables and expenses?", (r"receivable", r"expense", r"invoice", r"budget", r"spend"), q_finance),
    Question("faults", "Which vehicles have repeated faults?", (r"repeat", r"fault", r"diagnos", r"vehicle", r"recurr"), q_faults),
    Question("iot", "Are any connected IoT devices reporting unusual readings?", (r"iot", r"telemetry", r"device", r"unusual", r"anomal", r"sensor"), q_iot),
    Question("compare", "Compare this month's operations with last month", (r"compare", r"last month", r"previous (month|week|period)", r"month.?on.?month", r"versus|vs\.?\b"), q_compare, period="mom"),
    Question("missing", "What information is missing from my dashboard?", (r"missing", r"not available", r"what data", r"coverage", r"gap"), q_missing),
    Question("teams", "How is performance across teams?", (r"team", r"performance", r"department"), q_teams),
)
BY_ID = {q.id: q for q in QUESTIONS}
SUGGESTIONS = tuple(q.label for q in QUESTIONS)

# Things the system does not hold: answered with an explanation, no data is read.
UNSUPPORTED = (
    (r"gross margin|margin|profit", "Profit and margin", "Profit and gross margin are not reported: the system has no approved definition or cost ledger for them.", "An agreed definition (which revenue, which costs) and a source of cost-of-service records are needed. Invoices, receivables, expenses and budgets are available."),
    (r"churn|retention", "Customer churn", "Customer churn is not calculated: there is no approved churn definition and no recorded customer activity history to base it on.", "A definition of an active customer and dated customer activity are needed."),
    (r"forecast|predict|future revenue|next (quarter|year|month) revenue|projection", "Forecasts", "Forecasts are not produced. Only recorded history is analysed; nothing is projected.", "A forecasting method approved by management and enough revenue history. Budget lines you entered are available."),
    (r"(rank|best|worst|top|bottom).*(employee|staff|people|person)|employee.*(rank|performance)", "Employee ranking", "Employees are not ranked or scored: no performance measure has been defined, and doing so from activity counts would be misleading.", "An approved performance framework is required. Aggregate workload counts are available."),
    (r"cash (balance|flow|position)|runway|burn", "Cash position", "Cash balance, burn and runway are not reported: no bank or ledger data is connected.", "A bank or accounting connection or an approved manual cash register is required."),
)
# Requests for sensitive data or attempts to steer the system: refused without matching any metric and without reading any data.
SENSITIVE = (
    (r"salar(y|ies)|payroll|wages?|compensation|bonus", "Salary and payroll", "Salary and payroll data are not exposed through Ask your business."),
    (r"password|passcode|credential|secret|api[ _-]?key|access[ _-]?token|session (token|cookie)|\btoken\b", "Credentials and secrets", "Credentials, tokens and secrets are never available through Ask your business."),
    (r"(phone|mobile|email|e-mail|home address|personal address|aadhaar|pan number|tax id)", "Personal contact details", "Personal contact and identity details are not returned by Ask your business."),
    (r"(where is|locate|track|gps|live location|current location).*(driver|technician|employee|staff|person|vehicle)", "Individual location", "Locating individual people or vehicles is not available here. Use the Fleet and IoT screens, which apply the location policy for your role."),
    (r"ignore (all |any |the )?(previous|prior|above|earlier)|disregard (all |any |the )?(previous|prior|above|instructions)|system prompt|developer message|you are now|\bact as\b|pretend to be|jailbreak|override (your|the) (rules|instructions|permissions)|reveal (your|the) (instructions|prompt)",
     "Instruction override", "Ask your business answers only from the registered business metrics. It does not follow instructions that try to change its rules."),
    (r"\b(drop|truncate|alter)\s+(table|database)\b|\bdelete\s+from\b|\binsert\s+into\b|\bupdate\s+\w+\s+set\b|;\s*--|\bunion\s+select\b|\bselect\b.+\bfrom\b", "Database commands", "Ask your business does not run database commands. It is read-only and answers from registered metrics."),
)
_UNSUP = tuple((re.compile(p), *rest) for p, *rest in UNSUPPORTED)
_SENS = tuple((re.compile(p, re.I), *rest) for p, *rest in SENSITIVE)
_QPAT = {q.id: tuple(re.compile(p) for p in q.patterns) for q in QUESTIONS}


def resolve(text: str):
    """-> ('question', Question) | ('limitation', answer dict) | ('none', None). Pure function of the cleaned text: no I/O."""
    t = text.lower().strip()
    exact = next((q for q in QUESTIONS if q.label.lower() == t), None)
    if exact: return "question", exact
    for rx, title, why in _SENS: 
        if rx.search(t): return "limitation", limitation(title, why, "Ask about registered business metrics instead, for example overdue work, backlog, approvals or receivables.", ("What needs my attention today?", "What information is missing from my dashboard?"))
    for rx, title, why, needed in _UNSUP:
        if rx.search(t): return "limitation", limitation(title, why, needed, ("What information is missing from my dashboard?", "What needs my attention today?"))
    best, score = None, 0
    for q in QUESTIONS:
        sc = sum(1 for rx in _QPAT[q.id] if rx.search(t))
        if sc > score: best, score = q, sc
    return ("question", best) if best else ("none", None)


NO_MATCH_TEXT = "No AI provider is configured, so only the registered business questions can be answered, from real data. Try one of the suggested questions."


def no_match() -> dict:
    return {"status": "no_match", "title": "I cannot answer that yet", "statements": [st(R.UNAVAILABLE_INFO, NO_MATCH_TEXT)], "sources": [], "followups": list(SUGGESTIONS[:3]), "link": {}}
