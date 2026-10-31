"""READ-ONLY schema inspector. Prints structure and hash PREFIXES only (never hashes, emails or passwords)."""
import os, sys, collections, psycopg
from dotenv import load_dotenv; load_dotenv(encoding="utf-8-sig")
KW = ("user", "account", "login", "auth", "employee", "role", "permission", "session", "audit")
with psycopg.connect(os.environ["DATABASE_URL"]) as c:
    c.read_only = True
    t = c.execute("select table_schema,table_name from information_schema.tables where table_schema not in ('pg_catalog','information_schema','auth','storage','realtime','vault','extensions','graphql','graphql_public','pgbouncer','supabase_functions') order by 1,2").fetchall()
    print("== Candidate tables =="); cand = [(s, n) for s, n in t if any(k in n.lower() for k in KW)]
    for s, n in cand:
        print(f"\n{s}.{n}")
        for col, typ, nul in c.execute("select column_name,data_type,is_nullable from information_schema.columns where table_schema=%s and table_name=%s order by ordinal_position", (s, n)): print(f"   {col:30} {typ:22} null={nul}")
        for fk in c.execute("select kcu.column_name,ccu.table_schema||'.'||ccu.table_name,ccu.column_name from information_schema.table_constraints tc join information_schema.key_column_usage kcu using(constraint_name,table_schema) join information_schema.constraint_column_usage ccu using(constraint_name) where tc.constraint_type='FOREIGN KEY' and tc.table_schema=%s and tc.table_name=%s", (s, n)): print("   FK", fk)
    print("\n== Other tables ==", [f"{s}.{n}" for s, n in t if (s, n) not in cand])
    tbl = os.getenv("USERS_TABLE")
    if tbl:
        s, n = tbl.split(".") if "." in tbl else ("public", tbl)
        pw, role = os.getenv("COL_PASSWORD"), os.getenv("COL_ROLE")
        if pw:
            q = f'select left("{pw}"::text, case when "{pw}"::text like \'$%\' then 4 else 7 end) p, count(*) from "{s}"."{n}" group by 1'
            print("\n== Hash prefixes =="); [print("  ", r) for r in c.execute(q)]
        if role: print("\n== Distinct role values =="); [print("  ", r) for r in c.execute(f'select "{role}"::text, count(*) from "{s}"."{n}" group by 1')]
