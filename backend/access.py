"""Backend enforcement of the RBAC matrix in permissions.py. The UI hiding a button is never the control; this is.
`need("tasks.write")` returns a FastAPI dependency: it requires a valid session (and CSRF for writes) and then checks the matrix.
Deny by default. Denials are written to the security log."""
from fastapi import Depends, HTTPException
import permissions

def make_need(session, csrf, audit):
    def need(perm: str, write: bool = False):
        module, action = perm.split(".")
        assert action in permissions.ACTIONS, perm
        def dep(s=Depends(csrf if write else session)):
            if not permissions.can(s["role"], perm):
                audit.write("permission_denied", s["id"], None, permission=perm, role=s["role"])
                raise HTTPException(403, "You do not have permission to do this.")
            s = dict(s); s["own_only"] = permissions.is_own_only(s["role"], module); return s
        return dep
    return need
