"""Standard result states and evidence structures. Pure Python.
Rule: unavailable data is NEVER represented as zero. `value` is None unless the state is AVAILABLE or PARTIAL."""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

AVAILABLE = "available"                      # computed from real rows; value is trustworthy for the stated period
PARTIAL = "partial"                          # computed, but some sources/rows were missing, truncated or not permitted
NO_DATA = "no_data"                          # the source exists but holds no records at all (nothing to compute from)
NOT_ENOUGH_HISTORY = "not_enough_history"    # a comparison/trend/anomaly needs more history than the system holds
NO_THRESHOLD = "no_threshold_configured"     # the metric cannot be judged because nobody configured a limit
NO_PERMISSION = "no_permission"              # this user's role may not see this source (server-side decision)
NOT_CONFIGURED = "not_configured"            # a prerequisite setting does not exist yet (e.g. attendance policy)
UNAVAILABLE = "unavailable"                  # table missing (migration not applied), query failed or timed out
STATES = (AVAILABLE, PARTIAL, NO_DATA, NOT_ENOUGH_HISTORY, NO_THRESHOLD, NO_PERMISSION, NOT_CONFIGURED, UNAVAILABLE)
USABLE = (AVAILABLE, PARTIAL)

# Statement kinds: every sentence the product shows must carry exactly one of these.
FACT, CALCULATED, POSSIBLE, RECOMMENDATION, UNAVAILABLE_INFO = "verified_fact", "calculated_metric", "possible_explanation", "recommendation", "unavailable"
STATEMENT_KINDS = (FACT, CALCULATED, POSSIBLE, RECOMMENDATION, UNAVAILABLE_INFO)

NO_THRESHOLD_LABEL = "No threshold configured"
NOT_ENOUGH_HISTORY_LABEL = "Not enough history"


def iso(v: Any) -> Optional[str]:
    if v is None: return None
    if isinstance(v, (datetime, date)): return v.isoformat()
    return str(v)


@dataclass
class Evidence:
    source: str                       # table(s) the numbers came from, e.g. "office_dashboard.service_tickets"
    method: str                       # plain-language calculation, e.g. "count of non-archived tickets whose status is not COMPLETED/CUSTOMER_CONFIRMATION/CLOSED and due_date < today"
    row_count: Optional[int] = None   # rows that contributed
    record_ids: list = field(default_factory=list)   # a capped sample of record ids for drill-down (ids only, never free text)
    note: str = ""

    def to_dict(self): return {"source": self.source, "method": self.method, "row_count": self.row_count, "record_ids": self.record_ids[:10], "note": self.note}


@dataclass
class MetricResult:
    metric_id: str
    label: str
    state: str
    value: Any = None
    unit: str = ""
    message: str = ""                                   # why the state is not AVAILABLE (user-safe text, never raw exception text)
    breakdown: list = field(default_factory=list)       # rows of allow-listed fields
    detail: dict = field(default_factory=dict)          # extra named numbers that belong to this metric
    period: Optional[dict] = None
    comparison: Optional[dict] = None                   # previous-period block (has its own state)
    as_of: str = ""
    freshness: dict = field(default_factory=dict)       # {"latest_source_update_at": iso|None, "age_hours": float|None}
    evidence: list = field(default_factory=list)
    limitations: list = field(default_factory=list)
    threshold: dict = field(default_factory=lambda: {"configured": False, "label": NO_THRESHOLD_LABEL})
    reliability: str = "system_recorded"                # system_recorded | user_entered | derived | statistical
    link: dict = field(default_factory=dict)            # {"module": ..., "api_path": ..., "filter": {...}} for drill-down

    def usable(self) -> bool: return self.state in USABLE

    def to_dict(self) -> dict:
        assert self.state in STATES, self.state
        assert self.usable() or self.value is None, "unavailable data must never carry a value"
        return {"metric_id": self.metric_id, "label": self.label, "state": self.state, "value": self.value, "unit": self.unit, "message": self.message,
                "breakdown": self.breakdown, "detail": self.detail, "period": self.period, "comparison": self.comparison, "as_of": self.as_of,
                "freshness": self.freshness, "evidence": [e.to_dict() for e in self.evidence], "limitations": self.limitations,
                "threshold": self.threshold, "reliability": self.reliability, "link": self.link}
