"""Location-policy and permission tests. PURE PYTHON: no database, no third-party packages for the first group.
Run with `python -m pytest backend/tests/test_ops2_units.py` OR `python backend/tests/test_ops2_units.py`.
The AI-reply parser tests at the bottom need FastAPI/pydantic installed (they import diagapi) and are skipped otherwise."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import locationpolicy as LP
import permissions as P


# ---------- who may see location data ----------
def test_location_grant_is_ceo_and_authorised_operations_roles_only():
    assert {r for r in P.ROLES if P.can(r, "location.read")} == {"ceo", "coo", "service_manager"}

def test_cto_hr_employee_technician_have_no_location_grant():
    for role in ("cto", "hr", "employee", "technician"): assert not P.can(role, "location.read"), role

def test_access_levels():
    assert LP.location_access("ceo", True) == "full" and LP.location_access("service_manager", True) == "full"
    assert LP.location_access("technician", False) == "assigned_only"
    for role in ("cto", "hr", "employee", "intern"): assert LP.location_access(role, False) == "none", role

def test_access_levels_match_the_real_matrix():
    got = {r: LP.location_access(r, P.can(r, "location.read")) for r in P.ROLES}
    assert got == {"ceo": "full", "coo": "full", "service_manager": "full", "cto": "none", "hr": "none", "technician": "assigned_only", "employee": "none"}

def test_only_technician_is_row_scoped_for_iot_and_has_read_but_no_write_or_export():
    assert P.is_own_only("technician", "iot") and not P.is_own_only("cto", "iot")
    assert P.can("technician", "iot.read") and not P.can("technician", "iot.write") and not P.can("technician", "iot.export") and not P.can("technician", "iot.archive")
    assert not P.can("hr", "iot.read") and not P.can("employee", "iot.read")

def test_vehicle_scope_applies_to_technicians_only():
    assert LP.vehicle_scope("ceo", "u1", "r.vehicle_id") is None and LP.vehicle_scope("cto", "u1", "r.vehicle_id") is None
    sql, params = LP.vehicle_scope("technician", "u1", "r.vehicle_id")
    assert sql.startswith("r.vehicle_id in (") and "k.assigned_to=%s" in sql and "k.status <> all(%s)" in sql      # open tickets only: access ends when work is completed
    assert params == ["u1", ["COMPLETED", "CUSTOMER_CONFIRMATION", "CLOSED"]] and sql.count("%s") == len(params)

# ---------- what counts as location data ----------
def test_location_metric_names():
    for m in ("latitude", "longitude", "lat", "lng", "lon", "altitude", "heading", "gps", "gps_fix", "gps_speed", "location", "location_accuracy", "geo_hash", "position_x", "Latitude", " longitude "):
        assert LP.is_location_metric(m), m
    for m in ("battery_voltage", "temperature", "state_of_charge", "vehicle_speed", "motor_temperature", "energy_consumption", "longevity", "latency", "geometry_ok"):
        assert not LP.is_location_metric(m), m

def test_extra_location_names_from_environment_are_honoured_and_sanitised():
    assert not LP.is_location_metric("pos_x") and LP.is_location_metric("pos_x", "pos_x, pos_y") and LP.is_location_metric("pos_y", "pos_x, pos_y")
    assert LP.location_pattern("bad name;drop,ok_name") == LP.location_pattern("ok_name")       # invalid entries are dropped, never interpolated

def test_pattern_is_anchored_so_substrings_do_not_match():
    assert not LP.is_location_metric("battery_latitude_offset") and not LP.is_location_metric("my_gps")


# ---------- technician contact details ----------
def test_technician_contact_details_roles():
    assert {r for r in P.ROLES if P.can(r, "technician_contact.read")} == {"ceo", "coo", "service_manager"}
    assert not P.can("cto", "technician_contact.read") and not P.can("hr", "technician_contact.read")


# ---------- AI reply parser (needs fastapi/pydantic installed) ----------
def _diag():
    try:
        import diagapi; return diagapi
    except ImportError: return None

def test_ai_parser_skips_incomplete_items_and_never_invents():
    d = _diag()
    if d is None: return
    faults, skipped = d.parse_ai_faults({"faults": [
        {"id": "a1", "code": "p0a80", "description": " Weak cell ", "severity": "severe", "detected_at": "2026-10-01T10:00:00Z"},
        {"code": "X", "severity": "bogus", "detected_at": "2026-10-02T10:00:00Z"},      # unknown severity
        {"code": "Y", "severity": "LOW"},                                               # no timestamp
        {"code": "Z", "severity": "LOW", "detected_at": "2999-01-01T00:00:00Z"},        # future
        "junk"]})
    assert [f["code"] for f in faults] == ["P0A80"] and faults[0]["severity"] == "CRITICAL" and skipped == 4 and faults[0]["external_ref"] == "a1"

def test_ai_parser_rejects_wrong_shape():
    d = _diag()
    if d is None: return
    try: d.parse_ai_faults({"oops": 1})
    except ValueError: return
    raise AssertionError("expected ValueError")


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns: f(); print("PASS", f.__name__)
    print(f"{len(fns)} passed" + ("" if _diag() else "  (AI parser tests skipped: fastapi/pydantic not installed)"))
