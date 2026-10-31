"""Finance API (db/016): invoices, payments & receivables, expenses, budgets & forecast. All amounts are in a single currency (INR).
Permissions (see permissions.py): invoices.*, payments.*, expenses.* (incl. approve), budget.*. Every change is written to the business audit log.
Payment status of an invoice is derived from its non-voided payments; it is never stored. Nothing here invents numbers: empty tables give zeros / empty lists."""
import io
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from xml.sax.saxutils import escape
import psycopg
from psycopg.rows import dict_row
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator
import auditdb, csvutil, permissions

CATEGORIES = ('SALARIES', 'RENT', 'UTILITIES', 'TRAVEL', 'EQUIPMENT', 'MARKETING', 'SOFTWARE', 'MAINTENANCE', 'PARTS_AND_INVENTORY', 'PROFESSIONAL_FEES', 'TAXES', 'OTHER')
METHODS = ('BANK_TRANSFER', 'UPI', 'CARD', 'CASH', 'CHEQUE', 'OTHER')
PAY_STATUSES = ('DRAFT', 'UNPAID', 'PARTIAL', 'PAID', 'OVERDUE', 'CANCELLED')
EXP_STATUSES = ('PENDING', 'APPROVED', 'REJECTED')
MIN_FORECAST_MONTHS = 3     # forecast is shown only with at least this many months that actually had invoices or approved expenses
FORECAST_AHEAD = 3
FORECAST_WINDOW = 6
Q2 = Decimal('0.01')

def _trim(v): return v.strip() if isinstance(v, str) else v
def _blank(v):
    v = _trim(v)
    return (v or None) if isinstance(v, str) else v
