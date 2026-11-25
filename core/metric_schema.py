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
    """Kontrol sonucunun durumu. OK: sorun yok. WARNING: dikkat edilmeli. ERROR: sorun var ya da kontrol hiç çalışamadı."""
    OK      = "OK"
    WARNING = "WARNING"
    ERROR   = "ERROR"


class Kategori(str, Enum):
    """Kontrolün ait olduğu iş alanı: maliyet, kalite, pipeline, kullanici, guvenlik ve sistem. Değerler küçük harfli düz metindir; Prometheus etiketinde ve log tablosunda aynen kullanılır."""
    MALIYET   = "maliyet"
    KALITE    = "kalite"
    PIPELINE  = "pipeline"
    KULLANICI = "kullanici"
    GUVENLIK  = "guvenlik"
    SISTEM    = "sistem"


class DBTip(str, Enum):
    """Bilinen veritabanı türlerinin listesi. Yeni bir DB türü eklenirse buraya da yazılmalıdır. generic, tanınmayan türler içindir."""
    ORACLE     = "oracle"
    DB2        = "db2"
    MYSQL      = "mysql"
    MARIADB    = "mariadb"
    MONGODB    = "mongodb"
    MSSQL      = "mssql"
    POSTGRESQL = "postgresql"
    TERADATA   = "teradata"
    GENERIC    = "generic"


# Kontrol kodu biçimi: FR-KATEGORI-NO (örn. FR-DQ-01). Araya kısa bir ek kod da girebilir (örn. FR-COST-XX-003). Bu biçime uymayan kodlar reddedilir.
_KONTROL_KODU_RE = re.compile(
    r"^FR-[A-Z]{2,8}(-[A-Z]{2,8})?-\d{2,4}$"
)


class MetricSchema(BaseModel):
    """Tek bir sağlık kontrolünün sonucu. Adapter'lar collect_metrics ile bu nesnelerin listesini döner. Pydantic modeli olduğu için alan tipleri ve sınırları (uzunluk, 1-3 arası önem derecesi) oluşturulurken otomatik denetlenir; hatalı veri ValidationError verir."""
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

    # Enum değerleri (Sonuc, Kategori) nesne olarak değil düz metin olarak saklanır. DİKKAT: Bu yüzden karşılaştırmalarda Sonuc.OK.value (düz metin) kullanılır.
    model_config = {"use_enum_values": True}

    @field_validator("kontrol_kodu")
    @classmethod
    def kontrol_kodu_format(cls, v: str) -> str:
        """kontrol_kodu alanının FR- ile başlayan biçime uyup uymadığını regex ile denetler. Uymazsa ValueError fırlatır."""
        if not _KONTROL_KODU_RE.match(v):
            raise ValueError(f"Geçersiz kontrol_kodu formatı: '{v}'.")
        return v

    @field_validator("db_type")
    @classmethod
    def db_type_normalize(cls, v: str) -> str:
        """DB türünü küçük harfe çevirir ve baştaki/sondaki boşlukları siler. Örnek: ' MSSQL ' değeri 'mssql' olur."""
        return v.lower().strip()

    @field_validator("host")
    @classmethod
    def host_normalize(cls, v: str) -> str:
        """Host adındaki baştaki ve sondaki boşlukları siler."""
        return v.strip()

    @model_validator(mode="after")
    def severity_sonuc_tutarliligi(self) -> "MetricSchema":
        """Sonuç ile önem derecesinin çelişmediğini denetler: sonuç OK ise önem derecesi 1 olmalıdır, aksi halde ValueError fırlatılır. Tüm alanlar doldurulduktan sonra çalışır."""
        if self.sonuc == Sonuc.OK.value and self.severity > 1:
            raise ValueError(f"Tutarsız veri: sonuc=OK iken severity={self.severity}.")
        return self

    def to_prometheus(self) -> str:
        """Bu kontrolü Prometheus metin formatında tek satıra çevirir. Değer: sonuç OK ise 0, değilse önem derecesi. Zaman damgası milisaniye olarak eklenir."""
        def escape(s: str) -> str:
            """Etiket değerindeki özel karakterleri (ters eğik çizgi, çift tırnak, yeni satır) Prometheus formatına uygun hale getirir."""
            # Prometheus etiket değerinde ters eğik çizgi, tırnak ve yeni satır özel anlam taşır; önce kaçış karakteriyle yazılmazsa metin bozulur.
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
        # Grafikte 0 'sağlıklı' anlamına gelir. Sorun varsa önem derecesi (2 veya 3) yazılır, böylece uyarı ve hata ayrı görünür.
        value = 0 if self.sonuc == Sonuc.OK.value else self.severity
        # Prometheus zaman damgasını milisaniye ister; Python'da timestamp() saniye döner, bu yüzden 1000 ile çarpılır.
        timestamp_ms = int(self.ts.timestamp() * 1000)
        return f"dwh_health_check{{{labels}}} {value} {timestamp_ms}"

    def to_log_row(self) -> dict:
        """Bu kontrolü veritabanı log tablosuna yazılacak sözlüğe çevirir. Anahtarlar tablo kolonlarıyla aynıdır; ts alanı kontrol_tarihi adıyla yazılır."""
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
        """Veritabanından okunmuş bir satır sözlüğünü tekrar MetricSchema nesnesine çevirir. Opsiyonel alanlar yoksa None kabul edilir; zorunlu bir alan eksikse KeyError verir."""
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
        """Log ve hata ayıklama için kısa özet verir: veritabanı, kontrol kodu, sonuç ve önem derecesi."""
        return f"MetricSchema({self.db_type}/{self.db_name} | {self.kontrol_kodu} | {self.sonuc} | sev={self.severity})"


def metrics_to_prometheus_block(metrics: list[MetricSchema]) -> str:
    """Birden çok kontrolü, Prometheus'un HELP ve TYPE satırlarıyla birlikte tek bir metin bloğuna çevirir. API'nin /metrics çıktısı bu fonksiyondan gelir."""
    lines = [
        "# HELP dwh_health_check DWH saglık kontrol sonucu (0=OK, 2=WARNING, 3=ERROR)",
        "# TYPE dwh_health_check gauge",
    ]
    for m in metrics:
        lines.append(m.to_prometheus())
    return "\n".join(lines)


def metrics_to_log_rows(metrics: list[MetricSchema]) -> list[dict]:
    """Kontrol listesini, her biri to_log_row sonucu olan sözlüklerin listesine çevirir."""
    return [m.to_log_row() for m in metrics]


def filter_by_severity(metrics: list[MetricSchema], min_severity: int = 2) -> list[MetricSchema]:
    """Sadece sorunlu kontrolleri süzer: sonucu OK olmayan ve önem derecesi min_severity değerine eşit ya da üstünde olanları döner."""
    return [m for m in metrics if m.severity >= min_severity and m.sonuc != Sonuc.OK.value]


def summary_by_kategori(metrics: list[MetricSchema]) -> dict[str, dict]:
    """Kontrolleri kategoriye göre sayar. Dönüş örneği: {'kalite': {'OK': 3, 'WARNING': 1, 'ERROR': 0}}. API'nin /collect ve /logs/summary yanıtları bunu kullanır."""
    result: dict[str, dict] = {}
    for m in metrics:
        cat = m.kategori
        if cat not in result:
            result[cat] = {"OK": 0, "WARNING": 0, "ERROR": 0}
        result[cat][m.sonuc] = result[cat].get(m.sonuc, 0) + 1
    return result
