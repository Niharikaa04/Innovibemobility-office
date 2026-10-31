"""Authoritative metric registry. EVERY number the product shows (cards, alerts, insights, trends, future AI answers) comes from
`compute(metric_id, ctx)`. Results are memoised per request in ctx.memo, so two consumers can never disagree.

Server-side gates applied BEFORE any SQL runs: (1) role must hold every permission the metric declares (permissions.py, no new
permissions); (2) own-only roles never get aggregate company metrics; (3) every source table must exist (migration applied)."""
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable, Optional

import permissions
from . import results as R
from .periods import Period
from .reader import Reader, ReaderError

log = logging.getLogger("intelligence")


@dataclass
class Ctx:
    reader: Reader
    role: str
    user_id: str
    period: Period
    prev: Optional[Period]
    today: date
    as_of: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    extra_location_metrics: str = ""
    memo: dict = field(default_factory=dict)
    def can(self, perm: str) -> bool: return permissions.can(self.role, perm)
    def own_only(self, module: str) -> bool: return permissions.is_own_only(self.role, module)
    def location_access(self) -> str:
        import locationpolicy; return locationpolicy.location_access(self.role, self.can("location.read"))


@dataclass(frozen=True)
class MetricDef:
    id: str
    label: str
    module: str                  # business module key for drill-down links
    perms: tuple                 # ALL required, e.g. ("tickets.read",)
    sources: tuple               # table names under office_dashboard that must exist
    description: str             # plain-language definition (shown in the catalog)
    unit: str
    reliability: str             # system_recorded | user_entered | derived | statistical
    fn: Callable                 # fn(ctx, d: MetricDef) -> MetricResult
    kind: str = "snapshot"       # snapshot | flow | composite
    any_of: tuple = ()           # composites: at least ONE of these permissions is required (each part is still gated on its own)


REGISTRY: dict = {}


def metric(id, label, module, perms, sources, description, unit="count", reliability="system_recorded", kind="snapshot", any_of=()):
    def deco(fn):
        assert id not in REGISTRY, f"duplicate metric {id}"
        for p in (*perms, *any_of): assert p.split(".")[1] in permissions.ACTIONS, p
        assert perms or any_of, f"{id} must declare the permissions it needs"      # a metric with no permission would be readable by every role
        REGISTRY[id] = MetricDef(id, label, module, tuple(perms), tuple(sources), description, unit, reliability, fn, kind, tuple(any_of)); return fn
    return deco


def blank(d: MetricDef, ctx: Ctx, state: str, message: str = "", **kw) -> R.MetricResult:
    """Result with no value. Used for every non-available state."""
    assert state not in R.USABLE
    return R.MetricResult(d.id, d.label, state, None, d.unit, message, as_of=ctx.as_of.isoformat(), reliability=d.reliability,
                          period=ctx.period.to_dict() if d.kind == "flow" else None, link={"module": d.module}, **kw)


def compute(metric_id: str, ctx: Ctx) -> R.MetricResult:
    if metric_id not in REGISTRY: raise KeyError(metric_id)
    if metric_id in ctx.memo: return ctx.memo[metric_id]
    d = REGISTRY[metric_id]
    res = _gated(d, ctx)
    ctx.memo[metric_id] = res; return res


def _own(role, p): return permissions.is_own_only(role, p.split(".")[0])


def permitted(d: MetricDef, role: str) -> bool:
    """THE permission rule: used by the gate, the catalogue and the AI tool list so they can never disagree.
    Needs every permission in d.perms, at least one of d.any_of, and none of them may be an own-records-only grant."""
    ok = all(permissions.can(role, p) and not _own(role, p) for p in d.perms)
    return ok and (not d.any_of or any(permissions.can(role, p) and not _own(role, p) for p in d.any_of))


def _gated(d: MetricDef, ctx: Ctx) -> R.MetricResult:
    if any(not ctx.can(p) for p in d.perms) or (d.any_of and not any(ctx.can(p) for p in d.any_of)):
        return blank(d, ctx, R.NO_PERMISSION, "Your role does not have access to this source.")
    if not permitted(d, ctx.role):
        return blank(d, ctx, R.NO_PERMISSION, "Company-wide figures are not available for roles limited to their own records.")
    try:
        absent = [t for t in d.sources if not ctx.reader.has_table(t)]
        if absent: return blank(d, ctx, R.UNAVAILABLE, "This module's database tables are not set up yet (migration not applied).")
        res = d.fn(ctx, d)
    except ReaderError as e:
        return blank(d, ctx, R.UNAVAILABLE, "The source timed out." if e.kind == "timeout" else "The source could not be read right now.")
    except Exception as e:     # a bug in one metric must never take down the dashboard or leak a stack trace
        log.error("metric %s failed: %s", d.id, type(e).__name__); return blank(d, ctx, R.UNAVAILABLE, "This metric could not be calculated.")
    if not res.as_of: res.as_of = ctx.as_of.isoformat()
    if not res.link: res.link = {"module": d.module}
    return res


def catalog(role: str) -> list:
    """Metric definitions with whether THIS role may read them (no data)."""
    return [{"id": d.id, "label": d.label, "module": d.module, "description": d.description, "unit": d.unit, "reliability": d.reliability,
             "kind": d.kind, "sources": [f"office_dashboard.{t}" for t in d.sources],
             "permitted": permitted(d, role)}
            for d in sorted(REGISTRY.values(), key=lambda x: x.id)]
