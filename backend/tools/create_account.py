"""Create ONE employee + login (and a technician profile when role=technician). Run on your own machine.
The password is read hidden from the keyboard (or --password-stdin), hashed with bcrypt, and never printed or logged.
Only INSERTs into office_dashboard tables; refuses duplicates; all-or-nothing transaction."""
import argparse, getpass, os, re, sys
import bcrypt, psycopg
from dotenv import load_dotenv
ROLES = ("ceo", "coo", "cto", "service_manager", "hr", "technician", "employee")
def die(m): print("ERROR:", m); sys.exit(1)
def main(argv=None):
    load_dotenv(encoding="utf-8-sig"); a = argparse.ArgumentParser()
    a.add_argument("--role", required=True, choices=ROLES); a.add_argument("--username", required=True); a.add_argument("--name", required=True)
    a.add_argument("--email", required=True); a.add_argument("--designation"); a.add_argument("--employee-code")
    a.add_argument("--must-change-password", action="store_true"); a.add_argument("--password-stdin", action="store_true")
    a = a.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", a.username): die("username: 3-40 characters, letters, digits, . _ -")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", a.email): die("email does not look valid")
    if not os.getenv("DATABASE_URL"): die("DATABASE_URL is not set (put it in backend/.env)")
    if a.password_stdin: pw = sys.stdin.readline().rstrip("\r\n")
    else:
        pw = getpass.getpass("Password (hidden): ")
        if pw != getpass.getpass("Repeat password: "): die("passwords do not match")
    if len(pw) < 10: die("password must be at least 10 characters")
    if len(pw.encode()) > 72: die("password is longer than 72 bytes (bcrypt limit)")
    h = bcrypt.hashpw(pw.encode(), bcrypt.gensalt(12)).decode(); del pw
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:        # one transaction: commits only if everything succeeds
        if c.execute("select 1 from office_dashboard.users where lower(username)=lower(%s)", (a.username,)).fetchone(): die("that username already exists")
        if c.execute("select 1 from office_dashboard.employees where lower(email)=lower(%s)", (a.email,)).fetchone(): die("an employee with that email already exists (no duplicate people)")
        code = a.employee_code or "EMP-%04d" % (c.execute("select count(*)+1 from office_dashboard.employees").fetchone()[0])
        while c.execute("select 1 from office_dashboard.employees where employee_code=%s", (code,)).fetchone():
            if a.employee_code: die("that employee code already exists")
            code = "EMP-%04d" % (int(code[4:]) + 1)
        eid = c.execute("insert into office_dashboard.employees(employee_code,full_name,email,designation) values(%s,%s,%s,%s) returning id", (code, a.name, a.email, a.designation or a.role.replace("_", " ").title())).fetchone()[0]
        c.execute("insert into office_dashboard.users(employee_id,username,password_hash,role,must_change_password) values(%s,%s,%s,%s,%s)", (eid, a.username, h, a.role, a.must_change_password))
        if a.role == "technician": c.execute("insert into office_dashboard.technicians(employee_id) values(%s)", (eid,))
        c.execute("insert into office_dashboard.audit_log(user_id,action,detail) values(%s,'account_created',%s::jsonb)", ("cli", '{"username": "%s", "role": "%s"}' % (a.username, a.role)))
    print(f"Created {a.role} account '{a.username}' for {a.name} ({code}). Password was not stored anywhere except as a bcrypt hash.")
if __name__ == "__main__": main()
