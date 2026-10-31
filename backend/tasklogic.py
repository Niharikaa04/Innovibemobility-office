"""Task & approval business rules. PURE PYTHON (no FastAPI/DB imports) so they can be tested anywhere.
The API layer calls these before every write; the database CHECK constraints are a second line of defence.
ASSUMPTIONS (proposed, not confirmed company policy): see docs/MODULES.md "Tasks & Approvals".
"""
STATUSES = ("open", "in_progress", "pending_approval", "done", "cancelled")
PRIORITIES = ("low", "normal", "high")
STATUS_LABELS = {"open": "Open", "in_progress": "In progress", "pending_approval": "Pending approval", "done": "Done", "cancelled": "Cancelled"}
# Statuses a user may REQUEST through a normal edit. 'pending_approval' is only ever set by the server; approve/reject is its own action.
REQUESTABLE = ("open", "in_progress", "done", "cancelled")
# Normal moves for the assignee. Reopening finished/cancelled work is a manager action (see MANAGER_ONLY).
FLOW = {"open": {"in_progress", "done", "cancelled"}, "in_progress": {"open", "done", "cancelled"}}
MANAGER_ONLY = {("done", "open"), ("done", "in_progress"), ("cancelled", "open"), ("cancelled", "in_progress")}

class RuleError(Exception):
    def __init__(self, status: int, message: str): super().__init__(message); self.status, self.message = status, message

def new_status(current: str, requested: str, requires_approval: bool, is_manager: bool) -> str:
    """Status the task will actually get when `requested` is asked for. Raises RuleError if not allowed."""
    if requested not in STATUSES: raise RuleError(422, "Unknown status.")
    if requested == current: return current
    if current == "pending_approval": raise RuleError(409, "This task is waiting for approval. Use approve or reject.")
    if requested == "pending_approval": raise RuleError(422, "Pending approval is set automatically when you complete a task that needs approval.")
    ok = requested in FLOW.get(current, set()) or ((current, requested) in MANAGER_ONLY and is_manager)
    if not ok:
        raise RuleError(403 if (current, requested) in MANAGER_ONLY else 409, f"A task cannot move from {current} to {requested}." if (current, requested) not in MANAGER_ONLY else "Only a manager can reopen a finished or cancelled task.")
    return "pending_approval" if (requested == "done" and requires_approval) else requested

def can_see(own_only: bool, me: str, assignee_id: str, created_by: str) -> bool:
    return (not own_only) or me in (assignee_id, created_by)

def can_change_status(own_only: bool, me: str, assignee_id: str) -> bool:
    """Assignee, or anyone whose role is not own-only (managers)."""
    return (not own_only) or me == assignee_id

def can_edit_content(own_only: bool, me: str, assignee_id: str, created_by: str) -> bool:
    """Title/description/priority/due date/approval flag. Own-only roles: only tasks they made for themselves."""
    return (not own_only) or (me == created_by and me == assignee_id)

def can_reassign(own_only: bool) -> bool: return not own_only

def check_decision(me: str, assignee_id: str, status: str, decision: str, note: str) -> str:
    """Returns the resulting status for an approve/reject, or raises RuleError."""
    if status != "pending_approval": raise RuleError(409, "This task is not waiting for approval.")
    if me == assignee_id: raise RuleError(403, "You cannot approve your own task.")
    if decision == "approve": return "done"
    if decision == "reject":
        if not (note or "").strip(): raise RuleError(422, "A reason is required when rejecting.")
        return "in_progress"
    raise RuleError(422, "Decision must be approve or reject.")
