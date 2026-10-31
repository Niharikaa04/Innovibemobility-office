import pytest, tickets as T
def test_full_happy_path_with_roles():
    path = [("NEW","TRIAGED","service_manager"),("TRIAGED","DIAGNOSIS","service_manager"),("DIAGNOSIS","ASSIGNED","service_manager"),("ASSIGNED","ACCEPTED","technician"),
     ("ACCEPTED","IN_PROGRESS","technician"),("IN_PROGRESS","PARTS_REQUIRED","technician"),("PARTS_REQUIRED","WAITING","technician"),("WAITING","REPAIR","technician"),
     ("REPAIR","QUALITY_CHECK","technician"),("QUALITY_CHECK","COMPLETED","service_manager"),("COMPLETED","CUSTOMER_CONFIRMATION","service_manager"),("CUSTOMER_CONFIRMATION","CLOSED","service_manager")]
    for a, b, r in path: assert T.can_transition(a, b, r), (a, b, r)
def test_no_skipping_and_no_backwards_except_defined():
    assert not T.can_transition("NEW", "CLOSED", "ceo") and not T.can_transition("NEW", "ASSIGNED", "service_manager") and not T.can_transition("CLOSED", "NEW", "ceo")
def test_roles_enforced():
    assert not T.can_transition("NEW", "TRIAGED", "employee") and not T.can_transition("ASSIGNED", "ACCEPTED", "employee") and not T.can_transition("QUALITY_CHECK", "COMPLETED", "technician")
def test_unknown_states_denied(): assert not T.can_transition("BOGUS", "NEW", "ceo") and T.next_states("CLOSED", "ceo") == []
def test_every_blueprint_state_is_defined(): assert set(T.T) == set(T.ORDER)
