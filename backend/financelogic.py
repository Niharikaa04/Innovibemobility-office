"""Pure-Python money rules for quotations, orders, invoices and payments. No third-party imports, no database.
The API must call these on the SERVER for every total; never trust totals sent by the browser.

Rules (documented so finance can review them):
 * All money is Decimal, rounded half-up to 2 places. Floats are rejected (binary rounding errors).
 * Per line: net = qty*unit_price - discount (discount_pct of that gross); tax = net * tax_pct. Each is rounded per line,
   then documents are the SUM of rounded lines, so printed lines always add up to the printed total.
 * Tax rates and currencies are INPUTS (configured in Settings). Nothing here assumes a tax rate.
 * An invoice is paid only from VERIFIED payment allocations passed in by the caller. A payment link is not a payment.
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

CENT = Decimal("0.01")
INVOICE_STATUSES = ("draft", "issued", "partially_paid", "paid", "overdue", "cancelled")

class FinanceError(ValueError):
    pass

def dec(v, name="value") -> Decimal:
    if isinstance(v, (float, bool)) or v is None:
        raise FinanceError(f"{name} must be a Decimal, int or numeric string, not {type(v).__name__}")
    try:
        d = Decimal(str(v).strip()) if not isinstance(v, Decimal) else v
    except InvalidOperation:
        raise FinanceError(f"{name} is not a valid number")
    if not d.is_finite():
        raise FinanceError(f"{name} must be finite")
    return d

def money(v, name="amount") -> Decimal:
    return dec(v, name).quantize(CENT, rounding=ROUND_HALF_UP)

def line_totals(qty, unit_price, discount_pct=0, tax_pct=0) -> dict:
    q, p, dp, tp = dec(qty, "qty"), dec(unit_price, "unit_price"), dec(discount_pct, "discount_pct"), dec(tax_pct, "tax_pct")
    if q <= 0: raise FinanceError("qty must be greater than zero")
    if p < 0: raise FinanceError("unit_price cannot be negative")
    if not (0 <= dp <= 100): raise FinanceError("discount_pct must be between 0 and 100")
    if not (0 <= tp <= 100): raise FinanceError("tax_pct must be between 0 and 100")
    gross = money(q * p)
    discount = money(gross * dp / 100)
    net = gross - discount
    tax = money(net * tp / 100)
    return {"gross": gross, "discount": discount, "net": net, "tax": tax, "total": net + tax}

def document_totals(lines) -> dict:
    """lines: iterable of dicts with qty, unit_price, optional discount_pct, tax_pct."""
    rows = [line_totals(l["qty"], l["unit_price"], l.get("discount_pct", 0), l.get("tax_pct", 0)) for l in lines]
    if not rows: raise FinanceError("a document needs at least one line")
    s = lambda k: sum((r[k] for r in rows), Decimal("0.00"))
    return {"lines": rows, "subtotal": s("gross"), "discount_total": s("discount"), "net_total": s("net"),
            "tax_total": s("tax"), "total": s("total")}

def outstanding(total, verified_allocations) -> Decimal:
    t = money(total, "total"); paid = sum((money(a, "allocation") for a in verified_allocations), Decimal("0.00"))
    if any(money(a) < 0 for a in verified_allocations): raise FinanceError("allocations cannot be negative")
    if paid > t: raise FinanceError("allocations exceed the invoice total")
    return t - paid

def invoice_status(total, verified_allocations, due: date, today: date, issued=True, cancelled=False) -> str:
    if cancelled: return "cancelled"
    if not issued: return "draft"
    t = money(total, "total"); left = outstanding(t, verified_allocations)
    if t > 0 and left == 0: return "paid"
    if t == 0: return "paid"
    paid_any = left < t
    if due < today: return "overdue"
    return "partially_paid" if paid_any else "issued"

def allocate_payment(amount, invoices) -> dict:
    """Allocate one verified payment across open invoices, oldest due date first (ties: input order).
    invoices: list of {"id", "outstanding", "due"}. Never over-allocates; leftover is returned as unallocated (credit)."""
    left = money(amount, "payment amount")
    if left <= 0: raise FinanceError("payment amount must be greater than zero")
    out, seen = [], set()
    for i, inv in sorted(enumerate(invoices), key=lambda x: (x[1]["due"], x[0])):
        if inv["id"] in seen: raise FinanceError("duplicate invoice id in allocation list")
        seen.add(inv["id"]); o = money(inv["outstanding"], "outstanding")
        if o < 0: raise FinanceError("outstanding cannot be negative")
        if left == 0 or o == 0: continue
        take = min(left, o); out.append({"invoice_id": inv["id"], "amount": take}); left -= take
    return {"allocations": out, "unallocated": left}

AGING = (("current", None, 0), ("1-30", 1, 30), ("31-60", 31, 60), ("61-90", 61, 90), ("90+", 91, None))

def aging(invoices, today: date) -> dict:
    """Bucket outstanding balances by days past due. invoices: [{"outstanding","due"}]. Not-yet-due -> current."""
    b = {k: Decimal("0.00") for k, _, _ in AGING}
    for inv in invoices:
        o = money(inv["outstanding"], "outstanding")
        if o <= 0: continue
        days = (today - inv["due"]).days
        key = "current" if days <= 0 else "1-30" if days <= 30 else "31-60" if days <= 60 else "61-90" if days <= 90 else "90+"
        b[key] += o
    b["total"] = sum(b.values(), Decimal("0.00")); return b

def idempotent_once(seen: set, event_id: str) -> bool:
    """True the first time an external event id (webhook, retry key) is seen; False on duplicates."""
    if not event_id: raise FinanceError("event id is required for idempotency")
    if event_id in seen: return False
    seen.add(event_id); return True
