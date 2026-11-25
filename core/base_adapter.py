"""
core/base_adapter.py
====================
Tüm DB adapter'larının implement etmesi gereken Abstract Base Class (soyut taban sınıf).
Bu dosya "ortak sözleşmeyi" tanımlar: hata sınıfları (AdapterError ailesi), sağlık sonucu (HealthResult),
veritabanı bilgisi (DBMetadata) ve DBAdapter taban sınıfı.
adapters/ altındaki her adapter bu sınıfı miras alır; adapter_registry ve collector_engine bu arayüzü kullanır.
Yeni bir DB türü eklerken connect, disconnect, health_check, get_metadata ve collect_metrics metotlarını doldurmak yeterlidir.
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
    """Tüm adapter hatalarının taban sınıfı. Hatayı yakalayan kod tek bir except AdapterError ile tüm adapter hatalarını yakalayabilir."""
    def __init__(self, message: str, db_type: str = "", host: str = "", cause: Optional[Exception] = None):
        """Hata nesnesini oluşturur. db_type ve host, logda hangi veritabanında sorun olduğunu göstermek için saklanır. cause: alttaki asıl hata varsa (örn. sürücü hatası) onu tutar."""
        super().__init__(message)
        self.db_type = db_type
        self.host    = host
        self.cause   = cause

    def __str__(self) -> str:
        """Hata mesajını, varsa db_type, host ve cause bilgileriyle birlikte tek satır olarak döner."""
        base = super().__str__()
        parts = [base]
        if self.db_type: parts.append(f"db_type={self.db_type}")
        if self.host:    parts.append(f"host={self.host}")
        if self.cause:   parts.append(f"cause={self.cause!r}")
        return " | ".join(parts)


# DİKKAT: Bu isimler Python'ın yerleşik ConnectionError ve TimeoutError adlarını gölgeler.
# Bu dosyadan içe aktarırken adları açıkça yazın (from core.base_adapter import ConnectionError) ve karışıklık olmaması için dikkat edin.
class ConnectionError(AdapterError):
    """Veritabanına bağlanılamadığında fırlatılır (ağ kopuk, yanlış host/port, servis kapalı gibi durumlar)."""
    pass

class AuthenticationError(AdapterError):
    """Kullanıcı adı veya şifre yanlış ya da yetki yoksa fırlatılır. Mesajda şifre yazılmamalıdır."""
    pass

class QueryError(AdapterError):
    """Bir SQL sorgusu çalışırken hata olduğunda fırlatılır. Hangi sorgudan geldiğini görmek için sql alanı tutulur."""
    def __init__(self, message: str, sql: str = "", **kwargs):
        """sql: hatayı veren SQL metni (log ve hata ayıklama için). Diğer parametreler AdapterError'a aktarılır."""
        super().__init__(message, **kwargs)
        self.sql = sql

class TimeoutError(AdapterError):
    """Bağlantı veya sorgu zaman aşımına uğradığında fırlatılır. Adı Python'ın yerleşik TimeoutError'u ile aynıdır."""
    def __init__(self, message: str, timeout_s: float = 0, **kwargs):
        """timeout_s: aşılan süre limiti (saniye). Diğer parametreler AdapterError'a aktarılır."""
        super().__init__(message, **kwargs)
        self.timeout_s = timeout_s

class ConfigurationError(AdapterError):
    """databases.yaml'daki ayarlar eksik ya da hatalı olduğunda fırlatılır. Bağlantı denenmeden önce hatayı yakalamak için kullanılır."""
    pass


