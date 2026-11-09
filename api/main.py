"""
api/main.py
===========
FastAPI uygulaması — /metrics, /health, /logs endpoint'leri.
Uygulama açılırken (lifespan) ayarları okur, adapter'ları yükler ve CollectorEngine'i başlatır.
Endpoint'ler CollectorEngine'in son sonuçlarını okur; toplama işini kendileri yapmaz (/collect hariç, o da elle tetikler).
Çalıştırma: uvicorn api.main:app (proje kökünden).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.responses import PlainTextResponse

from core.adapter_registry import AdapterRegistry
from core.collector_engine import CollectorEngine
from core.metric_schema import metrics_to_prometheus_block, summary_by_kategori
from core.notifier import Notifier
from core.retention_manager import RetentionManager

# Tüm logger'lar için temel ayar. Bağlantı durumları ve hatalar bu seviyede konsola yazılır.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB config — env'den oku
# ---------------------------------------------------------------------------
def _required_env(name: str) -> str:
    """Ortam değişkenini okur; yoksa veya boşsa adını belirterek hata verir. Kodda varsayılan şifre yoktur."""
    value = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"Zorunlu ortam değişkeni eksik: {name}")
    return value

# Log veritabanı ayarları ortam değişkenlerinden okunur. Host/port/isim/kullanıcı için varsayılanlar yerel geliştirme içindir.
# DB_PASS zorunludur; yoksa uygulama içe aktarılırken açık bir hatayla durur.
DB_CONFIG = {
    "host":    os.getenv("DB_HOST", "localhost"),
    "port":    int(os.getenv("DB_PORT", "5432")),
    "db_name": os.getenv("DB_NAME", "dwhmonitor"),
    "db_type": "postgresql",
    "credentials": {
        "user":     os.getenv("DB_USER", "dquser"),
        "password": _required_env("DB_PASS"),
    },
}

# ---------------------------------------------------------------------------
# Uygulama başlangıç / bitiş
# ---------------------------------------------------------------------------
# Uygulama açıkken dolu olan genel (global) değişken. Endpoint'ler buna bakar; None ise uygulama henüz başlamamıştır.
engine: CollectorEngine | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI başlangıç ve bitiş yönetimi. yield'den önce: DB ayarlarını ve yapılandırma dosyalarını okur, adapter'ları yükler ve CollectorEngine'i başlatır. yield'den sonra: zamanlayıcıyı durdurur. Uygulama açılırken ve kapanırken bir kez çalışır."""
    global engine

    # Registry yükle
    # Adapter'lar config/databases.yaml'dan oluşturulur. load_all bağlantı açmaz, sadece nesneleri hazırlar.
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
        # Toplama zamanı. Varsayılan her saat başıdır. Cron biçimi: dakika saat gün ay haftanın_günü.
        collect_cron   = os.getenv("COLLECT_CRON", "0 * * * *"),
        retention_cron = os.getenv("RETENTION_CRON", "0 1 1 * *"),
    )
    engine.start()
    logger.info("CollectorEngine başlatıldı.")

    yield

    # Uygulama kapanırken zamanlayıcı durdurulur. Bu kod yield'den sonra, kapanış sırasında çalışır.
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


@app.get("/adapters")
def adapters():
    """Kayıtlı adapter'lar ve circuit breaker durumları."""
    if engine is None:
        return []
    return engine.get_circuit_status()
