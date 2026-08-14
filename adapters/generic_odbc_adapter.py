"""
adapters/generic_odbc_adapter.py
=================================
Generic ODBC fallback adapter — tanınmayan veya özel DB'ler için.
BRD Faz 5 — F5-07

Yalnızca ANSI SQL ve INFORMATION_SCHEMA kullanan sorgular içerir;
herhangi bir ODBC-uyumlu veritabanında çalışır.

Kullanım: databases.yaml'da adapter olarak bu sınıfı göster,
DSN veya connection_string üzerinden bağlantı kur.

Bağlantı önceliği:
  1. connection_string (tam DSN string)
  2. dsn + credentials
  3. host/port/db_name + driver + credentials
"""

from __future__ import annotations

import logging
import time
from typing import Optional

try:
    import pyodbc
except ImportError:
    pyodbc = None

from core.base_adapter import (
    DBAdapter, HealthResult, DBMetadata,
    ConnectionError, AuthenticationError, QueryError, TimeoutError,
)
from core.metric_schema import MetricSchema, Sonuc, Kategori

logger = logging.getLogger(__name__)

HASSAS_KOLONLAR = [
    "password", "parola", "sifre", "passwd",
    "credit_card", "kredi_kart", "kart_no",
    "ssn", "tc_kimlik", "tckn", "iban", "banka",
    "token", "secret", "api_key",
]


