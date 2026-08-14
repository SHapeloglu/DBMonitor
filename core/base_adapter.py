"""
core/base_adapter.py
====================
Tüm DB adapter'larının implement etmesi gereken Abstract Base Class.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from core.metric_schema import MetricSchema

logger = logging.getLogger(__name__)


class AdapterError(Exception):
    def __init__(self, message: str, db_type: str = "", host: str = "", cause: Optional[Exception] = None):
        super().__init__(message)
        self.db_type = db_type
        self.host    = host
        self.cause   = cause

    def __str__(self) -> str:
        base = super().__str__()
        parts = [base]
        if self.db_type: parts.append(f"db_type={self.db_type}")
        if self.host:    parts.append(f"host={self.host}")
        if self.cause:   parts.append(f"cause={self.cause!r}")
        return " | ".join(parts)


class ConnectionError(AdapterError):
    pass

class AuthenticationError(AdapterError):
    pass

class QueryError(AdapterError):
    def __init__(self, message: str, sql: str = "", **kwargs):
        super().__init__(message, **kwargs)
        self.sql = sql

class TimeoutError(AdapterError):
    def __init__(self, message: str, timeout_s: float = 0, **kwargs):
        super().__init__(message, **kwargs)
        self.timeout_s = timeout_s

class ConfigurationError(AdapterError):
    pass


@dataclass
class HealthResult:
    is_healthy:  bool
    latency_ms:  float
    message:     Optional[str]   = None
    checked_at:  datetime        = field(default_factory=datetime.utcnow)
    extra:       dict[str, Any]  = field(default_factory=dict)

    def __str__(self) -> str:
        status = "OK" if self.is_healthy else "FAIL"
        msg    = f" — {self.message}" if self.message else ""
        return f"HealthResult[{status}] latency={self.latency_ms:.1f}ms{msg}"


@dataclass
class DBMetadata:
    db_type:         str
    host:            str
    port:            int
    db_name:         str
    version:         str
    adapter_version: str
    extra:           dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "db_type":         self.db_type,
            "host":            self.host,
            "port":            self.port,
            "db_name":         self.db_name,
            "version":         self.version,
            "adapter_version": self.adapter_version,
            **self.extra,
        }


class DBAdapter(ABC):

    ADAPTER_VERSION: str = "1.0.0"

    def __init__(self, config: dict):
        self.config            = config
        self._connection: Any  = None
        self._connected: bool  = False
        self._metadata: Optional[DBMetadata] = None

        self.host              = config.get("host", "")
        self.port              = config.get("port", 0)
        self.db_name           = config.get("db_name", "")
        self.db_type           = config.get("db_type", self._infer_db_type())
        self.connect_timeout_s = config.get("connect_timeout_s", 10)
        self.query_timeout_s   = config.get("query_timeout_s", 30)

        logger.debug("Adapter oluşturuldu: %s host=%s db=%s",
                     self.__class__.__name__, self.host, self.db_name)

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def health_check(self) -> HealthResult: ...

    @abstractmethod
    def get_metadata(self) -> DBMetadata: ...

    @abstractmethod
    def collect_metrics(self) -> list[MetricSchema]: ...

    def supports_check(self, kontrol_kodu: str) -> bool:
        return True

    def on_connect_error(self, error: AdapterError) -> None:
        logger.error("Bağlantı hatası [%s] %s:%s — %s",
                     self.__class__.__name__, self.host, self.port, error)

    def _infer_db_type(self) -> str:
        name = self.__class__.__name__.lower()
        for db in ("oracle", "db2", "mysql", "mariadb", "mongodb",
                   "mssql", "postgresql", "teradata"):
            if db in name:
                return db
        return "generic"

    def _timed_query(self, fn, *args, label: str = "query") -> tuple[Any, float]:
        t0 = time.perf_counter()
        result = fn(*args)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug("%s tamamlandı: %.1f ms", label, elapsed_ms)
        return result, elapsed_ms

    def _safe_collect(self, check_fn, kontrol_kodu: str) -> list[MetricSchema]:
        try:
            return check_fn()
        except Exception as exc:
            logger.exception("Kontrol hatası: %s — %s", kontrol_kodu, exc)
            from core.metric_schema import Sonuc, Kategori
            kategori = self._kategori_from_kod(kontrol_kodu)
            return [MetricSchema(
                db_type      = self.db_type,
                host         = self.host,
                db_name      = self.db_name,
                kategori     = kategori,
                kontrol_kodu = kontrol_kodu,
                kontrol_adi  = f"{kontrol_kodu} (hata)",
                sonuc        = Sonuc.ERROR,
                severity     = 3,
                detay        = f"Kontrol çalıştırılamadı: {exc}",
            )]

    @staticmethod
    def _kategori_from_kod(kontrol_kodu: str) -> str:
        mapping = {
            "COST": "maliyet", "DQ": "kalite", "PIPE": "pipeline",
            "USER": "kullanici", "SEC": "guvenlik", "RPT": "sistem",
        }
        parts = kontrol_kodu.upper().split("-")
        if len(parts) >= 2:
            return mapping.get(parts[1], "sistem")
        return "sistem"

    def __enter__(self) -> "DBAdapter":
        self.connect()
        self._connected = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.disconnect()
        self._connected = False
        return False

    def __repr__(self) -> str:
        status = "connected" if self._connected else "disconnected"
        return f"{self.__class__.__name__}(host={self.host!r}, db={self.db_name!r}, status={status})"
