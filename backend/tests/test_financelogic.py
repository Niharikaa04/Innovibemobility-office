"""Pure-Python tests for money rules. Run `python tests/test_financelogic.py` or pytest."""
import os, sys
from datetime import date
from decimal import Decimal as D
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import financelogic as F

def bad(fn, *a, **k):
    try: fn(*a, **k)
    except F.FinanceError: return True
    return False

def test_floats_rejected(): assert bad(F.money, 0.1) and bad(F.line_totals, 1, 9.99)
def test_rounding_half_up(): assert F.money("2.675") == D("2.68") and F.money("0.005") == D("0.01")
def test_line_math():
    r = F.line_totals(3, "33.33", 10, 18)       # 99.99 gross, 10.00 disc, 89.99 net, 16.20 tax
    assert r == {"gross": D("99.99"), "discount": D("10.00"), "net": D("89.99"), "tax": D("16.20"), "total": D("106.19")}
def test_document_equals_sum_of_rounded_lines():
    d = F.document_totals([{"qty": 1, "unit_price": "0.335", "tax_pct": 10}] * 3)   # each line rounds first
    assert d["total"] == sum(l["total"] for l in d["lines"]) and d["subtotal"] == D("1.02")
def test_line_validation():
    assert bad(F.line_totals, 0, 1) and bad(F.line_totals, 1, -1) and bad(F.line_totals, 1, 1, 101) and bad(F.line_totals, 1, 1, 0, -1)
    assert bad(F.document_totals, []) and bad(F.money, "abc") and bad(F.money, "NaN") and bad(F.money, None)
def test_status_flow():
    due, today = date(2026, 11, 30), date(2026, 10, 26)
    assert F.invoice_status("100", [], due, today, issued=False) == "draft"
    assert F.invoice_status("100", [], due, today) == "issued"
    assert F.invoice_status("100", ["40"], due, today) == "partially_paid"
    assert F.invoice_status("100", ["40", "60"], due, today) == "paid"
    assert F.invoice_status("100", ["40"], date(2026, 10, 1), today) == "overdue"
    assert F.invoice_status("100", ["100"], date(2026, 10, 1), today) == "paid"      # paid beats overdue
    assert F.invoice_status("100", [], due, today, cancelled=True) == "cancelled"
def test_overpayment_rejected(): assert bad(F.outstanding, "100", ["60", "60"]) and bad(F.outstanding, "100", ["-5", "10"])
def test_allocation_oldest_first_and_remainder():
    inv = [{"id": "b", "outstanding": "50", "due": date(2026, 11, 1)}, {"id": "a", "outstanding": "70", "due": date(2026, 10, 1)}]
    r = F.allocate_payment("100", inv)
    assert r["allocations"] == [{"invoice_id": "a", "amount": D("70.00")}, {"invoice_id": "b", "amount": D("30.00")}] and r["unallocated"] == D("0.00")
    r = F.allocate_payment("500", inv); assert r["unallocated"] == D("380.00")      # never over-allocates
    assert bad(F.allocate_payment, "0", inv) and bad(F.allocate_payment, "-1", inv)
    assert bad(F.allocate_payment, "10", inv + [inv[0]])
def test_aging():
    t = date(2026, 10, 26); i = lambda o, d: {"outstanding": o, "due": d}
    a = F.aging([i("10", date(2026, 11, 5)), i("20", date(2026, 10, 20)), i("30", date(2026, 9, 1)), i("40", date(2026, 8, 1)), i("50", date(2026, 5, 1)), i("0", date(2026, 1, 1))], t)
    assert (a["current"], a["1-30"], a["31-60"], a["61-90"], a["90+"], a["total"]) == tuple(map(D, ("10.00", "20.00", "30.00", "40.00", "50.00", "150.00")))
def test_idempotency():
    s = set(); assert F.idempotent_once(s, "evt_1") and not F.idempotent_once(s, "evt_1") and F.idempotent_once(s, "evt_2") and bad(F.idempotent_once, s, "")

if __name__ == "__main__":
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"): v(); n += 1; print("PASS", k)
    print(n, "passed")
