import pytest
import csvutil, fleetapi, permissions, ticketapi

def test_csv_cells_that_look_like_formulas_are_neutralised():
    for bad in ("=1+1", "+cmd", "-2", "@SUM(A1)", "\tx"): assert csvutil.safe_cell(bad).startswith("'")
    assert csvutil.safe_cell(None) == "" and csvutil.safe_cell("ok") == "ok" and csvutil.safe_cell(12) == "12"

def test_csv_response_has_bom_headers_and_quoting():
    r = csvutil.csv_response("x.csv", ["a", "b"], [['he said "hi", ok', "=2"]])
    assert r.body.decode("utf-8").startswith("\ufeffa,b") and '"he said ""hi"", ok",\'=2' in r.body.decode("utf-8")
    assert "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"

def test_ticket_models_validate_category_priority_and_trim():
    t = ticketapi.TicketIn(title=" x ", category="BATTERY", customer_name="  ", assigned_to=" ")
    assert t.title == "x" and t.customer_name is None and t.assigned_to is None
    for bad in ({"category": "NOPE"}, {"priority": "P0"}, {"title": "  "}):
        with pytest.raises(Exception): ticketapi.TicketIn(**{"title": "ok", **bad})
    assert ticketapi.TicketUpdate(priority="LOW").model_dump(exclude_unset=True) == {"priority": "LOW"}
    with pytest.raises(Exception): ticketapi.TicketUpdate(category="NOPE")

def test_like_escapes_wildcards():
    assert ticketapi.like("50%_\\") == "%50\\%\\_\\\\%" and fleetapi.like("a%") == "%a\\%%"

def test_vehicle_models_normalise_and_validate():
    v = fleetapi.VehicleIn(registration_number="  ka 01   ab-1234 ", make=" Tata ", model="Ace", battery_capacity_kwh=21.3)
    assert v.registration_number == "KA 01 AB-1234" and v.make == "Tata" and v.status == "ACTIVE"
    for bad in ({"registration_number": "A!"}, {"registration_number": "ab"}, {"vehicle_type": "BOAT"}, {"battery_capacity_kwh": 0}, {"battery_capacity_kwh": -1}, {"status": "X"}, {"manufacture_year": 1800}, {"odometer_km": -1}):
        with pytest.raises(Exception): fleetapi.VehicleIn(**{"registration_number": "KA01AB1234", "make": "a", "model": "b", **bad})
    assert fleetapi.VehicleUpdate(status="IDLE").model_dump(exclude_unset=True) == {"status": "IDLE"}
    with pytest.raises(Exception): fleetapi.ServiceIn(service_date="2999-01-01", service_type="x")

def test_rbac_for_fleet_and_ticket_actions():
    can = permissions.can
    assert can("service_manager", "fleet.write") and can("service_manager", "fleet.export") and not can("service_manager", "fleet.archive") and can("ceo", "fleet.archive")
    assert can("technician", "fleet.read") and not can("technician", "fleet.write") and not can("technician", "fleet.export")
    assert can("coo", "fleet.export") and not can("coo", "fleet.write") and not can("coo", "fleet.archive")
    assert not can("hr", "fleet.read") and not can("employee", "tickets.read")
    assert can("service_manager", "tickets.approve") and not can("technician", "tickets.approve") and not can("coo", "tickets.write")
