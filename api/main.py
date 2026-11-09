"""
api/main.py
===========
FastAPI uygulaması — /metrics, /health, /logs endpoint'leri.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from datetime import datetime
from typing import Literal, Optional

import psycopg2
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse

from core.adapter_registry import AdapterRegistry
from core.collector_engine import CollectorEngine
from core.metric_schema import metrics_to_prometheus_block, summary_by_kategori
from core.notifier import Notifier
from core.retention_manager import RetentionManager
from api.logs import LogPage, LogItem, fetch_logs, to_utc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB config — env'den oku
# ---------------------------------------------------------------------------
DB_CONFIG = {
    "host":    os.getenv("DB_HOST", "localhost"),
    "port":    int(os.getenv("DB_PORT", "5432")),
    "db_name": os.getenv("DB_NAME", "dwhmonitor"),
    "db_type": "postgresql",
    "credentials": {
        "user":     os.getenv("DB_USER", "dquser"),
        "password": os.getenv("DB_PASS", "dqpass"),
    },
}

# ---------------------------------------------------------------------------
# Uygulama başlangıç / bitiş
# ---------------------------------------------------------------------------
engine: CollectorEngine | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine

    # Registry yükle
    registry = AdapterRegistry("config/databases.yaml")
    registry.load_all()

    # Modüller
    notifier  = Notifier("config/notifications.yaml")
    retention = RetentionManager("config/retention.yaml", db_config=DB_CONFIG)

    # Engine başlat
    engine = CollectorEngine(
        registry       = registry,
        notifier       = notifier,
        retention      = retention,
        db_config      = DB_CONFIG,
        collect_cron   = os.getenv("COLLECT_CRON", "0 * * * *"),
        retention_cron = os.getenv("RETENTION_CRON", "0 1 1 * *"),
    )
    engine.start()
    logger.info("CollectorEngine başlatıldı.")

    yield

    engine.stop()
    logger.info("CollectorEngine durduruldu.")


app = FastAPI(
    title       = "DWH Health Monitor",
    description = "Çok veritabanlı DWH sağlık izleme sistemi",
    version     = "1.0.0",
    lifespan    = lifespan,
)

# ---------------------------------------------------------------------------
# Endpoint'ler
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    """Servis ve tüm adapter'ların anlık durumu."""
    if engine is None:
        return {"status": "starting"}
    circuits = engine.get_circuit_status()
    return {
        "status":   "ok",
        "circuits": circuits,
    }


@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    """Prometheus exposition format — Grafana / Prometheus scrape eder."""
    if engine is None:
        return "# DWH Monitor henüz hazır değil\n"
    last = engine.get_last_metrics()
    return metrics_to_prometheus_block(last)


@app.get("/collect")
def collect_now():
    """Manuel koleksiyon tetikle — test ve preflight için."""
    if engine is None:
        return {"error": "Engine hazır değil"}
    metrics = engine.collect_now()
    return {
        "collected": len(metrics),
        "summary":   summary_by_kategori(metrics),
    }


@app.get("/logs/summary")
def logs_summary():
    """Son koleksiyonun kategori bazlı özeti."""
    if engine is None:
        return {}
    last = engine.get_last_metrics()
    return summary_by_kategori(last)


DB_UNAVAILABLE_DETAIL = "Veritabanı şu anda kullanılamıyor"


@app.get("/logs", response_model=LogPage)
def logs(
    db_name:      Optional[str]      = Query(None, min_length=1, max_length=255),
    kontrol_kodu: Optional[str]      = Query(None, min_length=1, max_length=30),
    sonuc:        Optional[Literal["OK", "WARNING", "ERROR"]] = Query(None),
    severity:     Optional[int]      = Query(None, ge=1, le=3),
    since:        Optional[datetime] = Query(None, description="ISO datetime; zaman dilimi yoksa UTC"),
    until:        Optional[datetime] = Query(None, description="ISO datetime; zaman dilimi yoksa UTC"),
    limit:        int                = Query(100, ge=1, le=1000),
    offset:       int                = Query(0, ge=0),
):
    """dwh_health_log kayıtlarını filtreli ve sayfalı olarak döner (kontrol_tarihi DESC)."""
    since_utc = to_utc(since)
    until_utc = to_utc(until)
    if since_utc and until_utc and since_utc > until_utc:
        raise HTTPException(status_code=422, detail="since, until değerinden büyük olamaz")

    if engine is None:
        raise HTTPException(status_code=503, detail=DB_UNAVAILABLE_DETAIL)

    filters = {
        "db_name":      db_name,
        "kontrol_kodu": kontrol_kodu,
        "sonuc":        sonuc,
        "severity":     severity,
        "since":        since_utc,
        "until":        until_utc,
    }
    try:
        rows = fetch_logs(engine._open_connection, filters, limit, offset)
    except psycopg2.Error as exc:
        # Yalnızca hata sınıfı loglanır; bağlantı bilgisi/parola/traceback yanıta girmez.
        logger.error("GET /logs veritabanı hatası: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail=DB_UNAVAILABLE_DETAIL) from None

    items = [LogItem(**row) for row in rows]
    return LogPage(items=items, limit=limit, offset=offset, count=len(items))


@app.get("/adapters")
def adapters():
    """Kayıtlı adapter'lar ve circuit breaker durumları."""
    if engine is None:
        return []
    return engine.get_circuit_status()
