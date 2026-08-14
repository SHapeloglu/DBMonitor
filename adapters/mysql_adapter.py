"""
adapters/mysql_adapter.py
==========================
MySQL / MariaDB ortak adapter implementasyonu.
BRD Faz 5 — F5-03 (MySQL) + F5-04 (MariaDB)

Not (K-04 açık karar): Bu adapter MySQL Community Edition ve MariaDB
ile uyumlu şekilde tasarlandı — yalnızca information_schema ve
performance_schema kullanır, Enterprise Audit Plugin'e bağımlı değildir.
Enterprise Audit mevcutsa ileride ek FR-SEC kontrolleri eklenebilir.

db_type config alanı üzerinden "mysql" veya "mariadb" olarak ayrıştırılır;
sorgular her iki motorda da ortak SQL sözdizimi kullanır.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

try:
    import pymysql
    import pymysql.cursors
except ImportError:
    pymysql = None  # preflight_check.py yakalar

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

NULL_SCAN_ROW_LIMIT = 500_000


class MySQLAdapter(DBAdapter):
    """MySQL ve MariaDB için ortak adapter. db_type config'ten okunur."""

    ADAPTER_VERSION = "1.0.0"

    def __init__(self, config: dict):
        super().__init__(config)
        self._conn: Optional[object] = None

    def connect(self) -> None:
        if pymysql is None:
            raise ConnectionError(
                "pymysql yüklü değil. 'pip install pymysql' çalıştırın.",
                db_type=self.db_type, host=self.host,
            )
        creds = self.config.get("credentials", {})
        try:
            self._conn = pymysql.connect(
                host              = self.host,
                port              = self.port or 3306,
                database          = self.db_name,
                user              = creds.get("user", ""),
                password          = creds.get("password", ""),
                connect_timeout   = self.connect_timeout_s,
                read_timeout      = self.query_timeout_s,
                write_timeout     = self.query_timeout_s,
                cursorclass       = pymysql.cursors.Cursor,
                autocommit        = True,
                charset           = "utf8mb4",
            )
            logger.info("MySQL/MariaDB bağlantısı kuruldu: %s:%s/%s (db_type=%s)",
                        self.host, self.port, self.db_name, self.db_type)
        except pymysql.err.OperationalError as exc:
            msg = str(exc).lower()
            if "access denied" in msg or "password" in msg:
                raise AuthenticationError(str(exc), db_type=self.db_type, host=self.host, cause=exc)
            if "timeout" in msg or "timed out" in msg:
                raise TimeoutError(str(exc), db_type=self.db_type, host=self.host, cause=exc)
            raise ConnectionError(str(exc), db_type=self.db_type, host=self.host, cause=exc)
        except Exception as exc:
            raise ConnectionError(str(exc), db_type=self.db_type, host=self.host, cause=exc)

    def disconnect(self) -> None:
        try:
            if self._conn:
                self._conn.close()
        except Exception as exc:
            logger.warning("MySQL/MariaDB bağlantı kapatma hatası: %s", exc)
        finally:
            self._conn = None

    def health_check(self) -> HealthResult:
        try:
            t0 = time.perf_counter()
            with self._conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            latency_ms = (time.perf_counter() - t0) * 1000
            return HealthResult(is_healthy=True, latency_ms=latency_ms)
        except Exception as exc:
            return HealthResult(is_healthy=False, latency_ms=0, message=str(exc))

    def get_metadata(self) -> DBMetadata:
        with self._conn.cursor() as cur:
            cur.execute("SELECT VERSION()")
            version = cur.fetchone()[0]
        return DBMetadata(
            db_type         = self.db_type,
            host            = self.host,
            port            = self.port or 3306,
            db_name         = self.db_name,
            version         = version,
            adapter_version = self.ADAPTER_VERSION,
        )

    def collect_metrics(self) -> list[MetricSchema]:
        metrics = []
        checks = [
            (self._check_unused_tables,     "FR-COST-01"),
            (self._check_table_fragmentation, "FR-COST-02"),
            (self._check_unpartitioned,     "FR-COST-03"),
            (self._check_null_ratio,        "FR-DQ-01"),
            (self._check_duplicates,        "FR-DQ-02"),
            (self._check_daily_load,        "FR-PIPE-01"),
            (self._check_sensitive_columns, "FR-SEC-01"),
            (self._check_long_queries,      "FR-USER-01"),
        ]
        for fn, kod in checks:
            metrics.extend(self._safe_collect(fn, kod))
        return metrics

    def _check_unused_tables(self) -> list[MetricSchema]:
        sql = """
            SELECT
                CONCAT(TABLE_SCHEMA, '.', TABLE_NAME) AS tablo,
                UPDATE_TIME,
                ROUND((DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024, 2) AS boyut_mb
            FROM information_schema.TABLES
            WHERE
                TABLE_SCHEMA NOT IN ('mysql','information_schema','performance_schema','sys','monitor')
                AND TABLE_TYPE = 'BASE TABLE'
                AND (
                    UPDATE_TIME < DATE_SUB(NOW(), INTERVAL 30 DAY)
                    OR UPDATE_TIME IS NULL
                )
            ORDER BY (DATA_LENGTH + INDEX_LENGTH) DESC
            LIMIT 20
        """
        rows = self._fetchall(sql)
        if not rows:
            return [self._ok("FR-COST-01", "kullanilmayan_tablo", "30+ gün erişilmeyen tablo yok")]
        results = []
        for tablo, update_time, boyut_mb in rows:
            results.append(MetricSchema(
                db_type        = self.db_type,
                host           = self.host,
                db_name        = self.db_name,
                kategori       = Kategori.MALIYET,
                kontrol_kodu   = "FR-COST-01",
                kontrol_adi    = "kullanilmayan_tablo",
                sonuc          = Sonuc.WARNING,
                severity       = 2,
                etkilenen_obje = tablo,
                detay          = f"Son güncelleme: {update_time} | Boyut: {boyut_mb} MB "
                                  f"(UPDATE_TIME yalnızca InnoDB file-per-table için güvenilirdir)",
            ))
        return results

    def _check_table_fragmentation(self) -> list[MetricSchema]:
        sql = """
            SELECT
                CONCAT(TABLE_SCHEMA, '.', TABLE_NAME) AS tablo,
                ROUND(DATA_FREE / 1024 / 1024, 2) AS bosluk_mb,
                ROUND((DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024, 2) AS toplam_mb,
                ROUND(100.0 * DATA_FREE / NULLIF(DATA_LENGTH + INDEX_LENGTH + DATA_FREE, 0), 1) AS frag_pct
            FROM information_schema.TABLES
            WHERE
                TABLE_SCHEMA NOT IN ('mysql','information_schema','performance_schema','sys','monitor')
                AND TABLE_TYPE = 'BASE TABLE'
                AND DATA_FREE > 100 * 1024 * 1024
                AND (100.0 * DATA_FREE / NULLIF(DATA_LENGTH + INDEX_LENGTH + DATA_FREE, 0)) > 20
            ORDER BY DATA_FREE DESC
            LIMIT 10
        """
        rows = self._fetchall(sql)
        if not rows:
            return [self._ok("FR-COST-02", "tablo_fragmantasyon", "Anormal fragmantasyon tespit edilmedi")]
        results = []
        for tablo, bosluk_mb, toplam_mb, frag_pct in rows:
            severity = 3 if (frag_pct or 0) > 40 else 2
            results.append(MetricSchema(
                db_type        = self.db_type,
                host           = self.host,
                db_name        = self.db_name,
                kategori       = Kategori.MALIYET,
                kontrol_kodu   = "FR-COST-02",
                kontrol_adi    = "tablo_fragmantasyon",
                sonuc          = Sonuc.ERROR if severity == 3 else Sonuc.WARNING,
                severity       = severity,
                etkilenen_obje = tablo,
                detay          = f"Fragmantasyon: %{frag_pct} | Boşluk: {bosluk_mb} MB / Toplam: {toplam_mb} MB",
            ))
        return results

    def _check_unpartitioned(self) -> list[MetricSchema]:
        sql = """
            SELECT
                CONCAT(TABLE_SCHEMA, '.', TABLE_NAME) AS tablo,
                ROUND((DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024, 2) AS boyut_mb
            FROM information_schema.TABLES
            WHERE
                TABLE_SCHEMA NOT IN ('mysql','information_schema','performance_schema','sys','monitor')
                AND TABLE_TYPE = 'BASE TABLE'
                AND (DATA_LENGTH + INDEX_LENGTH) > 1024 * 1024 * 1024
                AND CONCAT(TABLE_SCHEMA, '.', TABLE_NAME) NOT IN (
                    SELECT DISTINCT CONCAT(TABLE_SCHEMA, '.', TABLE_NAME)
                    FROM information_schema.PARTITIONS
                    WHERE PARTITION_NAME IS NOT NULL
                )
            ORDER BY (DATA_LENGTH + INDEX_LENGTH) DESC
            LIMIT 10
        """
        rows = self._fetchall(sql)
        if not rows:
            return [self._ok("FR-COST-03", "partitionsiz_buyuk_tablo", "1GB+ partitionsiz tablo yok")]
        results = []
        for tablo, boyut_mb in rows:
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
                detay          = f"Boyut: {boyut_mb} MB — partition önerilir",
            ))
        return results

    def _check_null_ratio(self) -> list[MetricSchema]:
        tablo_sql = """
            SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_ROWS
            FROM information_schema.TABLES
            WHERE
                TABLE_SCHEMA NOT IN ('mysql','information_schema','performance_schema','sys','monitor')
                AND TABLE_TYPE = 'BASE TABLE'
                AND TABLE_ROWS BETWEEN 1 AND %s
            ORDER BY TABLE_ROWS DESC
            LIMIT 15
        """
        tablolar = self._fetchall(tablo_sql, (NULL_SCAN_ROW_LIMIT,))
        if not tablolar:
            return [self._ok("FR-DQ-01", "null_orani",
                              "Taranabilir boyutta tablo yok (limit: %d satır)" % NULL_SCAN_ROW_LIMIT)]
        results = []
        for schema, tablo, tahmini_satir in tablolar:
            kolon_sql = """
                SELECT COLUMN_NAME
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND IS_NULLABLE = 'YES'
            """
            kolonlar = self._fetchall(kolon_sql, (schema, tablo))
            for (kolon,) in kolonlar:
                try:
                    check_sql = f"""
                        SELECT
                            COUNT(*) AS toplam,
                            SUM(CASE WHEN `{kolon}` IS NULL THEN 1 ELSE 0 END) AS null_sayi
                        FROM `{schema}`.`{tablo}`
                    """
                    toplam, null_sayi = self._fetchone(check_sql)
                    if toplam and toplam > 0:
                        oran = null_sayi / toplam
                        if oran > 0.5:
                            pct = round(oran * 100, 1)
                            severity = 3 if pct > 80 else 2
                            results.append(MetricSchema(
                                db_type        = self.db_type,
                                host           = self.host,
                                db_name        = self.db_name,
                                kategori       = Kategori.KALITE,
                                kontrol_kodu   = "FR-DQ-01",
                                kontrol_adi    = "null_orani",
                                sonuc          = Sonuc.ERROR if severity == 3 else Sonuc.WARNING,
                                severity       = severity,
                                etkilenen_obje = f"{schema}.{tablo}.{kolon}",
                                detay          = f"NULL oranı: %{pct}",
                            ))
                except Exception as exc:
                    logger.warning("FR-DQ-01 kolon tarama hatası %s.%s.%s: %s", schema, tablo, kolon, exc)
        if not results:
            return [self._ok("FR-DQ-01", "null_orani", "NULL oranı yüksek kolon yok")]
        return results

    def _check_duplicates(self) -> list[MetricSchema]:
        sql = """
            SELECT
                CONCAT(t.TABLE_SCHEMA, '.', t.TABLE_NAME) AS tablo,
                t.TABLE_ROWS
            FROM information_schema.TABLES t
            WHERE
                t.TABLE_SCHEMA NOT IN ('mysql','information_schema','performance_schema','sys','monitor')
                AND t.TABLE_TYPE = 'BASE TABLE'
                AND t.TABLE_ROWS > 0
                AND NOT EXISTS (
                    SELECT 1 FROM information_schema.TABLE_CONSTRAINTS tc
                    WHERE tc.TABLE_SCHEMA = t.TABLE_SCHEMA
                      AND tc.TABLE_NAME = t.TABLE_NAME
                      AND tc.CONSTRAINT_TYPE IN ('PRIMARY KEY', 'UNIQUE')
                )
            ORDER BY t.TABLE_ROWS DESC
            LIMIT 10
        """
        rows = self._fetchall(sql)
        if not rows:
            return [self._ok("FR-DQ-02", "duplicate_kontrol", "PK/UNIQUE kısıt eksik tablo yok")]
        results = []
        for tablo, kayit_sayisi in rows:
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
                etkilenen_sayi = kayit_sayisi,
                detay          = f"PK/UNIQUE kısıt yok. Tahmini kayıt: {kayit_sayisi}",
            ))
        return results

    def _check_daily_load(self) -> list[MetricSchema]:
        sql = """
            SELECT
                CONCAT(TABLE_SCHEMA, '.', TABLE_NAME) AS tablo,
                TABLE_ROWS,
                UPDATE_TIME
            FROM information_schema.TABLES
            WHERE
                TABLE_SCHEMA NOT IN ('mysql','information_schema','performance_schema','sys','monitor')
                AND TABLE_TYPE = 'BASE TABLE'
                AND TABLE_ROWS > 10000
                AND (
                    UPDATE_TIME < CURDATE()
                    OR UPDATE_TIME IS NULL
                )
            ORDER BY TABLE_ROWS DESC
            LIMIT 10
        """
        rows = self._fetchall(sql)
        if not rows:
            return [self._ok("FR-PIPE-01", "gunluk_yukleme", "Tüm tablolarda bugün veri hareketi var")]
        results = []
        for tablo, kayit_sayisi, update_time in rows:
            results.append(MetricSchema(
                db_type        = self.db_type,
                host           = self.host,
                db_name        = self.db_name,
                kategori       = Kategori.PIPELINE,
                kontrol_kodu   = "FR-PIPE-01",
                kontrol_adi    = "gunluk_yukleme",
                sonuc          = Sonuc.WARNING,
                severity       = 2,
                etkilenen_obje = tablo,
                etkilenen_sayi = kayit_sayisi,
                detay          = f"Bugün güncelleme yok. Son: {update_time} | Kayıt: {kayit_sayisi}",
            ))
        return results

    def _check_sensitive_columns(self) -> list[MetricSchema]:
        placeholders = ",".join(["%s"] * len(HASSAS_KOLONLAR))
        sql = f"""
            SELECT
                CONCAT(TABLE_SCHEMA, '.', TABLE_NAME) AS tablo,
                COLUMN_NAME,
                DATA_TYPE
            FROM information_schema.COLUMNS
            WHERE
                TABLE_SCHEMA NOT IN ('mysql','information_schema','performance_schema','sys','monitor')
                AND LOWER(COLUMN_NAME) IN ({placeholders})
            ORDER BY TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME
            LIMIT 30
        """
        rows = self._fetchall(sql, tuple(HASSAS_KOLONLAR))
        if not rows:
            return [self._ok("FR-SEC-01", "hassas_kolon", "Maskelenmemiş hassas kolon adı yok")]
        results = []
        for tablo, kolon, veri_tipi in rows:
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

    def _check_long_queries(self) -> list[MetricSchema]:
        sql = """
            SELECT
                ID,
                USER,
                TIME,
                LEFT(INFO, 200) AS sorgu
            FROM information_schema.PROCESSLIST
            WHERE
                COMMAND = 'Query'
                AND TIME > 60
                AND INFO NOT LIKE '%PROCESSLIST%'
            ORDER BY TIME DESC
            LIMIT 10
        """
        try:
            rows = self._fetchall(sql)
        except Exception:
            return [self._ok("FR-USER-01", "uzun_sorgu", "information_schema.PROCESSLIST erişim yetkisi yok — atlandı")]
        if not rows:
            return [self._ok("FR-USER-01", "uzun_sorgu", "60s+ süren aktif sorgu yok")]
        results = []
        for pid, kullanici, sure, sorgu in rows:
            sure = sure or 0
            severity = 3 if sure > 300 else 2
            results.append(MetricSchema(
                db_type        = self.db_type,
                host           = self.host,
                db_name        = self.db_name,
                kategori       = Kategori.KULLANICI,
                kontrol_kodu   = "FR-USER-01",
                kontrol_adi    = "uzun_sorgu",
                sonuc          = Sonuc.ERROR if severity == 3 else Sonuc.WARNING,
                severity       = severity,
                etkilenen_obje = f"id={pid} user={kullanici}",
                detay          = f"Süre: {sure}s | Sorgu: {sorgu}",
            ))
        return results

    def _fetchall(self, sql: str, params: tuple = ()) -> list:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def _fetchone(self, sql: str, params: tuple = ()):
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

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
