"""
core/collector_engine.py
========================
Tüm adapter'lardan periyodik metrik toplar.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.extras
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from core.adapter_registry import AdapterRegistry
from core.metric_schema import MetricSchema, metrics_to_log_rows, summary_by_kategori
from core.notifier import Notifier
from core.retention_manager import RetentionManager

logger = logging.getLogger(__name__)


class CircuitBreaker:
    CLOSED    = "CLOSED"
    OPEN      = "OPEN"
    HALF_OPEN = "HALF_OPEN"

    def __init__(self, name: str, failure_threshold: int = 3, cooldown_s: int = 300):
        self.name              = name
        self.failure_threshold = failure_threshold
        self.cooldown_s        = cooldown_s
        self._state            = self.CLOSED
        self._failure_count    = 0
        self._opened_at: Optional[datetime] = None
        self._lock             = threading.Lock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self._state == self.OPEN:
                elapsed = (datetime.now(timezone.utc) - self._opened_at).total_seconds()
                if elapsed >= self.cooldown_s:
                    self._state = self.HALF_OPEN
                    return False
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._state         = self.CLOSED
            self._opened_at     = None

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._state     = self.OPEN
                self._opened_at = datetime.now(timezone.utc)
                logger.error("Circuit OPEN: %s (%d hata)", self.name, self._failure_count)

    def __repr__(self) -> str:
        return f"CircuitBreaker({self.name}, state={self._state}, failures={self._failure_count})"


class CollectorEngine:

    def __init__(
        self,
        registry:        AdapterRegistry,
        notifier:        Notifier,
        retention:       RetentionManager,
        db_config:       dict,
        collect_cron:    str = "0 * * * *",
        retention_cron:  str = "0 1 1 * *",
        circuit_failure_threshold: int = 3,
        circuit_cooldown_s:        int = 300,
    ):
        self.registry       = registry
        self.notifier       = notifier
        self.retention      = retention
        self.db_config      = db_config
        self.collect_cron   = collect_cron
        self.retention_cron = retention_cron

        self._scheduler     = BackgroundScheduler(timezone="Europe/Istanbul")
        self._circuits:     dict[str, CircuitBreaker] = {}
        self._last_metrics: list[MetricSchema]        = []
        self._lock          = threading.Lock()

        for name in registry.names():
            self._circuits[name] = CircuitBreaker(
                name,
                failure_threshold=circuit_failure_threshold,
                cooldown_s=circuit_cooldown_s,
            )

    def start(self) -> None:
        self._scheduler.add_job(
            self._collect_all,
            CronTrigger.from_crontab(self.collect_cron),
            id="collect_all", max_instances=1,
            misfire_grace_time=300, replace_existing=True,
        )
        self._scheduler.add_job(
            self._run_retention,
            CronTrigger.from_crontab(self.retention_cron),
            id="retention", max_instances=1,
            misfire_grace_time=3600, replace_existing=True,
        )
        self._scheduler.start()
        logger.info("CollectorEngine başladı. collect=%s retention=%s",
                    self.collect_cron, self.retention_cron)

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("CollectorEngine durduruldu.")

    def collect_now(self) -> list[MetricSchema]:
        return self._collect_all()

    def _collect_all(self) -> list[MetricSchema]:
        logger.info("Koleksiyon başladı: %s", datetime.now(timezone.utc).isoformat())
        all_metrics: list[MetricSchema] = []

        for name, adapter in self.registry.items():
            circuit = self._circuits.get(name)

            if circuit and circuit.is_open:
                logger.warning("Circuit açık, atlanıyor: %s", name)
                continue

            try:
                # Her koleksiyonda bağlantı aç → topla → kapat
                adapter.connect()
                try:
                    health = adapter.health_check()
                    if not health.is_healthy:
                        logger.warning("Sağlık kontrolü başarısız: %s — %s", name, health.message)
                        if circuit:
                            circuit.record_failure()
                        continue

                    metrics = adapter.collect_metrics()
                    all_metrics.extend(metrics)

                    if circuit:
                        circuit.record_success()

                    logger.info("Koleksiyon tamamlandı: %s → %d metrik (latency=%.1fms)",
                                name, len(metrics), health.latency_ms)
                finally:
                    adapter.disconnect()

            except Exception as exc:
                logger.error("Koleksiyon hatası [%s]: %s", name, exc)
                if circuit:
                    circuit.record_failure()

        if all_metrics:
            self._persist(all_metrics)
            self.notifier.evaluate(all_metrics)

        with self._lock:
            self._last_metrics = all_metrics

        logger.info("Koleksiyon bitti: toplam %d metrik.", len(all_metrics))
        return all_metrics

    def _persist(self, metrics: list[MetricSchema]) -> None:
        rows = metrics_to_log_rows(metrics)
        if not rows:
            return
        try:
            conn = self._open_connection()
            try:
                with conn.cursor() as cur:
                    psycopg2.extras.execute_batch(
                        cur,
                        """
                        INSERT INTO monitor.dwh_health_log
                            (kontrol_tarihi, db_type, host, db_name, kategori,
                             kontrol_kodu, kontrol_adi, sonuc, severity,
                             etkilenen_obje, etkilenen_sayi, detay)
                        VALUES
                            (%(kontrol_tarihi)s, %(db_type)s, %(host)s, %(db_name)s,
                             %(kategori)s, %(kontrol_kodu)s, %(kontrol_adi)s,
                             %(sonuc)s, %(severity)s,
                             %(etkilenen_obje)s, %(etkilenen_sayi)s, %(detay)s)
                        """,
                        rows, page_size=500,
                    )
                conn.commit()
                logger.info("%d satır dwh_health_log'a yazıldı.", len(rows))
            finally:
                conn.close()
        except Exception as exc:
            logger.error("dwh_health_log yazma hatası: %s", exc)

    def _run_retention(self) -> None:
        logger.info("RetentionManager çalışıyor...")
        try:
            conn   = self._open_connection()
            result = self.retention.run(conn)
            logger.info("Retention tamamlandı: %s", result)
        except Exception as exc:
            logger.error("Retention hatası: %s", exc)

    def get_last_metrics(self) -> list[MetricSchema]:
        with self._lock:
            return list(self._last_metrics)

    def get_circuit_status(self) -> dict:
        return {
            name: {"state": cb._state, "failures": cb._failure_count}
            for name, cb in self._circuits.items()
        }

    def _open_connection(self):
        creds = self.db_config.get("credentials", {})
        return psycopg2.connect(
            host            = self.db_config["host"],
            port            = self.db_config.get("port", 5432),
            dbname          = self.db_config["db_name"],
            user            = creds.get("user", "dquser"),
            password        = creds.get("password", ""),
            connect_timeout = self.db_config.get("connect_timeout_s", 10),
        )
