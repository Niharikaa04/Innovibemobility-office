-- Rollback for 016. DESTROYS all invoices, payments, expenses and budgets. Never run on production without a backup.
drop table if exists office_dashboard.budgets;
drop table if exists office_dashboard.expenses;
drop table if exists office_dashboard.invoice_payments;
drop table if exists office_dashboard.invoice_items;
drop table if exists office_dashboard.invoices;
drop sequence if exists office_dashboard.invoice_number_seq;
drop sequence if exists office_dashboard.expense_number_seq;
