"""Small helpers shared by garageapi / technicianapi / diagapi / iotapi (same conventions as fleetapi / ticketapi)."""
from fastapi import Depends, HTTPException
import permissions

DONE = ('COMPLETED', 'CUSTOMER_CONFIRMATION', 'CLOSED')   # ticket statuses that no longer count as open work


def trim(v): return v.strip() if isinstance(v, str) else v
def blank(v):
    v = trim(v)
    return (v or None) if isinstance(v, str) else v
def like(q: str) -> str: return '%' + q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def make_perm(session, csrf, audit, module):
    """perm('read') / perm('write', True) -> FastAPI dependency. Writes also require the CSRF token. Denials go to the security log."""
    def perm(action, write=False):
        def dep(s=Depends(csrf if write else session)):
            if not permissions.can(s['role'], f'{module}.{action}'):
                audit.write('permission_denied', s['id'], None, permission=f'{module}.{action}', role=s['role'])
                raise HTTPException(403, f'You do not have permission to {action} {module}.')
            return s
        return dep
    return perm