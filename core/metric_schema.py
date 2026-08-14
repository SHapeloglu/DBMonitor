"""
core/metric_schema.py
=====================
DWH sağlık izleme sisteminin merkezi veri modeli.

Tüm adapter'lar MetricSchema döner.
Collector Engine, Notifier, RetentionManager sadece bu modeli bilir.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class Sonuc(str, Enum):
    OK      = "OK"
    WARNING = "WARNING"
    ERROR   = "ERROR"


class Kategori(str, Enum):
    MALIYET   = "maliyet"
    KALITE    = "kalite"
    PIPELINE  = "pipeline"
    KULLANICI = "kullanici"
    GUVENLIK  = "guvenlik"
    SISTEM    = "sistem"


class DBTip(str, Enum):
    ORACLE     = "oracle"
    DB2        = "db2"
    MYSQL      = "mysql"
    MARIADB    = "mariadb"
    MONGODB    = "mongodb"
    MSSQL      = "mssql"
    POSTGRESQL = "postgresql"
    TERADATA   = "teradata"
    GENERIC    = "generic"


_KONTROL_KODU_RE = re.compile(
    r"^FR-[A-Z]{2,8}(-[A-Z]{2,8})?-\d{2,4}$"
)


class MetricSchema(BaseModel):
    db_type:  str = Field(..., description="oracle | db2 | mysql | mariadb | mongodb | mssql | postgresql | teradata | generic")
    host:     str = Field(..., min_length=1, max_length=255)
    db_name:  str = Field(..., min_length=1, max_length=255)
    ts: datetime = Field(default_factory=datetime.utcnow)
    kategori:      Kategori = Field(...)
    kontrol_kodu:  str      = Field(...)
    kontrol_adi:   str      = Field(..., min_length=1, max_length=100)
    sonuc:    Sonuc = Field(...)
    severity: int   = Field(..., ge=1, le=3)
    etkilenen_obje: Optional[str] = Field(None, max_length=255)
    etkilenen_sayi: Optional[int] = Field(None, ge=0)
    detay:          Optional[str] = Field(None, max_length=2000)

    model_config = {"use_enum_values": True}

    @field_validator("kontrol_kodu")
    @classmethod
    def kontrol_kodu_format(cls, v: str) -> str:
        if not _KONTROL_KODU_RE.match(v):
            raise ValueError(f"Geçersiz kontrol_kodu formatı: '{v}'.")
        return v

    @field_validator("db_type")
    @classmethod
    def db_type_normalize(cls, v: str) -> str:
        return v.lower().strip()

    @field_validator("host")
    @classmethod
    def host_normalize(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def severity_sonuc_tutarliligi(self) -> "MetricSchema":
        if self.sonuc == Sonuc.OK.value and self.severity > 1:
            raise ValueError(f"Tutarsız veri: sonuc=OK iken severity={self.severity}.")
        return self

    def to_prometheus(self) -> str:
        def escape(s: str) -> str:
            return str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        labels = ",".join([
            f'db_type="{escape(self.db_type)}"',
            f'host="{escape(self.host)}"',
            f'db_name="{escape(self.db_name)}"',
            f'kategori="{escape(self.kategori)}"',
            f'kontrol_kodu="{escape(self.kontrol_kodu)}"',
            f'kontrol_adi="{escape(self.kontrol_adi)}"',
            f'sonuc="{escape(self.sonuc)}"',
        ])
        value = 0 if self.sonuc == Sonuc.OK.value else self.severity
        timestamp_ms = int(self.ts.timestamp() * 1000)
        return f"dwh_health_check{{{labels}}} {value} {timestamp_ms}"

    def to_log_row(self) -> dict:
        return {
            "kontrol_tarihi": self.ts,
            "db_type":        self.db_type,
            "host":           self.host,
            "db_name":        self.db_name,
            "kategori":       self.kategori,
            "kontrol_kodu":   self.kontrol_kodu,
            "kontrol_adi":    self.kontrol_adi,
            "sonuc":          self.sonuc,
            "severity":       self.severity,
            "etkilenen_obje": self.etkilenen_obje,
            "etkilenen_sayi": self.etkilenen_sayi,
            "detay":          self.detay,
        }

    @classmethod
    def from_log_row(cls, row: dict) -> "MetricSchema":
        return cls(
            db_type        = row["db_type"],
            host           = row["host"],
            db_name        = row["db_name"],
            ts             = row["kontrol_tarihi"],
            kategori       = row["kategori"],
            kontrol_kodu   = row["kontrol_kodu"],
            kontrol_adi    = row["kontrol_adi"],
            sonuc          = row["sonuc"],
            severity       = row["severity"],
            etkilenen_obje = row.get("etkilenen_obje"),
            etkilenen_sayi = row.get("etkilenen_sayi"),
            detay          = row.get("detay"),
        )

    def __repr__(self) -> str:
        return f"MetricSchema({self.db_type}/{self.db_name} | {self.kontrol_kodu} | {self.sonuc} | sev={self.severity})"


def metrics_to_prometheus_block(metrics: list[MetricSchema]) -> str:
    lines = [
        "# HELP dwh_health_check DWH saglık kontrol sonucu (0=OK, 2=WARNING, 3=ERROR)",
        "# TYPE dwh_health_check gauge",
    ]
    for m in metrics:
        lines.append(m.to_prometheus())
    return "\n".join(lines)


def metrics_to_log_rows(metrics: list[MetricSchema]) -> list[dict]:
    return [m.to_log_row() for m in metrics]


def filter_by_severity(metrics: list[MetricSchema], min_severity: int = 2) -> list[MetricSchema]:
    return [m for m in metrics if m.severity >= min_severity and m.sonuc != Sonuc.OK.value]


def summary_by_kategori(metrics: list[MetricSchema]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for m in metrics:
        cat = m.kategori
        if cat not in result:
            result[cat] = {"OK": 0, "WARNING": 0, "ERROR": 0}
        result[cat][m.sonuc] = result[cat].get(m.sonuc, 0) + 1
    return result
