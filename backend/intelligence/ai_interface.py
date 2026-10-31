"""Provider-independent AI interface (Stage 1: NO external provider is wired in, no company data leaves the server).

What exists now:
  * AIProvider protocol + UnavailableProvider (the only implementation): asking for a completion raises ProviderUnavailable, so every
    caller must handle degraded mode. Deterministic metrics/dashboards never depend on this module.
  * An allow-list of READ-ONLY tools generated from the metric registry. A tool can only call compute(); it has no write path.
  * redact_for_ai(): the only door through which metric data may ever reach a provider. Allow-listed result keys, sensitive fields
    dropped, names replaced by stable aliases, free text neutralised (database text is data, never instructions).
Provider selection (Stage 3) needs explicit approval of the provider and the data-sharing arrangement: see docs/INTELLIGENCE.md."""
import re
from typing import Protocol

from . import results as R
from .registry import REGISTRY, Ctx, compute

TOOL_PREFIX = "get_"


class ProviderUnavailable(Exception): pass


class AIProvider(Protocol):
    name: str
    def complete(self, system: str, messages: list, tools: list) -> dict: ...


class UnavailableProvider:
    name = "none"
    def complete(self, system, messages, tools): raise ProviderUnavailable("No AI provider has been approved or configured.")


def get_provider() -> AIProvider: return UnavailableProvider()      # Stage 3: select an approved provider here, behind explicit configuration


def status() -> dict:
    p = get_provider()
    return {"ai_available": not isinstance(p, UnavailableProvider), "provider": p.name, "degraded_mode": isinstance(p, UnavailableProvider),
            "message": "No AI provider is configured. All metrics, alerts and insights work without one." if isinstance(p, UnavailableProvider) else "",
            "data_shared_with_provider": False}


# ---------------- allow-listed read-only tools ----------------
PERIODS = ("last_7d", "last_30d", "wow", "mom")


def tool_catalog(role: str) -> list:
    """Tool specs the model may be offered. One tool per registered metric; the only argument is a period from a fixed enum."""
    from .registry import permitted
    out = []
    for d in sorted(REGISTRY.values(), key=lambda x: x.id):
        if permitted(d, role):
            out.append({"name": TOOL_PREFIX + d.id.replace(".", "__"), "metric_id": d.id, "description": d.description, "read_only": True,
                        "input_schema": {"type": "object", "properties": {"period": {"type": "string", "enum": list(PERIODS)}}, "additionalProperties": False}})
    return out


def run_tool(name: str, args: dict, ctx: Ctx) -> dict:
    """Execute one allow-listed tool. Unknown tool or argument -> ValueError. Authorisation is re-checked inside compute() with the
    SESSION's role (ctx.role), never with anything the model supplied."""
    spec = next((t for t in tool_catalog(ctx.role) if t["name"] == name), None)
    if spec is None: raise ValueError("Unknown or not permitted tool.")
    if set(args or {}) - {"period"}: raise ValueError("Unexpected argument.")
    if args.get("period") not in (None, *PERIODS): raise ValueError("Invalid period.")
    return redact_for_ai(compute(spec["metric_id"], ctx).to_dict())


# ---------------- redaction ----------------
RESULT_KEYS = ("metric_id", "label", "state", "value", "unit", "message", "breakdown", "detail", "period", "comparison", "as_of", "freshness", "limitations", "threshold", "reliability")
DROP_FIELDS = {"vehicle_ref", "registration_number", "device_identifier", "vin", "email", "phone", "address", "customer_email", "customer_address", "customer_tax_id", "latitude", "longitude", "token", "token_hint", "password", "secret"}
ALIAS_FIELDS = {"technician_name": "Technician", "technician_name_": "Technician", "customer_name": "Customer", "max_owner_name": "Technician", "name": "Person"}
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def clean_text(s: str, limit: int = 120) -> str:
    return _CTRL.sub(" ", s).strip()[:limit]


class _Aliaser:
    def __init__(self): self.m = {}
    def __call__(self, field, value):
        k = (ALIAS_FIELDS[field], value)
        if k not in self.m: self.m[k] = f"{ALIAS_FIELDS[field]} {sum(1 for x in self.m if x[0] == ALIAS_FIELDS[field]) + 1}"
        return self.m[k]


def _walk(v, alias, field=None):
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            if k in DROP_FIELDS or any(w in k.lower() for w in ("password", "token", "secret", "api_key")): continue
            out[k] = alias(k, x) if (k in ALIAS_FIELDS and isinstance(x, str)) else _walk(x, alias, k)
        return out
    if isinstance(v, list): return [_walk(x, alias, field) for x in v]
    if isinstance(v, str): return clean_text(v, 300)
    return v


def redact_for_ai(result: dict) -> dict:
    """Allow-list top-level keys, drop sensitive fields at any depth, alias personal names consistently within this response.
    Evidence record ids are omitted (opaque ids are not needed for reasoning); the source/method text is kept via the metric's own fields."""
    alias = _Aliaser()
    out = {k: _walk(result[k], alias, k) for k in RESULT_KEYS if k in result}
    out["evidence"] = [{"source": e["source"], "method": e["method"], "row_count": e["row_count"]} for e in result.get("evidence", [])]
    return out
