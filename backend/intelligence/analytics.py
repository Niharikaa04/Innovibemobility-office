"""Pure statistics helpers. No I/O. Everything here is deterministic and unit-tested."""
from datetime import date, datetime, timezone
from statistics import median
from typing import Optional

AGEING_EDGES_DAYS = (3, 8, 15, 31)
AGEING_LABELS = ("0-2 days", "3-7 days", "8-14 days", "15-30 days", "31+ days")   # descriptive buckets, NOT an SLA

# Robust anomaly method (documented in docs/INTELLIGENCE.md): modified z-score (Iglewicz & Hoaglin) on median/MAD, with the MeanAD fallback when MAD is 0.
# 3.5 is the conventional cut-off for that statistic. It is a statistical convention, NOT a company threshold.
MIN_BASELINE_POINTS = 30
MODIFIED_Z_CUTOFF = 3.5


def to_dt(v) -> Optional[datetime]:
    """datetime | date | ISO string | None -> aware UTC datetime (naive values are taken as UTC)."""
    if v is None: return None
    if isinstance(v, str): v = datetime.fromisoformat(v.replace("Z", "+00:00")) if "T" in v or " " in v else datetime.fromisoformat(v)
    if isinstance(v, datetime): return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, date): return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)
    raise TypeError(type(v).__name__)


def to_date(v) -> Optional[date]:
    if v is None: return None
    if isinstance(v, datetime): return v.date()
    if isinstance(v, date): return v
    return date.fromisoformat(str(v)[:10])


def age_hours(then, now: datetime) -> Optional[float]:
    t = to_dt(then); return None if t is None else round((now - t).total_seconds() / 3600, 1)


def pct_change(current, previous) -> Optional[float]:
    """% change, None when the previous value is 0 (a percentage of zero is undefined, never invent one)."""
    if previous in (0, None) or current is None: return None
    return round((current - previous) / previous * 100, 1)


def share_pct(part, whole) -> Optional[float]:
    return None if not whole else round(part / whole * 100, 1)


def bucket_ageing(cumulative_newer_than_edge: list, total: int) -> list:
    """cumulative_newer_than_edge[i] = number of tickets younger than AGEING_EDGES_DAYS[i] days. Returns bucket counts (len 5), summing to total."""
    counts, prev = [], 0
    for c in cumulative_newer_than_edge: counts.append(c - prev); prev = c
    counts.append(total - prev)
    if any(c < 0 for c in counts): raise ValueError("cumulative counts must be non-decreasing and <= total")
    return counts


def workload_distribution(counts: dict) -> dict:
    """counts: {owner_key: open_items}. Facts only: no judgement about what is 'too much' (no threshold exists)."""
    vals = [v for v in counts.values()]
    if not vals: return {"owners": 0}
    total, n = sum(vals), len(vals); mean = total / n; top = max(counts, key=lambda k: (counts[k], str(k)))
    return {"owners": n, "total": total, "mean": round(mean, 2), "max": counts[top], "max_owner": top,
            "max_share_pct": share_pct(counts[top], total), "max_over_mean": round(counts[top] / mean, 2) if mean else None}


def modified_z(history: list, latest: float) -> Optional[float]:
    """Modified z-score of `latest` against `history` (Iglewicz & Hoaglin): 0.6745*(x-median)/MAD.
    When MAD is 0 (common for sensors reported in coarse steps, where more than half the readings are identical) the documented fallback is
    (x-median)/(1.253314*MeanAD). None when the spread is zero either way (a perfectly constant series gives no basis for a score) or the history is too short."""
    if len(history) < MIN_BASELINE_POINTS: return None
    med = median(history); dev = [abs(x - med) for x in history]; mad = median(dev)
    if mad != 0: return round(0.6745 * (latest - med) / mad, 2)
    mean_ad = sum(dev) / len(dev)
    if mean_ad == 0: return None
    return round((latest - med) / (1.253314 * mean_ad), 2)


def detect_anomaly(history: list, latest: float) -> dict:
    """-> {"state": "not_enough_history"|"not_computable"|"normal"|"anomalous", ...}. `history` EXCLUDES the latest reading."""
    if len(history) < MIN_BASELINE_POINTS: return {"state": "not_enough_history", "baseline_points": len(history), "required": MIN_BASELINE_POINTS}
    z = modified_z(history, latest)
    if z is None: return {"state": "not_computable", "baseline_points": len(history), "reason": "all baseline readings are identical, so there is no spread to score against"}
    return {"state": "anomalous" if abs(z) > MODIFIED_Z_CUTOFF else "normal", "modified_z": z, "baseline_median": round(median(history), 3), "baseline_points": len(history), "cutoff": MODIFIED_Z_CUTOFF}