def like(q: str) -> str: return '%' + q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
def money(v) -> Decimal: return Decimal(str(v)).quantize(Q2, rounding=ROUND_HALF_UP)
def f(v) -> float: return float(v or 0)
def month_start(d: date) -> date: return d.replace(day=1)
def add_months(d: date, n: int) -> date:
    m = d.year * 12 + d.month - 1 + n
    return date(m // 12, m % 12 + 1, 1)

# ---------- request models ----------
class ItemIn(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    unit_price: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    @field_validator('description', mode='before')
    @classmethod
    def trim(cls, v): return _trim(v)

class InvoiceBase(BaseModel):
    @field_validator('customer_name', 'customer_address', 'notes', check_fields=False, mode='before')
    @classmethod
    def trim(cls, v): return _trim(v)
    @field_validator('customer_email', 'customer_tax_id', 'contact_id', check_fields=False, mode='before')
    @classmethod
    def blank(cls, v): return _blank(v)
    @field_validator('customer_email', check_fields=False)
    @classmethod
    def email_ok(cls, v):
        if v is not None and ('@' not in v or ' ' in v or v.startswith('@') or v.endswith('@')): raise ValueError('Enter a valid email address.')
        return v

class InvoiceIn(InvoiceBase):
    contact_id: str | None = None
    customer_name: str = Field(default='', max_length=180)
    customer_email: str | None = Field(default=None, max_length=254)
    customer_address: str = Field(default='', max_length=500)
    customer_tax_id: str | None = Field(default=None, max_length=40)
    issue_date: date
    due_date: date
    tax_percent: Decimal = Field(default=Decimal(0), ge=0, le=100, max_digits=5, decimal_places=2)
    notes: str = Field(default='', max_length=3000)
    items: list[ItemIn] = Field(min_length=1, max_length=50)
    send: bool = False

class InvoiceUpdate(InvoiceBase):
    contact_id: str | None = None
    customer_name: str | None = Field(default=None, max_length=180)
    customer_email: str | None = Field(default=None, max_length=254)
    customer_address: str | None = Field(default=None, max_length=500)
    customer_tax_id: str | None = Field(default=None, max_length=40)
    issue_date: date | None = None
    due_date: date | None = None
    tax_percent: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    notes: str | None = Field(default=None, max_length=3000)
    items: list[ItemIn] | None = Field(default=None, min_length=1, max_length=50)

class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    @field_validator('reason', mode='before')
    @classmethod
    def trim(cls, v): return _trim(v)

class PaymentIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    paid_on: date
    method: str = 'BANK_TRANSFER'
    reference: str | None = Field(default=None, max_length=120)
    notes: str = Field(default='', max_length=1000)
    @field_validator('reference', mode='before')
    @classmethod
    def blank(cls, v): return _blank(v)
    @field_validator('notes', mode='before')
    @classmethod
    def trim(cls, v): return _trim(v)
    @field_validator('method')
    @classmethod
    def method_ok(cls, v):
        if v not in METHODS: raise ValueError('Invalid payment method.')
        return v
    @field_validator('paid_on')
    @classmethod
    def not_future(cls, v):
        if v > date.today(): raise ValueError('Payment date cannot be in the future.')
        return v

class ExpenseBase(BaseModel):
    @field_validator('vendor', 'description', check_fields=False, mode='before')
    @classmethod
    def trim(cls, v): return _trim(v)
    @field_validator('receipt_number', 'receipt_url', check_fields=False, mode='before')
    @classmethod
    def blank(cls, v): return _blank(v)
    @field_validator('receipt_url', check_fields=False)
    @classmethod
    def url_ok(cls, v):
        if v is not None and not (v.lower().startswith('http://') or v.lower().startswith('https://')): raise ValueError('Receipt link must start with http:// or https://')
        return v
    @field_validator('category', check_fields=False)
    @classmethod
    def cat_ok(cls, v):
        if v is not None and v not in CATEGORIES: raise ValueError('Invalid expense category.')
        return v
    @field_validator('expense_date', check_fields=False)
    @classmethod
    def not_future(cls, v):
        if v is not None and v > date.today(): raise ValueError('Expense date cannot be in the future.')
        return v

class ExpenseIn(ExpenseBase):
    expense_date: date
    category: str
    vendor: str = Field(min_length=1, max_length=180)
    description: str = Field(default='', max_length=2000)
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    receipt_number: str | None = Field(default=None, max_length=80)
    receipt_url: str | None = Field(default=None, max_length=500)

class ExpenseUpdate(ExpenseBase):
    expense_date: date | None = None
    category: str | None = None
    vendor: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=2000)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    receipt_number: str | None = Field(default=None, max_length=80)
    receipt_url: str | None = Field(default=None, max_length=500)

class ReviewIn(BaseModel):
    note: str = Field(default='', max_length=500)
    @field_validator('note', mode='before')
    @classmethod
    def trim(cls, v): return _trim(v) or ''

class BudgetIn(BaseModel):
    kind: str
    category: str = 'REVENUE'
    month: str = Field(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')
    amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    notes: str = Field(default='', max_length=500)
    @field_validator('notes', mode='before')
    @classmethod
    def trim(cls, v): return _trim(v) or ''
    @field_validator('kind')
    @classmethod
    def kind_ok(cls, v):
        if v not in ('REVENUE', 'EXPENSE'): raise ValueError('Budget kind must be REVENUE or EXPENSE.')
        return v

INV_FIELDS = ('customer_name', 'customer_email', 'customer_address', 'customer_tax_id', 'issue_date', 'due_date', 'tax_percent', 'notes')

def totals(items, tax_percent):
    sub = sum((money(i.quantity * i.unit_price) for i in items), Decimal(0))
    tax = money(sub * Decimal(tax_percent) / 100)
    return sub, tax, sub + tax

def jd(v):
    """Make audit before/after payloads JSON-safe (Decimal, date, UUID)."""
    if isinstance(v, dict): return {k: jd(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [jd(x) for x in v]
    if isinstance(v, Decimal): return float(v)
    if isinstance(v, date) or hasattr(v, 'hex'): return v.isoformat() if isinstance(v, date) else str(v)
    return v

def rec(c, **k):
    for key in ('before', 'after'):
        if k.get(key) is not None: k[key] = jd(k[key])
    return auditdb.record(c, **k)

def build_router(dsn, session, csrf, audit):
    r = APIRouter(prefix='/api/finance')
    def db(): return psycopg.connect(dsn(), row_factory=dict_row, connect_timeout=10, prepare_threshold=None)
    def perm(module, action, write=False):
        def dep(s=Depends(csrf if write else session)):
            if not permissions.can(s['role'], f'{module}.{action}'):
                audit.write('permission_denied', s['id'], None, permission=f'{module}.{action}', role=s['role'])
                raise HTTPException(403, f'You do not have permission to {action} {module}.')
            return s
        return dep
    def flags(role, module, actions): return {f'can_{a}': permissions.can(role, f'{module}.{a}') for a in actions}
    def rng(date_from, date_to):
        if date_from and date_to and date_from > date_to: raise HTTPException(422, 'The From date must not be after the To date.')

    # ---------- invoice query (payment status derived) ----------
    def inv_base(today):
        return ("(select i.*, coalesce(p.paid,0) as paid_amount, i.total_amount-coalesce(p.paid,0) as balance, "
                "case when i.status='CANCELLED' then 'CANCELLED' when i.status='DRAFT' then 'DRAFT' when i.total_amount-coalesce(p.paid,0)<=0 then 'PAID' "
                "when i.due_date<%s then 'OVERDUE' when coalesce(p.paid,0)>0 then 'PARTIAL' else 'UNPAID' end as payment_status "
                "from office_dashboard.invoices i left join (select invoice_id, sum(amount) paid from office_dashboard.invoice_payments where not voided group by invoice_id) p on p.invoice_id=i.id) x", [today])
    def inv_where(q='', payment_status='', date_from=None, date_to=None, outstanding=False):
        w = ['not x.archived']; a = []
        if q.strip(): w.append('(x.invoice_number ilike %s or x.customer_name ilike %s or coalesce(x.customer_email,\'\') ilike %s)'); a += [like(q)] * 3
        if payment_status.strip():
            if payment_status not in PAY_STATUSES: raise HTTPException(422, 'Unknown payment status.')
            w.append('x.payment_status=%s'); a.append(payment_status)
        if outstanding: w.append("x.status='SENT' and x.balance>0")
        if date_from: w.append('x.issue_date>=%s'); a.append(date_from)
        if date_to: w.append('x.issue_date<=%s'); a.append(date_to)
        return ' and '.join(w), a
    def get_invoice(c, iid, lock=False):
        try:
            row = c.execute('select * from office_dashboard.invoices where id=%s and not archived' + (' for update' if lock else ''), (iid,)).fetchone()
        except psycopg.errors.InvalidTextRepresentation: row = None
        if not row: raise HTTPException(404, 'Invoice not found.')
        return row
    def paid_of(c, iid): return c.execute('select coalesce(sum(amount),0) p from office_dashboard.invoice_payments where invoice_id=%s and not voided', (iid,)).fetchone()['p']
    def full_invoice(c, iid):
        b, ba = inv_base(date.today())
        inv = c.execute(f'select x.* from {b} where x.id=%s', [*ba, iid]).fetchone()
        items = c.execute('select description,quantity,unit_price,round(quantity*unit_price,2) as line_total from office_dashboard.invoice_items where invoice_id=%s order by position,id', (iid,)).fetchall()
        pays = c.execute('select * from office_dashboard.invoice_payments where invoice_id=%s order by paid_on desc, created_at desc', (iid,)).fetchall()
        return inv, items, pays
    def resolve_contact(c, contact_id):
        try: row = c.execute('select id,full_name,email,organization from office_dashboard.contacts where id=%s and not is_archived', (contact_id,)).fetchone()
        except psycopg.errors.InvalidTextRepresentation: row = None
        if not row: raise HTTPException(422, 'The selected customer was not found.')
        return row
    def write_items(c, iid, items):
        c.execute('delete from office_dashboard.invoice_items where invoice_id=%s', (iid,))
        for n, i in enumerate(items):
            c.execute('insert into office_dashboard.invoice_items(invoice_id,position,description,quantity,unit_price) values(%s,%s,%s,%s,%s)', (iid, n, i.description, i.quantity, i.unit_price))

    # ================= INVOICES =================
    @r.get('/customers')
    def customers(q: str = '', s=Depends(perm('invoices', 'read'))):
        w, a = 'not is_archived', []
        if q.strip(): w += " and (full_name ilike %s or coalesce(organization,'') ilike %s or coalesce(email,'') ilike %s)"; a += [like(q)] * 3
        with db() as c:
            return c.execute(f'select id,full_name,email,organization from office_dashboard.contacts where {w} order by full_name limit 10', a).fetchall()

    @r.get('/invoices/summary')
    def invoice_summary(date_from: date | None = None, date_to: date | None = None, s=Depends(perm('invoices', 'read'))):
        rng(date_from, date_to); b, ba = inv_base(date.today()); w, a = inv_where('', '', date_from, date_to)
        with db() as c:
            rows = c.execute(f'select x.payment_status ps, count(*)::int n, coalesce(sum(x.total_amount),0) total, coalesce(sum(x.paid_amount),0) paid, coalesce(sum(x.balance),0) bal from {b} where {w} group by 1', [*ba, *a]).fetchall()
        by = {x['ps']: {'count': x['n'], 'total': f(x['total'])} for x in rows}
        live = [x for x in rows if x['ps'] in ('UNPAID', 'PARTIAL', 'PAID', 'OVERDUE')]
        return {'by_status': by, 'invoiced': sum(f(x['total']) for x in live), 'received': sum(f(x['paid']) for x in live), 'outstanding': sum(f(x['bal']) for x in live),
                'count': sum(x['n'] for x in rows)}

    @r.get('/invoices/export')
    def invoice_export(q: str = '', payment_status: str = '', date_from: date | None = None, date_to: date | None = None, s=Depends(perm('invoices', 'export'))):
        rng(date_from, date_to); b, ba = inv_base(date.today()); w, a = inv_where(q, payment_status, date_from, date_to)
        with db() as c:
            rows = c.execute(f'select x.* from {b} where {w} order by x.issue_date desc, x.invoice_number desc limit 10000', [*ba, *a]).fetchall()
            rec(c, actor_id=s['id'], actor_role=s['role'], action='export', entity_type='invoice', after={'rows': len(rows)})
        head = ['Invoice', 'Customer', 'Email', 'Issue date', 'Due date', 'Subtotal', 'Tax %', 'Tax', 'Total', 'Paid', 'Balance', 'Payment status', 'Notes']
        return csvutil.csv_response('invoices.csv', head, [[x['invoice_number'], x['customer_name'], x['customer_email'], x['issue_date'], x['due_date'], x['subtotal'], x['tax_percent'], x['tax_amount'], x['total_amount'], x['paid_amount'], x['balance'], x['payment_status'], x['notes']] for x in rows])

    @r.get('/invoices')
    def list_invoices(q: str = '', payment_status: str = '', date_from: date | None = None, date_to: date | None = None, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100), s=Depends(perm('invoices', 'read'))):
        rng(date_from, date_to); b, ba = inv_base(date.today()); w, a = inv_where(q, payment_status, date_from, date_to)
        with db() as c:
            total = c.execute(f'select count(*)::int n from {b} where {w}', [*ba, *a]).fetchone()['n']
            rows = c.execute(f'select x.* from {b} where {w} order by x.issue_date desc, x.invoice_number desc limit %s offset %s', [*ba, *a, limit, (page - 1) * limit]).fetchall()
        return {'items': rows, 'total': total, 'page': page, 'limit': limit, 'statuses': PAY_STATUSES, **flags(s['role'], 'invoices', ('write', 'export', 'archive')), 'can_pay': permissions.can(s['role'], 'payments.write')}

    @r.post('/invoices', status_code=201)
    def create_invoice(b: InvoiceIn, s=Depends(perm('invoices', 'write', True))):
        if b.due_date < b.issue_date: raise HTTPException(422, 'Due date cannot be before the issue date.')
        sub, tax, tot = totals(b.items, b.tax_percent)
        if tot <= 0: raise HTTPException(422, 'Invoice total must be greater than zero.')
        with db() as c:
            name, email = b.customer_name, b.customer_email
            if b.contact_id:
                ct = resolve_contact(c, b.contact_id); name = name or ct['full_name']; email = email or ct['email']
            if not name: raise HTTPException(422, 'Customer name is required.')
            row = c.execute('insert into office_dashboard.invoices(contact_id,customer_name,customer_email,customer_address,customer_tax_id,issue_date,due_date,tax_percent,subtotal,tax_amount,total_amount,status,notes,created_by) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *',
                            (b.contact_id, name, email, b.customer_address, b.customer_tax_id, b.issue_date, b.due_date, b.tax_percent, sub, tax, tot, 'SENT' if b.send else 'DRAFT', b.notes, s['id'])).fetchone()
            write_items(c, row['id'], b.items)
            rec(c, actor_id=s['id'], actor_role=s['role'], action='create', entity_type='invoice', entity_id=row['id'], after={'invoice_number': row['invoice_number'], 'customer_name': name, 'total_amount': tot, 'status': row['status']})
        audit.write('invoice_created', s['id'], None, invoice_id=str(row['id']))
        return row

    @r.get('/invoices/{iid}')
    def invoice_detail(iid: str, s=Depends(perm('invoices', 'read'))):
        with db() as c:
            get_invoice(c, iid); inv, items, pays = full_invoice(c, iid)
        return {'invoice': inv, 'items': items, 'payments': pays, 'methods': METHODS, **flags(s['role'], 'invoices', ('write', 'export', 'archive')), 'can_pay': permissions.can(s['role'], 'payments.write')}

    @r.patch('/invoices/{iid}')
    def edit_invoice(iid: str, b: InvoiceUpdate, s=Depends(perm('invoices', 'write', True))):
        ch = b.model_dump(exclude_unset=True)
        if not ch: raise HTTPException(422, 'Nothing to update.')
        with db() as c:
            old = get_invoice(c, iid, lock=True)
            if old['status'] == 'CANCELLED': raise HTTPException(409, 'A cancelled invoice cannot be edited.')
            has_pay = f(paid_of(c, iid)) > 0
            money_change = any(k in ch for k in ('items', 'tax_percent', 'issue_date'))
            if has_pay and money_change: raise HTTPException(409, 'This invoice has payments. Only the customer details, due date and notes can be changed. Void the payments first to change amounts.')
            if ch.get('customer_name', 'x') is None or ch.get('customer_name', 'x') == '': raise HTTPException(422, 'Customer name cannot be empty.')
            upd = {k: ch[k] for k in INV_FIELDS if k in ch and (k != 'notes' or ch[k] is not None) and (k != 'customer_address' or ch[k] is not None)}
            if 'contact_id' in ch:
                if ch['contact_id']: resolve_contact(c, ch['contact_id'])
                upd['contact_id'] = ch['contact_id']
            if 'tax_percent' in ch and ch['tax_percent'] is None: raise HTTPException(422, 'Tax percent cannot be empty.')
            if 'issue_date' in ch and ch['issue_date'] is None or 'due_date' in ch and ch['due_date'] is None: raise HTTPException(422, 'Dates cannot be empty.')
            issue, due = upd.get('issue_date', old['issue_date']), upd.get('due_date', old['due_date'])
            if due < issue: raise HTTPException(422, 'Due date cannot be before the issue date.')
            if 'items' in ch or 'tax_percent' in ch:
                if 'items' in ch: items = b.items
                else:
                    items = [ItemIn(description=i['description'], quantity=i['quantity'], unit_price=i['unit_price']) for i in c.execute('select description,quantity,unit_price from office_dashboard.invoice_items where invoice_id=%s order by position,id', (iid,)).fetchall()]
                sub, tax, tot = totals(items, upd.get('tax_percent', old['tax_percent']))
                if tot <= 0: raise HTTPException(422, 'Invoice total must be greater than zero.')
                upd.update(subtotal=sub, tax_amount=tax, total_amount=tot)
                if 'items' in ch: write_items(c, iid, items)
            diff = {k: v for k, v in upd.items() if old[k] != v and not (isinstance(v, Decimal) and old[k] is not None and Decimal(str(old[k])) == v)}
            if not diff and 'items' not in ch: return old
            row = c.execute('update office_dashboard.invoices set ' + ','.join(f'{k}=%s' for k in diff) + (',' if diff else '') + 'updated_at=now() where id=%s returning *', [*diff.values(), iid]).fetchone()
            rec(c, actor_id=s['id'], actor_role=s['role'], action='update', entity_type='invoice', entity_id=iid, before={k: old[k] for k in diff}, after={**diff, **({'items_changed': True} if 'items' in ch else {})})
        audit.write('invoice_updated', s['id'], None, invoice_id=iid, fields=sorted(diff))
        return row

    @r.post('/invoices/{iid}/send')
    def send_invoice(iid: str, s=Depends(perm('invoices', 'write', True))):
        with db() as c:
            old = get_invoice(c, iid, lock=True)
            if old['status'] != 'DRAFT': raise HTTPException(409, 'Only a draft invoice can be marked as sent.')
            row = c.execute("update office_dashboard.invoices set status='SENT',updated_at=now() where id=%s returning *", (iid,)).fetchone()
            rec(c, actor_id=s['id'], actor_role=s['role'], action='status_change', entity_type='invoice', entity_id=iid, before={'status': 'DRAFT'}, after={'status': 'SENT'})
        audit.write('invoice_sent', s['id'], None, invoice_id=iid)
        return row

    @r.post('/invoices/{iid}/cancel')
    def cancel_invoice(iid: str, b: ReasonIn, s=Depends(perm('invoices', 'write', True))):
        with db() as c:
            old = get_invoice(c, iid, lock=True)
            if old['status'] == 'CANCELLED': raise HTTPException(409, 'This invoice is already cancelled.')
            if f(paid_of(c, iid)) > 0: raise HTTPException(409, 'This invoice has payments. Void them before cancelling the invoice.')
            row = c.execute("update office_dashboard.invoices set status='CANCELLED',cancelled_reason=%s,updated_at=now() where id=%s returning *", (b.reason, iid)).fetchone()
            rec(c, actor_id=s['id'], actor_role=s['role'], action='status_change', entity_type='invoice', entity_id=iid, before={'status': old['status']}, after={'status': 'CANCELLED', 'reason': b.reason})
        audit.write('invoice_cancelled', s['id'], None, invoice_id=iid)
        return row

    @r.delete('/invoices/{iid}')
    def archive_invoice(iid: str, s=Depends(perm('invoices', 'archive', True))):
        with db() as c:
            old = get_invoice(c, iid, lock=True)
            if old['status'] == 'SENT': raise HTTPException(409, 'A sent invoice cannot be archived. Cancel it first.')
            c.execute('update office_dashboard.invoices set archived=true,updated_at=now() where id=%s', (iid,))
            rec(c, actor_id=s['id'], actor_role=s['role'], action='archive', entity_type='invoice', entity_id=iid, before={'invoice_number': old['invoice_number']})
        audit.write('invoice_archived', s['id'], None, invoice_id=iid)
        return {'ok': True, 'archived': iid}

    @r.get('/invoices/{iid}/pdf')
    def invoice_pdf(iid: str, s=Depends(perm('invoices', 'read'))):
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        except ImportError: raise HTTPException(503, 'PDF generation is not available: install the "reportlab" package on the server (pip install reportlab).')
        with db() as c:
            get_invoice(c, iid); inv, items, pays = full_invoice(c, iid)
            rec(c, actor_id=s['id'], actor_role=s['role'], action='export', entity_type='invoice', entity_id=iid, after={'format': 'pdf', 'invoice_number': inv['invoice_number']})
        st = getSampleStyleSheet(); navy = colors.HexColor('#0f2342'); P = lambda t, s_='BodyText': Paragraph(escape(str(t)).replace('\n', '<br/>'), st[s_])
        inr = lambda v: 'INR {:,.2f}'.format(float(v or 0))
        buf = io.BytesIO(); doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm, title=f"Invoice {inv['invoice_number']}")
        els = [Paragraph(f'<font color="#0f2342"><b>INVOICE {escape(inv["invoice_number"])}</b></font>', st['Title']), P('InnoVibe Mobility'), Spacer(1, 6 * mm)]
        meta = [[P('Bill to', 'Heading4'), P('Details', 'Heading4')],
                [P('\n'.join(x for x in (inv['customer_name'], inv['customer_address'], inv['customer_email'], ('Tax ID: ' + inv['customer_tax_id']) if inv['customer_tax_id'] else '') if x)),
                 P(f"Issue date: {inv['issue_date']:%d %b %Y}\nDue date: {inv['due_date']:%d %b %Y}\nStatus: {inv['payment_status'].title()}")]]
        t = Table(meta, colWidths=[90 * mm, 76 * mm]); t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')])); els += [t, Spacer(1, 6 * mm)]
        rows = [['Description', 'Qty', 'Unit price', 'Amount']] + [[P(i['description']), f"{float(i['quantity']):g}", inr(i['unit_price']), inr(i['line_total'])] for i in items]
        rows += [['', '', 'Subtotal', inr(inv['subtotal'])], ['', '', f"Tax ({float(inv['tax_percent']):g}%)", inr(inv['tax_amount'])], ['', '', 'Total', inr(inv['total_amount'])], ['', '', 'Paid', inr(inv['paid_amount'])], ['', '', 'Balance due', inr(inv['balance'])]]
        it = Table(rows, colWidths=[80 * mm, 20 * mm, 32 * mm, 34 * mm], repeatRows=1)
        it.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), navy), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white), ('ALIGN', (1, 0), (-1, -1), 'RIGHT'), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                ('LINEBELOW', (0, 0), (-1, len(items)), 0.25, colors.HexColor('#cbd5e1')), ('FONTNAME', (2, -3), (-1, -1), 'Helvetica-Bold'), ('LINEABOVE', (2, len(items) + 1), (-1, len(items) + 1), 0.5, navy)]))
        els.append(it)
        live = [p for p in pays if not p['voided']]
        if live:
            els += [Spacer(1, 6 * mm), P('Payments received', 'Heading4'), Table([['Date', 'Method', 'Reference', 'Amount']] + [[f"{p['paid_on']:%d %b %Y}", p['method'].replace('_', ' ').title(), p['reference'] or '', inr(p['amount'])] for p in live], colWidths=[34 * mm, 40 * mm, 58 * mm, 34 * mm], style=TableStyle([('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#cbd5e1')), ('ALIGN', (3, 0), (3, -1), 'RIGHT')]))]
        if inv['notes']: els += [Spacer(1, 6 * mm), P('Notes', 'Heading4'), P(inv['notes'])]
        doc.build(els)
        return Response(content=buf.getvalue(), media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename="{inv["invoice_number"]}.pdf"', 'Cache-Control': 'no-store'})

    # ================= PAYMENTS & RECEIVABLES =================
    @r.post('/invoices/{iid}/payments', status_code=201)
    def add_payment(iid: str, b: PaymentIn, s=Depends(perm('payments', 'write', True))):
        with db() as c:
            inv = get_invoice(c, iid, lock=True)
            if inv['status'] != 'SENT': raise HTTPException(409, 'Payments can only be recorded against a sent invoice.')
            bal = money(inv['total_amount']) - money(paid_of(c, iid))
            if b.amount > bal: raise HTTPException(422, f'Amount exceeds the outstanding balance ({bal}).')
            row = c.execute('insert into office_dashboard.invoice_payments(invoice_id,amount,paid_on,method,reference,notes,created_by) values(%s,%s,%s,%s,%s,%s,%s) returning *', (iid, b.amount, b.paid_on, b.method, b.reference, b.notes, s['id'])).fetchone()
            rec(c, actor_id=s['id'], actor_role=s['role'], action='payment_recorded', entity_type='invoice_payment', entity_id=row['id'], after={'invoice_number': inv['invoice_number'], 'amount': b.amount, 'paid_on': b.paid_on, 'method': b.method})
        audit.write('payment_recorded', s['id'], None, invoice_id=iid)
        return row

    @r.post('/payments/{pid}/void')
    def void_payment(pid: str, b: ReasonIn, s=Depends(perm('payments', 'write', True))):
        with db() as c:
            try: p = c.execute('select * from office_dashboard.invoice_payments where id=%s for update', (pid,)).fetchone()
            except psycopg.errors.InvalidTextRepresentation: p = None
            if not p: raise HTTPException(404, 'Payment not found.')
            if p['voided']: raise HTTPException(409, 'This payment is already voided.')
            row = c.execute('update office_dashboard.invoice_payments set voided=true,void_reason=%s,voided_by=%s,voided_at=now() where id=%s returning *', (b.reason, s['id'], pid)).fetchone()
            rec(c, actor_id=s['id'], actor_role=s['role'], action='payment_voided', entity_type='invoice_payment', entity_id=pid, before={'amount': p['amount'], 'invoice_id': p['invoice_id']}, after={'reason': b.reason})
        audit.write('payment_voided', s['id'], None, payment_id=pid)
        return row

    def pay_where(q='', method='', date_from=None, date_to=None, include_voided=False):
        w = ['true'] if include_voided else ['not p.voided']; a = []
        if q.strip(): w.append("(i.invoice_number ilike %s or i.customer_name ilike %s or coalesce(p.reference,'') ilike %s)"); a += [like(q)] * 3
        if method.strip():
            if method not in METHODS: raise HTTPException(422, 'Unknown payment method.')
            w.append('p.method=%s'); a.append(method)
        if date_from: w.append('p.paid_on>=%s'); a.append(date_from)
        if date_to: w.append('p.paid_on<=%s'); a.append(date_to)
        return ' and '.join(w), a
    PAY_FROM = 'office_dashboard.invoice_payments p join office_dashboard.invoices i on i.id=p.invoice_id'

    @r.get('/payments/export')
    def payment_export(q: str = '', method: str = '', date_from: date | None = None, date_to: date | None = None, include_voided: bool = False, s=Depends(perm('payments', 'export'))):
        rng(date_from, date_to); w, a = pay_where(q, method, date_from, date_to, include_voided)
        with db() as c:
            rows = c.execute(f'select p.*, i.invoice_number, i.customer_name from {PAY_FROM} where {w} order by p.paid_on desc, p.created_at desc limit 10000', a).fetchall()
            rec(c, actor_id=s['id'], actor_role=s['role'], action='export', entity_type='invoice_payment', after={'rows': len(rows)})
        return csvutil.csv_response('payments.csv', ['Paid on', 'Invoice', 'Customer', 'Amount', 'Method', 'Reference', 'Notes', 'Voided', 'Void reason'],
                                    [[x['paid_on'], x['invoice_number'], x['customer_name'], x['amount'], x['method'], x['reference'], x['notes'], 'yes' if x['voided'] else 'no', x['void_reason']] for x in rows])

    @r.get('/payments')
    def list_payments(q: str = '', method: str = '', date_from: date | None = None, date_to: date | None = None, include_voided: bool = False, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100), s=Depends(perm('payments', 'read'))):
        rng(date_from, date_to); w, a = pay_where(q, method, date_from, date_to, include_voided)
        with db() as c:
            total = c.execute(f'select count(*)::int n from {PAY_FROM} where {w}', a).fetchone()['n']
            rows = c.execute(f'select p.*, i.invoice_number, i.customer_name from {PAY_FROM} where {w} order by p.paid_on desc, p.created_at desc limit %s offset %s', [*a, limit, (page - 1) * limit]).fetchall()
        return {'items': rows, 'total': total, 'page': page, 'limit': limit, 'methods': METHODS, **flags(s['role'], 'payments', ('write', 'export'))}

    @r.get('/receivables/summary')
    def receivables_summary(s=Depends(perm('payments', 'read'))):
        today = date.today(); b, ba = inv_base(today); m1 = month_start(today)
        with db() as c:
            t = c.execute(f"select coalesce(sum(x.total_amount),0) billed, coalesce(sum(x.paid_amount),0) received, coalesce(sum(x.balance),0) outstanding, "
                          f"coalesce(sum(x.balance) filter (where x.payment_status='OVERDUE'),0) overdue_amount, count(*) filter (where x.payment_status='OVERDUE')::int overdue_count, "
                          f"count(*) filter (where x.payment_status='PARTIAL')::int partial_count, count(*) filter (where x.payment_status='UNPAID')::int pending_count, count(*) filter (where x.payment_status='PAID')::int paid_count "
                          f"from {b} where not x.archived and x.status='SENT'", ba).fetchone()
            ag = c.execute(f"select coalesce(sum(x.balance) filter (where %s-x.due_date between 1 and 30),0) d30, coalesce(sum(x.balance) filter (where %s-x.due_date between 31 and 60),0) d60, "
                           f"coalesce(sum(x.balance) filter (where %s-x.due_date between 61 and 90),0) d90, coalesce(sum(x.balance) filter (where %s-x.due_date>90),0) d90p "
                           f"from {b} where not x.archived and x.status='SENT' and x.balance>0", [today] * 4 + ba).fetchone()
            top = c.execute(f"select x.customer_name, sum(x.balance) outstanding, count(*)::int invoices from {b} where not x.archived and x.status='SENT' and x.balance>0 group by x.customer_name order by 2 desc limit 5", ba).fetchall()
            rm = c.execute('select coalesce(sum(p.amount),0) a from office_dashboard.invoice_payments p where not p.voided and p.paid_on>=%s and p.paid_on<=%s', (m1, today)).fetchone()['a']
        return {'billed': f(t['billed']), 'received': f(t['received']), 'outstanding': f(t['outstanding']), 'overdue_amount': f(t['overdue_amount']), 'overdue_count': t['overdue_count'],
                'partial_count': t['partial_count'], 'pending_count': t['pending_count'], 'paid_count': t['paid_count'], 'received_this_month': f(rm),
                'aging': {'1-30': f(ag['d30']), '31-60': f(ag['d60']), '61-90': f(ag['d90']), '90+': f(ag['d90p'])},
                'top_debtors': [{'customer_name': x['customer_name'], 'outstanding': f(x['outstanding']), 'invoices': x['invoices']} for x in top]}

    def recv_where(q, payment_status):
        if payment_status and payment_status not in ('OVERDUE', 'PARTIAL', 'UNPAID'): raise HTTPException(422, 'Filter must be OVERDUE, PARTIAL or UNPAID.')
        return inv_where(q, payment_status, outstanding=True)

    @r.get('/receivables/export')
    def receivables_export(q: str = '', payment_status: str = '', s=Depends(perm('payments', 'export'))):
        b, ba = inv_base(date.today()); w, a = recv_where(q, payment_status)
        with db() as c:
            rows = c.execute(f'select x.*, (%s - x.due_date) as days_overdue from {b} where {w} order by x.due_date, x.invoice_number limit 10000', [date.today(), *ba, *a]).fetchall()
            rec(c, actor_id=s['id'], actor_role=s['role'], action='export', entity_type='receivable', after={'rows': len(rows)})
        return csvutil.csv_response('receivables.csv', ['Invoice', 'Customer', 'Email', 'Issue date', 'Due date', 'Total', 'Paid', 'Outstanding', 'Status', 'Days overdue'],
                                    [[x['invoice_number'], x['customer_name'], x['customer_email'], x['issue_date'], x['due_date'], x['total_amount'], x['paid_amount'], x['balance'], x['payment_status'], max(x['days_overdue'], 0)] for x in rows])

    @r.get('/receivables')
    def list_receivables(q: str = '', payment_status: str = '', page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100), s=Depends(perm('payments', 'read'))):
        today = date.today(); b, ba = inv_base(today); w, a = recv_where(q, payment_status)
        with db() as c:
            total = c.execute(f'select count(*)::int n from {b} where {w}', [*ba, *a]).fetchone()['n']
            rows = c.execute(f'select x.*, greatest(%s - x.due_date, 0)::int as days_overdue from {b} where {w} order by x.due_date, x.invoice_number limit %s offset %s', [today, *ba, *a, limit, (page - 1) * limit]).fetchall()
        return {'items': rows, 'total': total, 'page': page, 'limit': limit, 'methods': METHODS, **flags(s['role'], 'payments', ('write', 'export'))}

    # ================= EXPENSES =================
    def get_expense(c, eid, lock=False):
        try: row = c.execute('select * from office_dashboard.expenses where id=%s and not archived' + (' for update' if lock else ''), (eid,)).fetchone()
        except psycopg.errors.InvalidTextRepresentation: row = None
        if not row: raise HTTPException(404, 'Expense not found.')
        return row
    def exp_where(q='', status='', category='', vendor='', date_from=None, date_to=None):
        w = ['not archived']; a = []
        if q.strip(): w.append("(expense_number ilike %s or vendor ilike %s or description ilike %s or coalesce(receipt_number,'') ilike %s)"); a += [like(q)] * 4
        if status.strip():
            if status not in EXP_STATUSES: raise HTTPException(422, 'Unknown expense status.')
            w.append('status=%s'); a.append(status)
        if category.strip():
            if category not in CATEGORIES: raise HTTPException(422, 'Unknown expense category.')
            w.append('category=%s'); a.append(category)
        if vendor.strip(): w.append('vendor ilike %s'); a.append(like(vendor))
        if date_from: w.append('expense_date>=%s'); a.append(date_from)
        if date_to: w.append('expense_date<=%s'); a.append(date_to)
        return ' and '.join(w), a
    EX = 'office_dashboard.expenses'
    EXF = ('expense_date', 'category', 'vendor', 'description', 'amount', 'receipt_number', 'receipt_url')

    @r.get('/expenses/summary')
    def expense_summary(s=Depends(perm('expenses', 'read'))):
        m1 = month_start(date.today())
        with db() as c:
            rows = c.execute(f'select status, count(*)::int n, coalesce(sum(amount),0) total from {EX} where not archived group by status').fetchall()
            mo = c.execute(f"select coalesce(sum(amount),0) t from {EX} where not archived and status='APPROVED' and expense_date>=%s", (m1,)).fetchone()['t']
        by = {x['status']: {'count': x['n'], 'total': f(x['total'])} for x in rows}
        return {'by_status': by, 'approved_this_month': f(mo), 'count': sum(x['n'] for x in rows)}

    @r.get('/expenses/report')
    def expense_report(date_from: date | None = None, date_to: date | None = None, status: str = 'APPROVED', s=Depends(perm('expenses', 'read'))):
        rng(date_from, date_to); w, a = exp_where('', status, '', '', date_from, date_to)
        with db() as c:
            tot = c.execute(f'select count(*)::int n, coalesce(sum(amount),0) total from {EX} where {w}', a).fetchone()
            cat = c.execute(f'select category, count(*)::int n, sum(amount) total from {EX} where {w} group by 1 order by 3 desc', a).fetchall()
            ven = c.execute(f'select vendor, count(*)::int n, sum(amount) total from {EX} where {w} group by 1 order by 3 desc limit 10', a).fetchall()
            mon = c.execute(f"select to_char(date_trunc('month', expense_date), 'YYYY-MM') as month, count(*)::int n, sum(amount) total from {EX} where {w} group by 1 order by 1", a).fetchall()
        tt = f(tot['total'])
        return {'count': tot['n'], 'total': tt, 'status': status, 'by_category': [{'category': x['category'], 'count': x['n'], 'total': f(x['total']), 'share': round(f(x['total']) / tt * 100, 1) if tt else 0} for x in cat],
                'by_vendor': [{'vendor': x['vendor'], 'count': x['n'], 'total': f(x['total'])} for x in ven], 'by_month': [{'month': x['month'], 'count': x['n'], 'total': f(x['total'])} for x in mon]}

    @r.get('/expenses/report/export')
    def expense_report_export(date_from: date | None = None, date_to: date | None = None, status: str = 'APPROVED', s=Depends(perm('expenses', 'export'))):
        rng(date_from, date_to); w, a = exp_where('', status, '', '', date_from, date_to)
        with db() as c:
            cat = c.execute(f'select category, vendor, count(*)::int n, sum(amount) total from {EX} where {w} group by 1,2 order by 1,4 desc', a).fetchall()
            rec(c, actor_id=s['id'], actor_role=s['role'], action='export', entity_type='expense_report', after={'rows': len(cat), 'status': status})
        return csvutil.csv_response('expense-report.csv', ['Category', 'Vendor', 'Expenses', 'Total'], [[x['category'], x['vendor'], x['n'], x['total']] for x in cat])

    @r.get('/expenses/export')
    def expense_export(q: str = '', status: str = '', category: str = '', vendor: str = '', date_from: date | None = None, date_to: date | None = None, s=Depends(perm('expenses', 'export'))):
        rng(date_from, date_to); w, a = exp_where(q, status, category, vendor, date_from, date_to)
        with db() as c:
            rows = c.execute(f'select * from {EX} where {w} order by expense_date desc, expense_number desc limit 10000', a).fetchall()
            rec(c, actor_id=s['id'], actor_role=s['role'], action='export', entity_type='expense', after={'rows': len(rows)})
        return csvutil.csv_response('expenses.csv', ['Expense', 'Date', 'Category', 'Vendor', 'Description', 'Amount', 'Receipt no.', 'Receipt link', 'Status', 'Review note'],
                                    [[x['expense_number'], x['expense_date'], x['category'], x['vendor'], x['description'], x['amount'], x['receipt_number'], x['receipt_url'], x['status'], x['review_note']] for x in rows])

    @r.get('/expenses')
    def list_expenses(q: str = '', status: str = '', category: str = '', vendor: str = '', date_from: date | None = None, date_to: date | None = None, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100), s=Depends(perm('expenses', 'read'))):
        rng(date_from, date_to); w, a = exp_where(q, status, category, vendor, date_from, date_to)
        with db() as c:
            total = c.execute(f'select count(*)::int n, coalesce(sum(amount),0) amt from {EX} where {w}', a).fetchone()
            rows = c.execute(f'select * from {EX} where {w} order by expense_date desc, expense_number desc limit %s offset %s', [*a, limit, (page - 1) * limit]).fetchall()
        return {'items': rows, 'total': total['n'], 'filtered_amount': f(total['amt']), 'page': page, 'limit': limit, 'categories': CATEGORIES, 'statuses': EXP_STATUSES,
                **flags(s['role'], 'expenses', ('write', 'approve', 'export', 'archive')), 'me': s['id']}

    @r.post('/expenses', status_code=201)
    def create_expense(b: ExpenseIn, s=Depends(perm('expenses', 'write', True))):
        with db() as c:
            row = c.execute(f'insert into {EX}(expense_date,category,vendor,description,amount,receipt_number,receipt_url,submitted_by) values(%s,%s,%s,%s,%s,%s,%s,%s) returning *', (b.expense_date, b.category, b.vendor, b.description, b.amount, b.receipt_number, b.receipt_url, s['id'])).fetchone()
            rec(c, actor_id=s['id'], actor_role=s['role'], action='create', entity_type='expense', entity_id=row['id'], after={'expense_number': row['expense_number'], 'category': b.category, 'vendor': b.vendor, 'amount': b.amount})
        audit.write('expense_created', s['id'], None, expense_id=str(row['id']))
        return row

    @r.patch('/expenses/{eid}')
    def edit_expense(eid: str, b: ExpenseUpdate, s=Depends(perm('expenses', 'write', True))):
        ch = b.model_dump(exclude_unset=True)
        if not ch: raise HTTPException(422, 'Nothing to update.')
        for k in ('expense_date', 'category', 'vendor', 'amount'):
            if k in ch and ch[k] is None: raise HTTPException(422, f'{k.replace("_", " ").title()} cannot be empty.')
        if ch.get('description', 0) is None: ch['description'] = ''
        with db() as c:
            old = get_expense(c, eid, lock=True)
            if old['status'] == 'APPROVED': raise HTTPException(409, 'An approved expense is locked and cannot be edited.')
            diff = {k: v for k, v in ch.items() if k in EXF and old[k] != v and not (isinstance(v, Decimal) and Decimal(str(old[k])) == v)}
            if not diff: return old
            sets = dict(diff)
            if old['status'] == 'REJECTED': sets.update(status='PENDING', reviewed_by=None, reviewed_at=None, review_note=None)   # an edited rejected expense goes back for review
            row = c.execute(f'update {EX} set ' + ','.join(f'{k}=%s' for k in sets) + ',updated_at=now() where id=%s returning *', [*sets.values(), eid]).fetchone()
            rec(c, actor_id=s['id'], actor_role=s['role'], action='update', entity_type='expense', entity_id=eid, before={k: old[k] for k in diff}, after=sets)
        audit.write('expense_updated', s['id'], None, expense_id=eid, fields=sorted(diff))
        return row

    def review(eid, s, status, note):
        with db() as c:
            old = get_expense(c, eid, lock=True)
            if old['status'] != 'PENDING': raise HTTPException(409, f'Only a pending expense can be reviewed (this one is {old["status"].lower()}).')
            if old['submitted_by'] == s['id']: raise HTTPException(403, 'You cannot approve or reject an expense you submitted. Ask another approver.')
            row = c.execute(f'update {EX} set status=%s,reviewed_by=%s,reviewed_at=now(),review_note=%s,updated_at=now() where id=%s returning *', (status, s['id'], note or None, eid)).fetchone()
            rec(c, actor_id=s['id'], actor_role=s['role'], action='approval' if status == 'APPROVED' else 'rejection', entity_type='expense', entity_id=eid, before={'status': 'PENDING'}, after={'status': status, 'note': note, 'amount': old['amount']})
        audit.write('expense_' + status.lower(), s['id'], None, expense_id=eid)
        return row

    @r.post('/expenses/{eid}/approve')
    def approve(eid: str, b: ReviewIn, s=Depends(perm('expenses', 'approve', True))): return review(eid, s, 'APPROVED', b.note)

    @r.post('/expenses/{eid}/reject')
    def reject(eid: str, b: ReviewIn, s=Depends(perm('expenses', 'approve', True))):
        if not b.note: raise HTTPException(422, 'Enter a reason for rejecting this expense.')
        return review(eid, s, 'REJECTED', b.note)

    @r.delete('/expenses/{eid}')
    def archive_expense(eid: str, s=Depends(perm('expenses', 'archive', True))):
        with db() as c:
            old = get_expense(c, eid, lock=True)
            if old['status'] == 'APPROVED': raise HTTPException(409, 'An approved expense cannot be archived.')
            c.execute(f'update {EX} set archived=true,updated_at=now() where id=%s', (eid,))
            rec(c, actor_id=s['id'], actor_role=s['role'], action='archive', entity_type='expense', entity_id=eid, before={'expense_number': old['expense_number']})
        audit.write('expense_archived', s['id'], None, expense_id=eid)
        return {'ok': True, 'archived': eid}

    # ================= BUDGET & FORECAST =================
    def mdate(m: str) -> date: return date(int(m[:4]), int(m[5:7]), 1)

    @r.get('/budgets')
    def list_budgets(year: int | None = Query(default=None, ge=2000, le=2100), s=Depends(perm('budget', 'read'))):
        year = year or date.today().year
        with db() as c:
            rows = c.execute("select id,kind,category,to_char(period_month,'YYYY-MM') as month,amount,notes,updated_at from office_dashboard.budgets where period_month>=%s and period_month<%s order by period_month, kind, category", (date(year, 1, 1), date(year + 1, 1, 1))).fetchall()
        return {'year': year, 'items': rows, 'categories': CATEGORIES, **flags(s['role'], 'budget', ('write', 'export'))}

    @r.put('/budgets')
    def upsert_budget(b: BudgetIn, s=Depends(perm('budget', 'write', True))):
        cat = 'REVENUE' if b.kind == 'REVENUE' else b.category
        if b.kind == 'EXPENSE' and cat not in CATEGORIES: raise HTTPException(422, 'Choose an expense category.')
        with db() as c:
            old = c.execute('select * from office_dashboard.budgets where kind=%s and category=%s and period_month=%s for update', (b.kind, cat, mdate(b.month))).fetchone()
            if old: row = c.execute('update office_dashboard.budgets set amount=%s,notes=%s,updated_by=%s,updated_at=now() where id=%s returning *', (b.amount, b.notes, s['id'], old['id'])).fetchone()
            else: row = c.execute('insert into office_dashboard.budgets(kind,category,period_month,amount,notes,created_by) values(%s,%s,%s,%s,%s,%s) returning *', (b.kind, cat, mdate(b.month), b.amount, b.notes, s['id'])).fetchone()
            rec(c, actor_id=s['id'], actor_role=s['role'], action='update' if old else 'create', entity_type='budget', entity_id=row['id'], before={'amount': old['amount']} if old else None, after={'kind': b.kind, 'category': cat, 'month': b.month, 'amount': b.amount})
        audit.write('budget_saved', s['id'], None, budget_id=str(row['id']))
        return row

    @r.delete('/budgets/{bid}')
    def delete_budget(bid: str, s=Depends(perm('budget', 'write', True))):
        with db() as c:
            try: old = c.execute('select * from office_dashboard.budgets where id=%s for update', (bid,)).fetchone()
            except psycopg.errors.InvalidTextRepresentation: old = None
            if not old: raise HTTPException(404, 'Budget line not found.')
            c.execute('delete from office_dashboard.budgets where id=%s', (bid,))
            rec(c, actor_id=s['id'], actor_role=s['role'], action='delete', entity_type='budget', entity_id=bid, before={'kind': old['kind'], 'category': old['category'], 'period_month': old['period_month'], 'amount': old['amount']})
        audit.write('budget_deleted', s['id'], None, budget_id=bid)
        return {'ok': True}

    def monthly_actuals(c, start, end):
        """Actual revenue = invoices issued (sent, not cancelled/archived) by issue month. Actual expense = approved expenses by expense month."""
        rev = {x['m']: f(x['t']) for x in c.execute("select to_char(date_trunc('month',issue_date),'YYYY-MM') m, sum(total_amount) t from office_dashboard.invoices where not archived and status='SENT' and issue_date>=%s and issue_date<%s group by 1", (start, end)).fetchall()}
        exp = {x['m']: f(x['t']) for x in c.execute(f"select to_char(date_trunc('month',expense_date),'YYYY-MM') m, sum(amount) t from {EX} where not archived and status='APPROVED' and expense_date>=%s and expense_date<%s group by 1", (start, end)).fetchall()}
        return rev, exp

    def forecast(c, today):
        cur = month_start(today)
        first = c.execute(f"select least((select min(issue_date) from office_dashboard.invoices where not archived and status='SENT'), (select min(expense_date) from {EX} where not archived and status='APPROVED')) d").fetchone()['d']
        if not first or month_start(first) >= cur: return {'available': False, 'reason': f'Not enough history yet: forecasts need at least {MIN_FORECAST_MONTHS} completed months of invoices or approved expenses, and none are complete so far.', 'history_months': 0, 'required_months': MIN_FORECAST_MONTHS}
        start = month_start(first); rev, exp = monthly_actuals(c, start, cur)
        months = []; d = start
        while d < cur: months.append(d.strftime('%Y-%m')); d = add_months(d, 1)
        active = [m for m in months if rev.get(m, 0) or exp.get(m, 0)]
        if len(active) < MIN_FORECAST_MONTHS:
            return {'available': False, 'reason': f'Not enough history yet: {len(active)} completed month(s) with activity found; at least {MIN_FORECAST_MONTHS} are needed.', 'history_months': len(active), 'required_months': MIN_FORECAST_MONTHS}
        basis = months[-FORECAST_WINDOW:]; n = len(basis)
        ar, ae = sum(rev.get(m, 0) for m in basis) / n, sum(exp.get(m, 0) for m in basis) / n
        out = [{'month': add_months(cur, i).strftime('%Y-%m'), 'revenue': round(ar, 2), 'expenses': round(ae, 2), 'net': round(ar - ae, 2)} for i in range(FORECAST_AHEAD)]
        return {'available': True, 'method': f'Average of the last {n} completed month(s) of invoiced revenue and approved expenses', 'basis_months': n, 'history_months': len(active), 'required_months': MIN_FORECAST_MONTHS, 'items': out}

    def compare_data(c, year):
        today = date.today(); y0, y1 = date(year, 1, 1), date(year + 1, 1, 1)
        rev, exp = monthly_actuals(c, y0, y1)
        bud = c.execute("select kind,category,to_char(period_month,'YYYY-MM') m,amount from office_dashboard.budgets where period_month>=%s and period_month<%s", (y0, y1)).fetchall()
        br, be, bcat = {}, {}, {}
        for x in bud:
            if x['kind'] == 'REVENUE': br[x['m']] = br.get(x['m'], 0) + f(x['amount'])
            else: be[x['m']] = be.get(x['m'], 0) + f(x['amount']); bcat[x['category']] = bcat.get(x['category'], 0) + f(x['amount'])
        acat = {x['category']: f(x['t']) for x in c.execute(f"select category, sum(amount) t from {EX} where not archived and status='APPROVED' and expense_date>=%s and expense_date<%s group by 1", (y0, y1)).fetchall()}
        months = []
        for i in range(12):
            m = date(year, i + 1, 1).strftime('%Y-%m')
            months.append({'month': m, 'budget_revenue': br.get(m), 'actual_revenue': rev.get(m, 0), 'budget_expenses': be.get(m), 'actual_expenses': exp.get(m, 0), 'future': date(year, i + 1, 1) > today})
        cats = [{'category': k, 'budget': bcat.get(k), 'actual': acat.get(k, 0)} for k in CATEGORIES if k in bcat or k in acat]
        tr, te = sum(br.values()), sum(be.values())
        return {'year': year, 'months': months, 'categories': cats, 'totals': {'budget_revenue': tr if br else None, 'actual_revenue': sum(rev.values()), 'budget_expenses': te if be else None, 'actual_expenses': sum(exp.values())},
                'basis': 'Actual revenue = invoices issued (sent, not cancelled) by issue date. Actual expenses = approved expenses by expense date.'}

    @r.get('/budget/compare')
    def compare(year: int | None = Query(default=None, ge=2000, le=2100), s=Depends(perm('budget', 'read'))):
        year = year or date.today().year
        with db() as c: data = compare_data(c, year); fc = forecast(c, date.today())
        return {**data, 'forecast': fc, **flags(s['role'], 'budget', ('write', 'export'))}

    @r.get('/budget/export')
    def budget_export(year: int | None = Query(default=None, ge=2000, le=2100), s=Depends(perm('budget', 'export'))):
        year = year or date.today().year
        with db() as c:
            d = compare_data(c, year)
            rec(c, actor_id=s['id'], actor_role=s['role'], action='export', entity_type='budget', after={'year': year})
        head = ['Month', 'Budget revenue', 'Actual revenue', 'Revenue variance', 'Budget expenses', 'Actual expenses', 'Expense variance']
        rows = [[m['month'], m['budget_revenue'], m['actual_revenue'], None if m['budget_revenue'] is None else round(m['actual_revenue'] - m['budget_revenue'], 2), m['budget_expenses'], m['actual_expenses'], None if m['budget_expenses'] is None else round(m['budget_expenses'] - m['actual_expenses'], 2)] for m in d['months']]
        return csvutil.csv_response(f'budget-vs-actual-{year}.csv', head, rows)
    return r
