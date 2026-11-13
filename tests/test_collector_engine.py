"""
tests/test_collector_engine.py
==============================
CollectorEngine testleri (F08-F13). Sahte registry/adapter/notifier kullanılır;
gerçek veritabanına bağlanılmaz, _persist monkeypatch ile değiştirilir.
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

import api.main as main
from core.base_adapter import HealthResult
from core.collector_engine import CollectionBusy, CollectorEngine
from core.metric_schema import MetricSchema


SECRET = "S3cr3tPw"


def _metric(db_name: str) -> MetricSchema:
    return MetricSchema(
        db_type="postgresql", host="h", db_name=db_name, kategori="kalite",
        kontrol_kodu="FR-DQ-01", kontrol_adi="Test", sonuc="OK", severity=1,
    )


class FakeAdapter:
    def __init__(self, name, healthy=True, connect_exc=None, block=None, entered=None):
        self.name = name
        self.healthy = healthy
        self.connect_exc = connect_exc
        self.block = block
        self.entered = entered
        self.disconnected = 0

    def connect(self):
        if self.connect_exc:
            raise self.connect_exc

    def health_check(self):
        return HealthResult(is_healthy=self.healthy, latency_ms=1.0,
                            message=None if self.healthy else "yanit yok")

    def collect_metrics(self):
        if self.entered:
            self.entered.set()
        if self.block:
            self.block.wait(timeout=5)
        return [_metric(self.name)]

    def disconnect(self):
        self.disconnected += 1


class FakeRegistry:
    def __init__(self, adapters):
        self._adapters = adapters

    def names(self):
        return list(self._adapters)

    def items(self):
        return list(self._adapters.items())

    def get_config(self, name):
        return {"db_type": "oracle", "host": f"{name}-host", "db_name": f"{name}_db",
                "credentials": {"user": "u", "password": SECRET}}


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def evaluate(self, metrics):
        self.calls.append(list(metrics))


class FakeRetention:
    def __init__(self):
        self.conn = None

    def run(self, conn):
        self.conn = conn
        return {"ok": True}


class FakeConn:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeScheduler:
    def __init__(self):
        self.jobs = []
        self.started = False

    def add_job(self, func, *args, **kwargs):
        self.jobs.append((func, args, kwargs))

    def start(self):
        self.started = True

    def shutdown(self, wait=False):
        pass


def _engine(adapters, **kw):
    eng = CollectorEngine(
        registry=FakeRegistry(adapters), notifier=FakeNotifier(),
        retention=FakeRetention(), db_config={"host": "x", "db_name": "y"}, **kw,
    )
    persisted = []
    eng._persist = lambda metrics: persisted.append(list(metrics)) or True
    eng.persisted = persisted
    return eng


def test_failed_health_check_yields_error_metric_and_keeps_other_adapters():
    eng = _engine({"bad": FakeAdapter("bad", healthy=False), "good": FakeAdapter("good")})
    metrics = eng._collect_all()

    errs = [m for m in metrics if m.kontrol_kodu == "FR-SYS-01"]
    assert len(errs) == 1
    e = errs[0]
    assert (e.sonuc, e.severity, e.kategori) == ("ERROR", 3, "sistem")
    assert (e.db_type, e.host, e.db_name) == ("oracle", "bad-host", "bad_db")
    assert e.kontrol_adi == "Baglanti/saglik kontrolu"
    assert "yanit yok" in e.detay

    good = [m for m in metrics if m.db_name == "good"]
    assert len(good) == 1 and good[0].sonuc == "OK"
    assert eng.persisted and eng.notifier.calls
    assert eng._last_persist_ok is True


def test_connect_error_metric_has_no_secret_and_is_truncated():
    exc = RuntimeError(f"fail host=h password={SECRET} " + "x" * 2000)
    eng = _engine({"bad": FakeAdapter("bad", connect_exc=exc)})
    (m,) = eng._collect_all()
    assert m.sonuc == "ERROR"
    assert SECRET not in m.detay
    assert len(m.detay) <= 500


def test_missing_db_type_falls_back_to_generic_and_truncates(monkeypatch):
    eng = _engine({"bad": FakeAdapter("bad", connect_exc=RuntimeError("boom"))})
    long = "h" * 400
    monkeypatch.setattr(
        eng.registry, "get_config",
        lambda name: {"adapter": "adapters.oracle_adapter.OracleAdapter.Very.Long.Path",
                      "host": long, "db_name": long},
    )
    (m,) = eng._collect_all()
    assert m.db_type == "generic"
    assert len(m.host) == 255 and len(m.db_name) == 255
    MetricSchema.model_validate(m.model_dump())    # doğrulamayı geçer


def test_lock_released_after_exception():
    eng = _engine({"bad": FakeAdapter("bad", connect_exc=RuntimeError("boom"))})
    eng._collect_all()
    assert not eng._collect_lock.locked()
    assert len(eng._collect_all()) == 1            # ikinci tur çalışır, atlanmaz

    def explode(metrics):
        raise RuntimeError("beklenmedik")

    eng.notifier.evaluate = explode
    with pytest.raises(RuntimeError):
        eng._collect_all()
    assert not eng._collect_lock.locked()
    eng.notifier.evaluate = lambda metrics: None
    assert len(eng._collect_all()) == 1


def test_open_circuit_yields_error_metric():
    eng = _engine({"a": FakeAdapter("a", healthy=False)}, circuit_failure_threshold=1)
    eng._collect_all()                     # devreyi açar
    assert eng._circuits["a"].is_open
    metrics = eng._collect_all()           # devre açık turu
    assert len(metrics) == 1
    assert metrics[0].sonuc == "ERROR" and metrics[0].kontrol_kodu == "FR-SYS-01"
    assert "Devre açık" in metrics[0].detay


def test_persist_failure_is_recorded_but_notifier_still_runs():
    eng = _engine({"a": FakeAdapter("a")})
    eng._persist = lambda metrics: False
    eng._collect_all()
    assert eng._last_persist_ok is False
    assert eng.get_last_persist_ok() is False
    assert len(eng.notifier.calls) == 1


def test_concurrent_collect_is_skipped_and_collect_now_raises_busy():
    release, entered = threading.Event(), threading.Event()
    eng = _engine({"a": FakeAdapter("a", block=release, entered=entered)})
    t = threading.Thread(target=eng._collect_all)
    t.start()
    try:
        assert entered.wait(timeout=5)
        assert eng._collect_all() == []            # scheduler turu: atlanır
        with pytest.raises(CollectionBusy):
            eng.collect_now()
    finally:
        release.set()
        t.join(timeout=5)
    assert len(eng.persisted) == 1                 # yalnızca ilk tur yazdı
    assert len(eng.collect_now()) == 1             # kilit serbest kaldı


def test_collect_endpoint_returns_409_when_busy(monkeypatch):
    class BusyEngine:
        def collect_now(self):
            raise CollectionBusy("x")

    monkeypatch.setattr(main, "engine", BusyEngine())
    resp = TestClient(main.app).get("/collect")
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Toplama zaten çalışıyor"}


def test_health_degraded_when_all_circuits_open(monkeypatch):
    eng = _engine({"a": FakeAdapter("a"), "b": FakeAdapter("b")}, circuit_failure_threshold=1)
    for cb in eng._circuits.values():
        cb.record_failure()
    monkeypatch.setattr(main, "engine", eng)
    body = TestClient(main.app).get("/health").json()
    assert body["status"] == "degraded"
    assert set(body["circuits"]) == {"a", "b"}
    assert body["persist_ok"] is None


def test_health_ok_when_some_circuit_closed(monkeypatch):
    eng = _engine({"a": FakeAdapter("a"), "b": FakeAdapter("b")}, circuit_failure_threshold=1)
    eng._circuits["a"].record_failure()
    monkeypatch.setattr(main, "engine", eng)
    assert TestClient(main.app).get("/health").json()["status"] == "ok"


def test_run_retention_closes_connection(monkeypatch):
    eng = _engine({})
    conn = FakeConn()
    monkeypatch.setattr(eng, "_open_connection", lambda: conn)
    eng._run_retention()
    assert eng.retention.conn is conn and conn.closed is True


def test_run_retention_closes_connection_even_on_error(monkeypatch):
    eng = _engine({})
    conn = FakeConn()

    def boom(c):
        raise RuntimeError("x")

    eng.retention.run = boom
    monkeypatch.setattr(eng, "_open_connection", lambda: conn)
    eng._run_retention()
    assert conn.closed is True


def test_start_schedules_startup_collection():
    eng = _engine({})
    eng._scheduler = FakeScheduler()
    eng.start()
    ids = [kw.get("id") for _, _, kw in eng._scheduler.jobs]
    assert ids == ["collect_all", "retention", "collect_startup"]
    func, args, kw = eng._scheduler.jobs[-1]
    assert func == eng._collect_all and args == ("date",) and "run_date" in kw
    assert eng._scheduler.started
