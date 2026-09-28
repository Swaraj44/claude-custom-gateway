import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def auth_headers():
    return {"Authorization": "Bearer %s" % settings.api_key} if settings.api_key else {}


def test_health_open():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["timeout_s"] == settings.timeout


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "ClaudeBridge" in r.text
    assert "text/html" in r.headers["content-type"]


def test_models_listed():
    r = client.get("/v1/models", headers=auth_headers())
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()["data"]]
    assert ids == list(settings.models)


@pytest.mark.skipif(not settings.api_key, reason="auth disabled")
def test_chat_rejects_wrong_api_key():
    r = client.post("/api/chat", json={"prompt": "hi"}, headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


@pytest.mark.skipif(not settings.api_key, reason="auth disabled")
def test_chat_validation_error_format():
    r = client.post("/api/chat", json={"prompt": "   "}, headers=auth_headers())
    assert r.status_code == 400
    assert "error" in r.json()


@pytest.mark.skipif(not settings.api_key, reason="auth disabled")
def test_openai_validation_error_format():
    r = client.post("/v1/chat/completions", json={"messages": []}, headers=auth_headers())
    assert r.status_code == 400
    assert r.json()["error"]["type"] == "invalid_request_error"
