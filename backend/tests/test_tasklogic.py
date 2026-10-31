"""Pure-Python tests for task rules. Run with `python -m pytest tests/test_tasklogic.py` or `python tests/test_tasklogic.py`."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import tasklogic as T

def err(fn, *a):
    try: fn(*a)
    except T.RuleError as e: return e.status
    return None

def test_normal_flow():
    assert T.new_status("open", "in_progress", False, False) == "in_progress"
    assert T.new_status("in_progress", "done", False, False) == "done"
    assert T.new_status("open", "done", False, False) == "done"
    assert T.new_status("in_progress", "in_progress", False, False) == "in_progress"

def test_completion_of_approval_task_goes_to_pending():
    assert T.new_status("in_progress", "done", True, False) == "pending_approval"
    assert T.new_status("open", "done", True, True) == "pending_approval"      # even a manager cannot skip approval

def test_pending_cannot_be_set_or_left_by_edit():
    assert err(T.new_status, "open", "pending_approval", False, True) == 422
    for to in ("done", "open", "in_progress", "cancelled"): assert err(T.new_status, "pending_approval", to, True, True) == 409

def test_reopen_is_manager_only():
    assert err(T.new_status, "done", "open", False, False) == 403 and T.new_status("done", "open", False, True) == "open"
    assert err(T.new_status, "cancelled", "in_progress", False, False) == 403 and T.new_status("cancelled", "in_progress", False, True) == "in_progress"

def test_invalid_moves_and_unknown_status():
    assert err(T.new_status, "done", "cancelled", False, True) == 409 and err(T.new_status, "open", "bogus", False, True) == 422

def test_scope_and_edit_rights():
    assert T.can_see(True, "1", "1", "9") and T.can_see(True, "1", "5", "1") and not T.can_see(True, "1", "5", "9") and T.can_see(False, "1", "5", "9")
    assert T.can_change_status(True, "1", "1") and not T.can_change_status(True, "1", "2") and T.can_change_status(False, "1", "2")
    assert T.can_edit_content(True, "1", "1", "1") and not T.can_edit_content(True, "1", "1", "9") and not T.can_edit_content(True, "1", "2", "1")
    assert T.can_edit_content(False, "1", "2", "3") and not T.can_reassign(True) and T.can_reassign(False)

def test_decisions():
    assert T.check_decision("9", "1", "pending_approval", "approve", "") == "done"
    assert T.check_decision("9", "1", "pending_approval", "reject", "redo it") == "in_progress"
    assert err(T.check_decision, "9", "1", "pending_approval", "reject", "  ") == 422
    assert err(T.check_decision, "1", "1", "pending_approval", "approve", "") == 403          # no self-approval
    assert err(T.check_decision, "9", "1", "open", "approve", "") == 409
    assert err(T.check_decision, "9", "1", "pending_approval", "maybe", "") == 422

if __name__ == "__main__":
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"): v(); n += 1
    print(f"{n} passed")