class GenericODBCAdapter(DBAdapter):
    """
    ODBC-uyumlu herhangi bir DB için fallback adapter.
    DB-spesifik view veya DMV kullanmaz — yalnızca ANSI INFORMATION_SCHEMA.
    """

    ADAPTER_VERSION = "1.0.0"

    def __init__(self, config: dict):
        super().__init__(config)
        self._conn: Optional[object] = None
        self._connection_string = config.get("connection_string", None)
        self._dsn = config.get("dsn", None)
        self._driver = config.get("driver", None)

    # ------------------------------------------------------------------
    # Bağlantı
    # ------------------------------------------------------------------
    def connect(self) -> None:
        if pyodbc is None:
            raise ConnectionError(
                "pyodbc yüklü değil. 'pip install pyodbc' çalıştırın.",
                db_type=self.db_type, host=self.host,
            )

        conn_str = self._build_connection_string()
        try:
            self._conn = pyodbc.connect(conn_str, timeout=self.connect_timeout_s)
            self._conn.timeout = self.query_timeout_s
            logger.info("Generic ODBC bağlantısı kuruldu: %s/%s", self.host, self.db_name)
        except pyodbc.Error as exc:
            msg = str(exc).lower()
            if "login failed" in msg or "password" in msg or "access denied" in msg:
                raise AuthenticationError(str(exc), db_type=self.db_type, host=self.host, cause=exc)
            if "timeout" in msg:
                raise TimeoutError(str(exc), db_type=self.db_type, host=self.host, cause=exc)
            raise ConnectionError(str(exc), db_type=self.db_type, host=self.host, cause=exc)
        except Exception as exc:
            raise ConnectionError(str(exc), db_type=self.db_type, host=self.host, cause=exc)

    def _build_connection_string(self) -> str:
        """Config'e göre ODBC connection string oluşturur."""
        # 1. Hazır connection string
        if self._connection_string:
            return self._connection_string

        creds = self.config.get("credentials", {})

        # 2. DSN tabanlı
        if self._dsn:
            parts = [f"DSN={self._dsn}"]
            if creds.get("user"):
                parts.append(f"UID={creds['user']}")
            if creds.get("password"):
                parts.append(f"PWD={creds['password']}")
            return ";".join(parts)

        # 3. Host/port/driver tabanlı
        driver = self._driver or self._detect_any_driver()
        if not driver:
            raise ConnectionError(
                "ODBC driver bulunamadı. 'driver' veya 'dsn' veya 'connection_string' belirtin.",
                db_type=self.db_type, host=self.host,
            )
        parts = [
            f"DRIVER={{{driver}}}",
            f"SERVER={self.host},{self.port}" if self.port else f"SERVER={self.host}",
            f"DATABASE={self.db_name}",
            f"Connection Timeout={self.connect_timeout_s}",
        ]
        if creds.get("user"):
            parts.append(f"UID={creds['user']}")
        if creds.get("password"):
            parts.append(f"PWD={creds['password']}")
        return ";".join(parts)

    def disconnect(self) -> None:
        try:
            if self._conn:
                self._conn.close()
        except Exception as exc:
            logger.warning("Generic ODBC bağlantı kapatma hatası: %s", exc)
        finally:
            self._conn = None

    def health_check(self) -> HealthResult:
        try:
            t0 = time.perf_counter()
            cur = self._conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
            latency_ms = (time.perf_counter() - t0) * 1000
            return HealthResult(is_healthy=True, latency_ms=latency_ms)
        except Exception as exc:
            return HealthResult(is_healthy=False, latency_ms=0, message=str(exc))

    def get_metadata(self) -> DBMetadata:
        # ANSI SQL — çoğu DB'de çalışır
        version = "unknown"
        for sql in [
            "SELECT @@VERSION",           # MSSQL, MySQL
            "SELECT VERSION()",           # MySQL, MariaDB, PostgreSQL
            "SELECT * FROM V$VERSION WHERE ROWNUM=1",  # Oracle (fallback)
        ]:
            try:
                cur = self._conn.cursor()
                cur.execute(sql)
                row = cur.fetchone()
                cur.close()
                if row:
                    version = str(row[0]).split("\n")[0].strip()
                    break
            except Exception:
                continue

        return DBMetadata(
            db_type         = self.db_type or "generic_odbc",
            host            = self.host,
            port            = self.port or 0,
            db_name         = self.db_name,
            version         = version,
            adapter_version = self.ADAPTER_VERSION,
        )

    # ------------------------------------------------------------------
    # Ana toplama metodu
    # ------------------------------------------------------------------
    def collect_metrics(self) -> list[MetricSchema]:
        metrics = []
        checks = [
            (self._check_large_tables,      "FR-COST-03"),
            (self._check_duplicates,        "FR-DQ-02"),
            (self._check_sensitive_columns, "FR-SEC-01"),
        ]
        for fn, kod in checks:
            metrics.extend(self._safe_collect(fn, kod))
        return metrics

    # ------------------------------------------------------------------
    # FR-COST-03: Büyük tablolar (INFORMATION_SCHEMA tabanlı)
    # Not: INFORMATION_SCHEMA.TABLES.DATA_LENGTH standart değil —
    # destekleniyorsa kullanılır, yoksa sadece tablo listesi döner.
    # ------------------------------------------------------------------
    def _check_large_tables(self) -> list[MetricSchema]:
        # Önce DATA_LENGTH destekli sürümü dene
        sql_with_size = """
            SELECT
                TABLE_SCHEMA || '.' || TABLE_NAME AS tablo,
                DATA_LENGTH + INDEX_LENGTH AS boyut_bytes
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE'
              AND TABLE_SCHEMA NOT IN ('information_schema','performance_schema','sys','mysql','pg_catalog')
            ORDER BY boyut_bytes DESC
        """
        sql_no_size = """
            SELECT
                TABLE_SCHEMA || '.' || TABLE_NAME AS tablo,
                NULL AS boyut_bytes
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE'
              AND TABLE_SCHEMA NOT IN ('information_schema','performance_schema','sys','mysql','pg_catalog')
        """
        try:
            rows = self._fetchall(sql_with_size)
            # 1GB+ olanları filtrele
            big = [(r[0], r[1]) for r in rows if r[1] and r[1] > 1024 * 1024 * 1024]
        except Exception:
            try:
                rows = self._fetchall(sql_no_size)
                big = []
            except Exception:
                return [self._ok("FR-COST-03", "partitionsiz_buyuk_tablo",
                                  "INFORMATION_SCHEMA.TABLES erişilemiyor — atlandı")]

        if not big:
            return [self._ok("FR-COST-03", "partitionsiz_buyuk_tablo",
                              "1GB+ tablo tespit edilmedi veya boyut bilgisi mevcut değil")]

        results = []
        for tablo, boyut_bytes in big:
            boyut_mb = round(boyut_bytes / 1024 / 1024, 2)
            results.append(MetricSchema(
                db_type        = self.db_type,
                host           = self.host,
                db_name        = self.db_name,
                kategori       = Kategori.MALIYET,
                kontrol_kodu   = "FR-COST-03",
                kontrol_adi    = "partitionsiz_buyuk_tablo",
                sonuc          = Sonuc.WARNING,
                severity       = 2,
                etkilenen_obje = tablo,
                detay          = f"Boyut: {boyut_mb} MB — partition kontrolü önerilir",
            ))
        return results

    # ------------------------------------------------------------------
    # FR-DQ-02: PK/UNIQUE kısıt eksik tablolar
    # INFORMATION_SCHEMA.TABLE_CONSTRAINTS — geniş ODBC uyumluluğu
    # ------------------------------------------------------------------
    def _check_duplicates(self) -> list[MetricSchema]:
        sql = """
            SELECT
                t.TABLE_SCHEMA || '.' || t.TABLE_NAME AS tablo
            FROM INFORMATION_SCHEMA.TABLES t
            WHERE
                t.TABLE_TYPE = 'BASE TABLE'
                AND t.TABLE_SCHEMA NOT IN ('information_schema','performance_schema','sys','mysql','pg_catalog')
                AND NOT EXISTS (
                    SELECT 1 FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                    WHERE tc.TABLE_SCHEMA = t.TABLE_SCHEMA
                      AND tc.TABLE_NAME = t.TABLE_NAME
                      AND tc.CONSTRAINT_TYPE IN ('PRIMARY KEY', 'UNIQUE')
                )
        """
        try:
            rows = self._fetchall(sql)
        except Exception:
            return [self._ok("FR-DQ-02", "duplicate_kontrol",
                              "INFORMATION_SCHEMA.TABLE_CONSTRAINTS erişilemiyor — atlandı")]

        if not rows:
            return [self._ok("FR-DQ-02", "duplicate_kontrol", "PK/UNIQUE kısıt eksik tablo yok")]

        results = []
        for (tablo,) in rows[:10]:
            results.append(MetricSchema(
                db_type        = self.db_type,
                host           = self.host,
                db_name        = self.db_name,
                kategori       = Kategori.KALITE,
                kontrol_kodu   = "FR-DQ-02",
                kontrol_adi    = "duplicate_kontrol",
                sonuc          = Sonuc.WARNING,
                severity       = 2,
                etkilenen_obje = tablo,
                detay          = "PK/UNIQUE kısıt yok",
            ))
        return results

    # ------------------------------------------------------------------
    # FR-SEC-01: Hassas kolon adları
    # INFORMATION_SCHEMA.COLUMNS — evrensel
    # ------------------------------------------------------------------
    def _check_sensitive_columns(self) -> list[MetricSchema]:
        placeholders = ",".join(f"'{k}'" for k in HASSAS_KOLONLAR)
        sql = f"""
            SELECT
                TABLE_SCHEMA || '.' || TABLE_NAME AS tablo,
                COLUMN_NAME,
                DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE
                TABLE_SCHEMA NOT IN ('information_schema','performance_schema','sys','mysql','pg_catalog')
                AND LOWER(COLUMN_NAME) IN ({placeholders})
            ORDER BY TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME
        """
        try:
            rows = self._fetchall(sql)
        except Exception:
            return [self._ok("FR-SEC-01", "hassas_kolon",
                              "INFORMATION_SCHEMA.COLUMNS erişilemiyor — atlandı")]

        if not rows:
            return [self._ok("FR-SEC-01", "hassas_kolon", "Hassas kolon adı tespit edilmedi")]

        results = []
        for tablo, kolon, veri_tipi in rows[:30]:
            results.append(MetricSchema(
                db_type        = self.db_type,
                host           = self.host,
                db_name        = self.db_name,
                kategori       = Kategori.GUVENLIK,
                kontrol_kodu   = "FR-SEC-01",
                kontrol_adi    = "hassas_kolon",
                sonuc          = Sonuc.ERROR,
                severity       = 3,
                etkilenen_obje = f"{tablo}.{kolon}",
                detay          = f"Tip: {veri_tipi} — maskeleme kontrol edilmeli",
            ))
        return results

    # ------------------------------------------------------------------
    # Yardımcı metodlar
    # ------------------------------------------------------------------
    def _fetchall(self, sql: str, params: tuple = ()) -> list:
        cur = self._conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return rows

    def _ok(self, kod: str, ad: str, detay: str) -> MetricSchema:
        return MetricSchema(
            db_type      = self.db_type,
            host         = self.host,
            db_name      = self.db_name,
            kategori     = self._kategori_from_kod(kod),
            kontrol_kodu = kod,
            kontrol_adi  = ad,
            sonuc        = Sonuc.OK,
            severity     = 1,
            detay        = detay,
        )

    @staticmethod
    def _detect_any_driver() -> Optional[str]:
        """Kurulu herhangi bir ODBC driver'ı döner."""
        if pyodbc is None:
            return None
        drivers = pyodbc.drivers()
        return drivers[0] if drivers else None
