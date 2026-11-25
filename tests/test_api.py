"""
tests/test_api.py
=================
FastAPI endpoint testleri. Gerçek veritabanı kullanılmaz: CollectorEngine
yerine sahte bir engine monkeypatch ile verilir. TestClient context manager
olarak kullanılmadığı için lifespan (scheduler, registry) çalışmaz.
"""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg2
import pytest
from fastapi.testclient import TestClient

import api.main as main


# ---------------------------------------------------------------------------
# Sahte DB katmanı
# ---------------------------------------------------------------------------

ROW = {
    "kontrol_tarihi": datetime(2026, 11, 8, 10, 0, tzinfo=timezone.utc),
    "db_type": "postgresql",
    "host": "dq-postgres",
    "db_name": "dwhmonitor",
    "kategori": "kalite",
    "kontrol_kodu": "FR-DQ-04",
    "kontrol_adi": "Null oranı",
    "sonuc": "WARNING",
    "severity": 2,
    "etkilenen_obje": "public.orders",
    "etkilenen_sayi": 12,
    "detay": "null oranı %12",
}


class FakeCursor:
    def __init__(self, rows, log):
        self._rows = rows
        self._log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._log.append((sql, params))

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    def __init__(self, rows):
        self._rows = rows
        self.executed: list = []
        self.readonly = False
        self.closed = False

    def set_session(self, readonly=False, **_):
        self.readonly = readonly

    def cursor(self, cursor_factory=None):
        return FakeCursor(self._rows, self.executed)

    def close(self):
        self.closed = True


class FakeEngine:
    """CollectorEngine'in /logs için kullanılan kısmı."""

    def __init__(self, rows=None, error: Exception | None = None):
        self.conn = FakeConnection(rows or [])
        self._error = error

    def _open_connection(self):
        if self._error is not None:
            raise self._error
        return self.conn

    def get_circuit_status(self):
        return {}

    def get_last_metrics(self):
        return []


@pytest.fixture(autouse=True)
def _no_api_key_env(monkeypatch):
    # Ortamdaki API_KEY testleri etkilemesin.
    monkeypatch.delenv("API_KEY", raising=False)


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def fake_engine(monkeypatch):
    eng = FakeEngine(rows=[ROW])
    monkeypatch.setattr(main, "engine", eng)
    return eng


# ---------------------------------------------------------------------------
# GET /logs — parametre doğrulama
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "query",
    [
        "sonuc=BAD",
        "sonuc=ok",
        "severity=0",
        "severity=4",
        "limit=0",
        "limit=1001",
        "offset=-1",
        "since=gecersiz-tarih",
    ],
)
def test_logs_bad_params_return_422(client, fake_engine, query):
    resp = client.get(f"/logs?{query}")
    assert resp.status_code == 422


