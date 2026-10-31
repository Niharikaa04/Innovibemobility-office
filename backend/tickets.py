"""Service ticket lifecycle (Blueprint s.24). Pure rules; no DB. Backend must call can_transition before any status write."""
ORDER = ["NEW","TRIAGED","DIAGNOSIS","ASSIGNED","ACCEPTED","IN_PROGRESS","PARTS_REQUIRED","WAITING","REPAIR","QUALITY_CHECK","COMPLETED","CUSTOMER_CONFIRMATION","CLOSED"]
MGR = {"service_manager","coo","ceo"}; TECH = {"technician","service_manager"}
# ASSUMPTIONS beyond the linear Blueprint chain (confirm): IN_PROGRESS->REPAIR when no parts needed; PARTS_REQUIRED/WAITING resume; failed QC returns to REPAIR.
T = {"NEW":{"TRIAGED":MGR},"TRIAGED":{"DIAGNOSIS":MGR|{"technician"}},"DIAGNOSIS":{"ASSIGNED":MGR},"ASSIGNED":{"ACCEPTED":TECH,"DIAGNOSIS":MGR},
 "ACCEPTED":{"IN_PROGRESS":TECH},"IN_PROGRESS":{"PARTS_REQUIRED":TECH,"REPAIR":TECH},"PARTS_REQUIRED":{"WAITING":TECH},"WAITING":{"REPAIR":TECH},
 "REPAIR":{"QUALITY_CHECK":TECH},"QUALITY_CHECK":{"COMPLETED":MGR,"REPAIR":MGR},"COMPLETED":{"CUSTOMER_CONFIRMATION":MGR},"CUSTOMER_CONFIRMATION":{"CLOSED":MGR},"CLOSED":{}}
def can_transition(frm: str, to: str, role: str) -> bool: return role in T.get(frm, {}).get(to, set())
def next_states(frm: str, role: str): return [t for t, r in T.get(frm, {}).items() if role in r]
