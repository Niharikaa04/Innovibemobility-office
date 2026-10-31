"""InnoVibe Business Intelligence foundation (Stage 1: deterministic, read-only, no external AI provider).

Layers (each depends only on the ones above it):
  results    - result states, Evidence, MetricResult (pure)
  periods    - reporting periods and comparison windows (pure)
  analytics  - statistics helpers: ageing, workload distribution, robust anomaly detection (pure)
  reader     - the ONLY place that talks to the database: read-only transaction, statement timeout, row limits
  registry   - authoritative metric registry: every number in the product is computed by exactly one registered function
  metrics    - the metric implementations (SQL aggregates + deterministic calculations)
  context    - company context engine: which modules/tables/metrics/history/thresholds actually exist
  alerts     - deterministic alerts, ranked issues, insights built ONLY from registry results
  ai_interface - provider-independent interface, allow-listed read-only tools, redaction (no provider is wired in)
  api        - FastAPI router (/api/intelligence/*)
"""
