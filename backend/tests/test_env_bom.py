import subprocess, sys, os
def test_dotenv_with_utf8_bom_is_read(tmp_path):
    (tmp_path / ".env").write_bytes(b"\xef\xbb\xbfDATABASE_URL=postgresql://u:p@h:5432/d\nSESSION_SECRET=s\n")
    code = "import os; from dotenv import load_dotenv; load_dotenv(encoding='utf-8-sig'); print(os.environ['DATABASE_URL'])"
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "SESSION_SECRET")}
    out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert out.stdout.strip() == "postgresql://u:p@h:5432/d", out.stderr
def test_plain_dotenv_with_bom_is_broken_without_the_fix(tmp_path):
    (tmp_path / ".env").write_bytes(b"\xef\xbb\xbfDATABASE_URL=x\n")
    code = "import os; from dotenv import load_dotenv; load_dotenv(); print('DATABASE_URL' in os.environ)"
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    assert subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True).stdout.strip() == "False"