@dataclass
class HealthResult:
    """Bir sağlık kontrolünün sonucu. is_healthy: veritabanı yanıt verdiyse True. latency_ms: yanıt süresi (milisaniye). message: açıklama (opsiyonel). checked_at: kontrol zamanı (UTC). extra: ek bilgiler için sözlük."""
    is_healthy:  bool
    latency_ms:  float
    message:     Optional[str]   = None
    # DİKKAT: datetime.utcnow() UTC zamanını döner ama saat dilimi bilgisi taşımaz; Python 3.12 ve sonrasında kullanımdan kaldırılmıştır.
    checked_at:  datetime        = field(default_factory=datetime.utcnow)
    extra:       dict[str, Any]  = field(default_factory=dict)

    def __str__(self) -> str:
        """Log'da okunaklı olsun diye tek satırlık özet döner. Örnek: HealthResult[OK] latency=12.3ms"""
        status = "OK" if self.is_healthy else "FAIL"
        msg    = f" — {self.message}" if self.message else ""
        return f"HealthResult[{status}] latency={self.latency_ms:.1f}ms{msg}"


@dataclass
class DBMetadata:
    """Veritabanı hakkında temel bilgiler: tür, host, port, veritabanı adı ve sürüm. Ek bilgiler extra sözlüğünde tutulur."""
    db_type:         str
    host:            str
    port:            int
    db_name:         str
    version:         str
    adapter_version: str
    extra:           dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Metadata'yı düz bir sözlüğe çevirir (JSON veya log çıktısı için). extra içindeki alanlar ana sözlüğe eklenir."""
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

    """Tüm adapter'ların taban sınıfı. Alt sınıf connect, disconnect, health_check, get_metadata ve collect_metrics metotlarını yazmak zorundadır (abstractmethod); yazmazsa nesne oluşturulamaz. config: databases.yaml'daki bu veritabanının ayar sözlüğüdür."""
    # Adapter kodunun sürümü. Metadata'da raporlanır; adapter kodu değiştiğinde artırılmalıdır.
    ADAPTER_VERSION: str = "1.0.0"

    def __init__(self, config: dict):
        """Ayar sözlüğünden host, port, db_name ve zaman aşımı değerlerini okur. Bu aşamada veritabanına bağlanmaz; bağlantı connect() ile açılır. db_type verilmezse sınıf adından tahmin edilir."""
        self.config            = config
        self._connection: Any  = None
        self._connected: bool  = False
        self._metadata: Optional[DBMetadata] = None

        self.host              = config.get("host", "")
        self.port              = config.get("port", 0)
        self.db_name           = config.get("db_name", "")
        self.db_type           = config.get("db_type", self._infer_db_type())
        # Zaman aşımı değerleri (saniye). Bağlantı için 10 sn, tek sorgu için 30 sn bekleriz; sunucu takılırsa işlemin sonsuza kadar sürmemesi için kullanılır.
        self.connect_timeout_s = config.get("connect_timeout_s", 10)
        self.query_timeout_s   = config.get("query_timeout_s", 30)

        logger.debug("Adapter oluşturuldu: %s host=%s db=%s",
                     self.__class__.__name__, self.host, self.db_name)

    @abstractmethod
    def connect(self) -> None:
        """Veritabanına bağlantı açar. Hata olursa AdapterError ailesinden uygun bir hata fırlatmalıdır (ConnectionError, AuthenticationError vb.). Alt sınıf mutlaka doldurmalıdır."""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Açık bağlantıyı kapatır. Bağlantı hiç açılmamışsa bile hata vermeden çalışmalıdır, çünkü __exit__ bunu her durumda çağırır."""
        ...

    @abstractmethod
    def health_check(self) -> HealthResult:
        """Veritabanının ayakta olup olmadığını hızlıca kontrol eder ve HealthResult döner. Alt sınıf genelde küçük bir sorgu atıp yanıt süresini ölçer."""
        ...

    @abstractmethod
    def get_metadata(self) -> DBMetadata:
        """Veritabanı türü, sürümü ve adı gibi bilgileri DBMetadata olarak döner."""
        ...

    @abstractmethod
    def collect_metrics(self) -> list[MetricSchema]:
        """Tüm sağlık kontrollerini çalıştırıp MetricSchema listesi döner. collector_engine bu metodu çağırır."""
        ...

    def supports_check(self, kontrol_kodu: str) -> bool:
        """Bu adapter belirli bir kontrol kodunu (örn. FR-DQ-01) destekliyor mu diye bakar. Varsayılan True'dur. Desteklemeyen veritabanı için alt sınıf False döndürebilir. Projede şu an çağrılmıyor."""
        return True

    def on_connect_error(self, error: AdapterError) -> None:
        """Bağlantı hatasını logda adapter adı, host ve port ile birlikte gösterir. Projede şu an çağrılmıyor; ileride kullanılmak üzere hazır."""
        logger.error("Bağlantı hatası [%s] %s:%s — %s",
                     self.__class__.__name__, self.host, self.port, error)

    def _infer_db_type(self) -> str:
        """Sınıf adından veritabanı türünü tahmin eder. Örnek: MSSQLAdapter sınıfı için 'mssql' döner. Eşleşme yoksa 'generic' döner."""
        name = self.__class__.__name__.lower()
        for db in ("oracle", "db2", "mysql", "mariadb", "mongodb",
                   "mssql", "postgresql", "teradata"):
            if db in name:
                return db
        return "generic"

    def _timed_query(self, fn, *args, label: str = "query") -> tuple[Any, float]:
        """Verilen fonksiyonu çalıştırır ve süresini milisaniye olarak ölçer. Dönüş değeri (sonuç, geçen_süre_ms) çiftidir. label sadece debug logunda görünür."""
        t0 = time.perf_counter()
        result = fn(*args)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug("%s tamamlandı: %.1f ms", label, elapsed_ms)
        return result, elapsed_ms

    def _safe_collect(self, check_fn, kontrol_kodu: str) -> list[MetricSchema]:
        """Bir kontrolü güvenli biçimde çalıştırır. Kontrol hata fırlatsa bile tüm çalıştırmayı durdurmaz; bunun yerine ERROR (severity=3) içeren tek bir MetricSchema döner. Böylece bir kontrol bozulsa da diğerleri çalışmaya devam eder."""
        try:
            return check_fn()
        except Exception as exc:
            logger.exception("Kontrol hatası: %s — %s", kontrol_kodu, exc)
            from core.metric_schema import Sonuc, Kategori
            kategori = self._kategori_from_kod(kontrol_kodu)
            # Kontrol kendisi çöktüyse hatayı gözden kaçırmamak için en yüksek önem (3) ile ERROR olarak raporlanır.
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
        """Kontrol kodundan kategoriyi bulur. Örnek: FR-COST-01 için 'maliyet' döner. Tanınmayan kodlar için 'sistem' döner."""
        mapping = {
            "COST": "maliyet", "DQ": "kalite", "PIPE": "pipeline",
            "USER": "kullanici", "SEC": "guvenlik", "RPT": "sistem",
        }
        # Kontrol kodu FR-<KATEGORI>-<no> biçimindedir. Örnek: 'FR-DQ-03' -> ['FR', 'DQ', '03'] -> ortadaki 'DQ' kategoriyi verir.
        parts = kontrol_kodu.upper().split("-")
        if len(parts) >= 2:
            return mapping.get(parts[1], "sistem")
        return "sistem"

    def __enter__(self) -> "DBAdapter":
        """'with adapter:' bloğunun başında bağlantıyı açar. Bağlantı kurulamazsa hata with bloğuna fırlatılır."""
        self.connect()
        self._connected = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """with bloğu bittiğinde bağlantıyı kapatır (hata olsa da olmasa da). False döner; yani bloktaki bir hata yutulmaz, yeniden fırlatılır."""
        self.disconnect()
        self._connected = False
        return False

    def __repr__(self) -> str:
        """Hata ayıklarken okunaklı bilgi verir: sınıf adı, host, veritabanı adı ve bağlantı durumu."""
        status = "connected" if self._connected else "disconnected"
        return f"{self.__class__.__name__}(host={self.host!r}, db={self.db_name!r}, status={status})"
