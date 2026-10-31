import subprocess, sys, os
def test_dotenv_with_utf8_bom_is_read(tmp_path):
    (tmp_path / ".env").write_bytes(b"\xef\xbb\xbfDATABASE_URL=postgresql://u:p@h:5432/d\nSESSION_SECRET=s\n")
    code = "import os; from dotenv import load_dotenv; load_dotenv(encoding='utf-8-sig'); print(os.environ['DATABASE_URL'])"
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "SESSION_SECRET")}
    out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert out.stdout.strip() == "postgresql://u:p@h:5432/d", out.stderr
def test_main_loads_dotenv_with_the_bom_safe_encoding():
    """Regression guard on OUR code (not on python-dotenv's version-dependent behaviour): main.py must keep passing encoding='utf-8-sig'."""
    import ast, pathlib
    tree = ast.parse((pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "load_dotenv"]
    assert calls and all(any(k.arg == "encoding" and getattr(k.value, "value", None) == "utf-8-sig" for k in c.keywords) for c in calls)
