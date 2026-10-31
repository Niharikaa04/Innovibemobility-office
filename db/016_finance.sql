-- 016: Finance (Revenue & Invoices, Payments & Receivables, Expenses, Budget & Forecast).
-- Additive and safe to re-run. Apply after 003 (contacts) and 005 (audit_log).
-- Money columns are numeric(14,2). Payment status of an invoice is NOT stored: it is derived from invoice_payments so it can never drift.

create sequence if not exists office_dashboard.invoice_number_seq;
create sequence if not exists office_dashboard.expense_number_seq;

create table if not exists office_dashboard.invoices (
 id uuid primary key default gen_random_uuid(),
 invoice_number text not null default ('INV-' || lpad(nextval('office_dashboard.invoice_number_seq')::text, 5, '0')),
 contact_id uuid references office_dashboard.contacts(id),
 customer_name text not null check (length(trim(customer_name)) between 1 and 180),
 customer_email text check (customer_email is null or length(customer_email) <= 254),
 customer_address text check (customer_address is null or length(customer_address) <= 500),
 customer_tax_id text check (customer_tax_id is null or length(customer_tax_id) <= 40),
 issue_date date not null default current_date,
 due_date date not null,
 tax_percent numeric(5,2) not null default 0 check (tax_percent >= 0 and tax_percent <= 100),
 subtotal numeric(14,2) not null default 0 check (subtotal >= 0),
 tax_amount numeric(14,2) not null default 0 check (tax_amount >= 0),
 total_amount numeric(14,2) not null default 0 check (total_amount >= 0),
 status text not null default 'DRAFT' check (status in ('DRAFT','SENT','CANCELLED')),
 notes text not null default '' check (length(notes) <= 3000),
 cancelled_reason text,
 created_by text not null, archived boolean not null default false,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 check (due_date >= issue_date)
);
create unique index if not exists invoices_number_uq on office_dashboard.invoices(invoice_number);
create index if not exists invoices_status_idx on office_dashboard.invoices(status, due_date) where not archived;
create index if not exists invoices_issue_idx on office_dashboard.invoices(issue_date) where not archived;
create index if not exists invoices_contact_idx on office_dashboard.invoices(contact_id);

create table if not exists office_dashboard.invoice_items (
 id bigserial primary key,
 invoice_id uuid not null references office_dashboard.invoices(id) on delete cascade,
 position int not null default 0,
 description text not null check (length(trim(description)) between 1 and 300),
 quantity numeric(12,2) not null check (quantity > 0),
 unit_price numeric(14,2) not null check (unit_price >= 0)
);
create index if not exists invoice_items_invoice_idx on office_dashboard.invoice_items(invoice_id, position);

create table if not exists office_dashboard.invoice_payments (
 id uuid primary key default gen_random_uuid(),
 invoice_id uuid not null references office_dashboard.invoices(id),
 amount numeric(14,2) not null check (amount > 0),
 paid_on date not null,
 method text not null default 'BANK_TRANSFER' check (method in ('BANK_TRANSFER','UPI','CARD','CASH','CHEQUE','OTHER')),
 reference text check (reference is null or length(reference) <= 120),
 notes text not null default '' check (length(notes) <= 1000),
 voided boolean not null default false, void_reason text, voided_by text, voided_at timestamptz,
 created_by text not null, created_at timestamptz not null default now()
);
create index if not exists invoice_payments_invoice_idx on office_dashboard.invoice_payments(invoice_id) where not voided;
create index if not exists invoice_payments_paid_idx on office_dashboard.invoice_payments(paid_on) where not voided;

create table if not exists office_dashboard.expenses (
 id uuid primary key default gen_random_uuid(),
 expense_number text not null default ('EXP-' || lpad(nextval('office_dashboard.expense_number_seq')::text, 5, '0')),
 expense_date date not null,
 category text not null check (category in ('SALARIES','RENT','UTILITIES','TRAVEL','EQUIPMENT','MARKETING','SOFTWARE','MAINTENANCE','PARTS_AND_INVENTORY','PROFESSIONAL_FEES','TAXES','OTHER')),
 vendor text not null check (length(trim(vendor)) between 1 and 180),
 description text not null default '' check (length(description) <= 2000),
 amount numeric(14,2) not null check (amount > 0),
 receipt_number text check (receipt_number is null or length(receipt_number) <= 80),
 receipt_url text check (receipt_url is null or (length(receipt_url) <= 500 and receipt_url ~* '^https?://')),
 status text not null default 'PENDING' check (status in ('PENDING','APPROVED','REJECTED')),
 submitted_by text not null, reviewed_by text, reviewed_at timestamptz, review_note text,
 archived boolean not null default false,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create unique index if not exists expenses_number_uq on office_dashboard.expenses(expense_number);
create index if not exists expenses_date_idx on office_dashboard.expenses(expense_date) where not archived;
create index if not exists expenses_status_idx on office_dashboard.expenses(status) where not archived;
create index if not exists expenses_category_idx on office_dashboard.expenses(category) where not archived;

-- One budget line per (kind, category, month). Revenue budgets use category 'REVENUE'.
create table if not exists office_dashboard.budgets (
 id uuid primary key default gen_random_uuid(),
 kind text not null check (kind in ('REVENUE','EXPENSE')),
 category text not null check (category in ('REVENUE','SALARIES','RENT','UTILITIES','TRAVEL','EQUIPMENT','MARKETING','SOFTWARE','MAINTENANCE','PARTS_AND_INVENTORY','PROFESSIONAL_FEES','TAXES','OTHER')),
 period_month date not null check (period_month = date_trunc('month', period_month)::date),
 amount numeric(14,2) not null check (amount >= 0),
 notes text not null default '' check (length(notes) <= 500),
 created_by text not null, updated_by text,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 check ((kind = 'REVENUE') = (category = 'REVENUE'))
);
create unique index if not exists budgets_line_uq on office_dashboard.budgets(kind, category, period_month);

alter table office_dashboard.invoices enable row level security;
alter table office_dashboard.invoice_items enable row level security;
alter table office_dashboard.invoice_payments enable row level security;
alter table office_dashboard.expenses enable row level security;
alter table office_dashboard.budgets enable row level security;