def test_logs_since_after_until_returns_422(client, fake_engine):
    resp = client.get(
        "/logs?since=2026-11-09T00:00:00Z&until=2026-11-01T00:00:00Z"
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /logs — DB erişilemez
# ---------------------------------------------------------------------------

def test_logs_503_when_engine_not_ready(client, monkeypatch):
    monkeypatch.setattr(main, "engine", None)
    resp = client.get("/logs")
    assert resp.status_code == 503
    assert "detail" in resp.json()


def test_logs_503_when_db_unreachable_is_generic(client, monkeypatch):
    secret = "parola-sızıntı-testi-9f2"
    err = psycopg2.OperationalError(
        f"connection to server at \"10.0.0.5\", port 5432 failed: password={secret}"
    )
    monkeypatch.setattr(main, "engine", FakeEngine(error=err))

    resp = client.get("/logs")

    assert resp.status_code == 503
    body = resp.text
    assert secret not in body
    assert "10.0.0.5" not in body
    assert "Traceback" not in body
    assert resp.json() == {"detail": main.DB_UNAVAILABLE_DETAIL}


# ---------------------------------------------------------------------------
# GET /logs — başarılı yanıt ve sorgu
# ---------------------------------------------------------------------------

def test_logs_success_returns_listed_columns_only(client, fake_engine):
    resp = client.get("/logs")

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["limit"] == 100
    assert body["offset"] == 0
    assert set(body["items"][0].keys()) == {
        "kontrol_tarihi", "db_type", "host", "db_name", "kategori",
        "kontrol_kodu", "kontrol_adi", "sonuc", "severity",
        "etkilenen_obje", "etkilenen_sayi", "detay",
    }
    assert body["items"][0]["sonuc"] == "WARNING"
    assert fake_engine.conn.readonly is True
    assert fake_engine.conn.closed is True


def test_logs_builds_parameterised_filtered_query(client, fake_engine):
    evil = "x' OR '1'='1"
    resp = client.get(
        "/logs",
        params={
            "db_name": evil,
            "kontrol_kodu": "FR-DQ-04",
            "sonuc": "ERROR",
            "severity": 3,
            "since": "2026-11-01T00:00:00Z",
            "limit": 10,
            "offset": 5,
        },
    )

    assert resp.status_code == 200
    sql, params = fake_engine.conn.executed[-1]

    # Kullanıcı girdisi SQL metninde değil, parametrelerde olmalı.
    assert evil not in sql
    assert "db_name = %s" in sql
    assert "kontrol_kodu = %s" in sql
    assert "sonuc = %s" in sql
    assert "severity = %s" in sql
    assert "kontrol_tarihi >= %s" in sql
    assert "ORDER BY kontrol_tarihi DESC" in sql
    assert sql.count("%s") == len(params)

    assert params[0] == evil
    assert params[1] == "FR-DQ-04"
    assert params[2] == "ERROR"
    assert params[3] == 3
    assert params[4] == datetime(2026, 11, 1, tzinfo=timezone.utc)
    assert params[-2:] == [10, 5]


def test_logs_naive_datetime_is_treated_as_utc(client, fake_engine):
    resp = client.get("/logs", params={"until": "2026-11-05T12:00:00"})
    assert resp.status_code == 200
    _, params = fake_engine.conn.executed[-1]
    assert params[0] == datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# API anahtarı (F3-07)
# ---------------------------------------------------------------------------

API_KEY = "test-anahtar-7c1e"
PROTECTED = ["/metrics", "/collect", "/logs/summary", "/adapters", "/logs"]


def test_auth_disabled_when_api_key_unset(client, fake_engine):
    assert client.get("/adapters").status_code == 200
    assert client.get("/logs").status_code == 200


def test_auth_disabled_when_api_key_empty(client, fake_engine, monkeypatch):
    monkeypatch.setenv("API_KEY", "")
    assert client.get("/adapters").status_code == 200
    assert client.get("/adapters", headers={"X-API-Key": "rastgele"}).status_code == 200


def test_auth_enabled_rejects_missing_key(client, fake_engine, monkeypatch):
    monkeypatch.setenv("API_KEY", API_KEY)
    for path in PROTECTED:
        resp = client.get(path)
        assert resp.status_code == 401, path


def test_auth_enabled_rejects_wrong_key_without_echo(client, fake_engine, monkeypatch):
    monkeypatch.setenv("API_KEY", API_KEY)
    wrong = "yanlis-anahtar"
    for path in PROTECTED:
        resp = client.get(path, headers={"X-API-Key": wrong})
        assert resp.status_code == 401, path
        assert wrong not in resp.text
        assert API_KEY not in resp.text


def test_auth_enabled_accepts_correct_key(client, fake_engine, monkeypatch):
    monkeypatch.setenv("API_KEY", API_KEY)
    headers = {"X-API-Key": API_KEY}
    assert client.get("/adapters", headers=headers).status_code == 200
    assert client.get("/logs", headers=headers).status_code == 200
    assert client.get("/logs/summary", headers=headers).status_code == 200


def test_health_open_when_auth_enabled(client, monkeypatch):
    monkeypatch.setenv("API_KEY", API_KEY)
    resp = client.get("/health")
    assert resp.status_code == 200
