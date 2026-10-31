-- Safe bootstrap: seed department labels only. No personal records, emails, usernames, or password hashes
-- are distributed in this source archive. Create real users through the approved admin process.
insert into office_dashboard.departments (name) values
 ('Executive'),('Operations'),('Technology'),('Service'),('HR'),('IT'),('R&D')
on conflict (name) do nothing;
