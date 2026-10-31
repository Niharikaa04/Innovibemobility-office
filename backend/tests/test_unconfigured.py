import pytest
from fastapi.testclient import TestClient
import config, main
def test_unconfigured_backend_answers_every_method_with_clear_503(monkeypatch):
    monkeypatch.delenv("USERS_TABLE", raising=False); monkeypatch.setenv("SESSION_SECRET", "x"); monkeypatch.setenv("DATABASE_URL", "x")
    import importlib; m = importlib.reload(main); c = TestClient(m.app)
    for method in ("get", "post", "put", "delete"):
        r = getattr(c, method)("/api/auth/login"); assert r.status_code == 503 and "not configured" in r.json()["detail"], method
