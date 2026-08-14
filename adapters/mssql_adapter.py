"""
adapters/mssql_adapter.py
=========================
Microsoft SQL Server adapter implementasyonu.
BRD Faz 4 — FR-COST-01/03, FR-DQ-04, FR-PIPE-01/04,
             FR-USER-04, FR-SEC-01/03
"""

from __future__ import annotations

import logging
import time
from typing import Optional

try:
    import pyodbc
except ImportError:
    pyodbc = None  # preflight_check.py yakalar

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


class MSSQLAdapter(DBAdapter):

    ADAPTER_VERSION = "1.0.0"

    def __init__(self, config: dict):
        super().__init__(config)
        self._conn: Optional[object] = None
        self._driver = config.get("driver", None)

    def connect(self) -> None:
        if pyodbc is None:
            raise ConnectionError(
                "pyodbc yüklü değil. 'pip install pyodbc' çalıştırın.",
                db_type=self.db_type, host=self.host,
            )
        driver = self._driver or self._detect_driver()
        if not driver:
            raise ConnectionError(
                "ODBC Driver bulunamadı. MSSQL ODBC Driver 17 veya 18 kurulu olmalı.",
                db_type=self.db_type, host=self.host,
            )
        creds = self.config.get("credentials", {})
        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={self.host},{self.port or 1433};"
            f"DATABASE={self.db_name};"
            f"UID={creds.get('user', '')};"
            f"PWD={creds.get('password', '')};"
            f"Connection Timeout={self.connect_timeout_s};"
            f"Login Timeout={self.connect_timeout_s};"
        )
        try:
            self._conn = pyodbc.connect(conn_str, timeout=self.connect_timeout_s)
            self._conn.timeout = self.query_timeout_s
            logger.info("MSSQL bağlantısı kuruldu: %s:%s/%s (driver=%s)",
                        self.host, self.port, self.db_name, driver)
        except pyodbc.Error as exc:
            msg = str(exc).lower()
            if "login failed" in msg or "password" in msg:
                raise AuthenticationError(str(exc), db_type=self.db_type, host=self.host, cause=exc)
            if "timeout" in msg:
                raise TimeoutError(str(exc), db_type=self.db_type, host=self.host, cause=exc)
            raise ConnectionError(str(exc), db_type=self.db_type, host=self.host, cause=exc)
        except Exception as exc:
            raise ConnectionError(str(exc), db_type=self.db_type, host=self.host, cause=exc)

    def disconnect(self) -> None:
        try:
            if self._conn:
                self._conn.close()
        except Exception as exc:
            logger.warning("MSSQL bağlantı kapatma hatası: %s", exc)
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
        cur = self._conn.cursor()
        cur.execute("SELECT @@VERSION")
        version = (cur.fetchone()[0] or "").split("\n")[0].strip()
        cur.close()
        return DBMetadata(
            db_type         = "mssql",
            host            = self.host,
            port            = self.port or 1433,
            db_name         = self.db_name,
            version         = version,
            adapter_version = self.ADAPTER_VERSION,
        )

    def collect_metrics(self) -> list[MetricSchema]:
        metrics = []
        checks = [
            (self._check_unused_tables,      "FR-COST-01"),
            (self._check_unpartitioned,      "FR-COST-03"),
            (self._check_format_violations,  "FR-DQ-04"),
            (self._check_daily_load,         "FR-PIPE-01"),
            (self._check_schema_changes,     "FR-PIPE-04"),
            (self._check_large_queries,      "FR-USER-04"),
            (self._check_sensitive_columns,  "FR-SEC-01"),
            (self._check_offhours_queries,   "FR-SEC-03"),
        ]
        for fn, kod in checks:
            metrics.extend(self._safe_collect(fn, kod))
        return metrics

    def _check_unused_tables(self) -> list[MetricSchema]:
        sql = """
            SELECT TOP 20
                SCHEMA_NAME(o.schema_id) + '.' + o.name AS tablo,
                MAX(COALESCE(us.last_user_seek, us.last_user_scan, us.last_user_lookup)) AS son_erisim,
                CAST(SUM(a.total_pages) * 8.0 / 1024 AS DECIMAL(10,2)) AS boyut_mb
            FROM sys.objects o
            JOIN sys.indexes i ON i.object_id = o.object_id
            JOIN sys.partitions p ON p.object_id = o.object_id AND p.index_id = i.index_id
            JOIN sys.allocation_units a ON a.container_id = p.partition_id
            LEFT JOIN sys.dm_db_index_usage_stats us
                ON us.object_id = o.object_id
                AND us.index_id = i.index_id
                AND us.database_id = DB_ID()
            WHERE
                o.type = 'U'
                AND o.schema_id NOT IN (SELECT schema_id FROM sys.schemas WHERE name IN ('sys','INFORMATION_SCHEMA'))
            GROUP BY o.schema_id, o.name
            HAVING
                MAX(COALESCE(us.last_user_seek, us.last_user_scan, us.last_user_lookup)) < DATEADD(DAY, -30, GETDATE())
                OR MAX(COALESCE(us.last_user_seek, us.last_user_scan, us.last_user_lookup)) IS NULL
            ORDER BY boyut_mb DESC
        """
        rows = self._fetchall(sql)
        if not rows:
            return [self._ok("FR-COST-01", "kullanilmayan_tablo", "30+ gün erişilmeyen tablo yok")]
        results = []
        for row in rows:
            results.append(MetricSchema(
                db_type        = self.db_type,
                host           = self.host,
                db_name        = self.db_name,
                kategori       = Kategori.MALIYET,
                kontrol_kodu   = "FR-COST-01",
                kontrol_adi    = "kullanilmayan_tablo",
                sonuc          = Sonuc.WARNING,
                severity       = 2,
                etkilenen_obje = row[0],
                detay          = f"Son erişim: {row[1]} | Boyut: {row[2]} MB",
            ))
        return results

    def _check_unpartitioned(self) -> list[MetricSchema]:
        sql = """
            SELECT TOP 10
                SCHEMA_NAME(o.schema_id) + '.' + o.name AS tablo,
                CAST(SUM(a.total_pages) * 8.0 / 1024 AS DECIMAL(10,2)) AS boyut_mb,
                COUNT(DISTINCT p.partition_number) AS partition_sayisi
            FROM sys.objects o
            JOIN sys.partitions p ON p.object_id = o.object_id
            JOIN sys.allocation_units a ON a.container_id = p.partition_id
            WHERE o.type = 'U'
            GROUP BY o.schema_id, o.name
            HAVING
                COUNT(DISTINCT p.partition_number) = 1
                AND SUM(a.total_pages) * 8.0 / 1024 > 1024
            ORDER BY boyut_mb DESC
        """
        rows = self._fetchall(sql)
        if not rows:
            return [self._ok("FR-COST-03", "partitionsiz_buyuk_tablo", "1GB+ partitionsiz tablo yok")]
        results = []
        for row in rows:
            results.append(MetricSchema(
                db_type        = self.db_type,
                host           = self.host,
                db_name        = self.db_name,
                kategori       = Kategori.MALIYET,
                kontrol_kodu   = "FR-COST-03",
                kontrol_adi    = "partitionsiz_buyuk_tablo",
                sonuc          = Sonuc.WARNING,
                severity       = 2,
                etkilenen_obje = row[0],
                detay          = f"Boyut: {row[1]} MB — partition önerilir",
            ))
        return results

    def _check_format_violations(self) -> list[MetricSchema]:
        discovery_sql = """
            SELECT TOP 20
                TABLE_SCHEMA + '.' + TABLE_NAME AS tablo,
                COLUMN_NAME,
                DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE
                DATA_TYPE IN ('nvarchar','varchar','char','nchar')
                AND LOWER(COLUMN_NAME) IN (
                    'iban','tckn','tc_kimlik','telefon','tel','gsm',
                    'phone','mobile','cep'
                )
        """
        cols = self._fetchall(discovery_sql)
        if not cols:
            return [self._ok("FR-DQ-04", "format_ihlali", "Format kontrol edilecek kolon bulunamadı")]
        results = []
        for tablo, kolon, _ in cols:
            if "iban" in kolon.lower():
                pattern_sql = f"""
                    SELECT COUNT(*) FROM {tablo}
                    WHERE {kolon} IS NOT NULL
                      AND {kolon} NOT LIKE 'TR[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
                      AND LEN({kolon}) > 0
                """
            elif any(x in kolon.lower() for x in ["tckn", "tc_kimlik"]):
                pattern_sql = f"""
                    SELECT COUNT(*) FROM {tablo}
                    WHERE {kolon} IS NOT NULL
                      AND ({kolon} NOT LIKE '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
                           OR LEN({kolon}) != 11)
                      AND LEN({kolon}) > 0
                """
            else:
                pattern_sql = f"""
                    SELECT COUNT(*) FROM {tablo}
                    WHERE {kolon} IS NOT NULL
                      AND {kolon} NOT LIKE '+[0-9]%'
                      AND {kolon} NOT LIKE '0[0-9][0-9][0-9]%'
                      AND LEN({kolon}) > 0
                """
            try:
                sayi = self._fetchval(pattern_sql)
                if sayi and sayi > 0:
                    severity = 3 if sayi > 1000 else 2
                    results.append(MetricSchema(
                        db_type        = self.db_type,
                        host           = self.host,
                        db_name        = self.db_name,
                        kategori       = Kategori.KALITE,
                        kontrol_kodu   = "FR-DQ-04",
                        kontrol_adi    = "format_ihlali",
                        sonuc          = Sonuc.ERROR if severity == 3 else Sonuc.WARNING,
                        severity       = severity,
                        etkilenen_obje = f"{tablo}.{kolon}",
                        etkilenen_sayi = sayi,
                        detay          = f"Format ihlali: {sayi} kayıt",
                    ))
            except Exception as exc:
                logger.warning("FR-DQ-04 tablo tarama hatası %s.%s: %s", tablo, kolon, exc)
        if not results:
            return [self._ok("FR-DQ-04", "format_ihlali", "Format ihlali tespit edilmedi")]
        return results

    def _check_daily_load(self) -> list[MetricSchema]:
        sql = """
            SELECT TOP 10
                SCHEMA_NAME(o.schema_id) + '.' + o.name AS tablo,
                p.row_count AS kayit_sayisi,
                CAST(SUM(a.total_pages) * 8.0 / 1024 AS DECIMAL(10,2)) AS boyut_mb
            FROM sys.objects o
            JOIN sys.dm_db_partition_stats p
                ON p.object_id = o.object_id AND p.index_id IN (0,1)
            JOIN sys.partitions pt ON pt.object_id = o.object_id AND pt.index_id IN (0,1)
            JOIN sys.allocation_units a ON a.container_id = pt.partition_id
            LEFT JOIN sys.dm_db_index_usage_stats us
                ON us.object_id = o.object_id AND us.database_id = DB_ID() AND us.index_id <= 1
            WHERE
                o.type = 'U'
                AND p.row_count > 10000
                AND (
                    COALESCE(us.last_user_update, us.last_system_update) < CAST(GETDATE() AS DATE)
                    OR us.last_user_update IS NULL
                )
            GROUP BY o.schema_id, o.name, p.row_count
            ORDER BY boyut_mb DESC
        """
        rows = self._fetchall(sql)
        if not rows:
            return [self._ok("FR-PIPE-01", "gunluk_yukleme", "Tüm tablolarda bugün veri hareketi var")]
        results = []
        for row in rows:
            results.append(MetricSchema(
                db_type        = self.db_type,
                host           = self.host,
                db_name        = self.db_name,
                kategori       = Kategori.PIPELINE,
                kontrol_kodu   = "FR-PIPE-01",
                kontrol_adi    = "gunluk_yukleme",
                sonuc          = Sonuc.WARNING,
                severity       = 2,
                etkilenen_obje = row[0],
                etkilenen_sayi = row[1],
                detay          = f"Bugün DML yok. Kayıt: {row[1]} | Boyut: {row[2]} MB",
            ))
        return results

    def _check_schema_changes(self) -> list[MetricSchema]:
        sql = """
            SELECT TOP 20
                SCHEMA_NAME(o.schema_id) + '.' + o.name AS obje,
                o.type_desc,
                o.modify_date
            FROM sys.objects o
            WHERE
                o.type IN ('U','V','P','FN','IF','TF')
                AND o.modify_date >= DATEADD(HOUR, -24, GETDATE())
                AND o.schema_id NOT IN (SELECT schema_id FROM sys.schemas WHERE name IN ('sys','INFORMATION_SCHEMA'))
            ORDER BY o.modify_date DESC
        """
        rows = self._fetchall(sql)
        if not rows:
            return [self._ok("FR-PIPE-04", "schema_degisikligi", "Son 24 saatte schema değişikliği yok")]
        results = []
        for row in rows:
            results.append(MetricSchema(
                db_type        = self.db_type,
                host           = self.host,
                db_name        = self.db_name,
                kategori       = Kategori.PIPELINE,
                kontrol_kodu   = "FR-PIPE-04",
                kontrol_adi    = "schema_degisikligi",
                sonuc          = Sonuc.WARNING,
                severity       = 2,
                etkilenen_obje = row[0],
                detay          = f"Tip: {row[1]} | Değişim: {row[2]}",
            ))
        return results

    def _check_large_queries(self) -> list[MetricSchema]:
        sql = """
            SELECT TOP 10
                qs.total_elapsed_time / qs.execution_count / 1000 AS ort_sure_ms,
                qs.total_logical_reads / qs.execution_count AS ort_logical_read,
                qs.execution_count,
                LEFT(st.text, 200) AS sorgu
            FROM sys.dm_exec_query_stats qs
            CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) st
            WHERE
                qs.execution_count > 0
                AND qs.total_elapsed_time / qs.execution_count / 1000 > 5000
            ORDER BY ort_sure_ms DESC
        """
        try:
            rows = self._fetchall(sql)
        except Exception:
            return [self._ok("FR-USER-04", "buyuk_sorgu", "sys.dm_exec_query_stats erişim yetkisi yok — atlandı")]
        if not rows:
            return [self._ok("FR-USER-04", "buyuk_sorgu", "5s+ ortalama süreli sorgu yok")]
        results = []
        for row in rows:
            sure_ms = row[0] or 0
            severity = 3 if sure_ms > 30000 else 2
            results.append(MetricSchema(
                db_type        = self.db_type,
                host           = self.host,
                db_name        = self.db_name,
                kategori       = Kategori.KULLANICI,
                kontrol_kodu   = "FR-USER-04",
                kontrol_adi    = "buyuk_sorgu",
                sonuc          = Sonuc.ERROR if severity == 3 else Sonuc.WARNING,
                severity       = severity,
                detay          = f"Ort süre: {sure_ms}ms | Logical reads: {row[1]} | Sorgu: {row[3]}",
            ))
        return results

    def _check_sensitive_columns(self) -> list[MetricSchema]:
        ddm_sql = """
            SELECT
                SCHEMA_NAME(o.schema_id) + '.' + o.name AS tablo,
                c.name AS kolon,
                c.system_type_id
            FROM sys.masked_columns mc
            JOIN sys.columns c ON c.object_id = mc.object_id AND c.column_id = mc.column_id
            JOIN sys.objects o ON o.object_id = mc.object_id
            WHERE mc.is_masked = 0
        """
        try:
            masked_rows = self._fetchall(ddm_sql)
        except Exception:
            masked_rows = None

        fallback_sql = f"""
            SELECT
                TABLE_SCHEMA + '.' + TABLE_NAME AS tablo,
                COLUMN_NAME,
                DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE LOWER(COLUMN_NAME) IN ({','.join(f"'{k}'" for k in HASSAS_KOLONLAR)})
        """
        col_rows = self._fetchall(fallback_sql)

        if masked_rows is not None:
            masked_set = {(r[0], r[1]) for r in masked_rows}
            unmasked = [(r[0], r[1], r[2]) for r in col_rows if (r[0], r[1]) not in masked_set]
        else:
            unmasked = col_rows

        if not unmasked:
            return [self._ok("FR-SEC-01", "hassas_kolon", "Maskelenmemiş hassas kolon adı yok")]
        results = []
        for row in unmasked:
            results.append(MetricSchema(
                db_type        = self.db_type,
                host           = self.host,
                db_name        = self.db_name,
                kategori       = Kategori.GUVENLIK,
                kontrol_kodu   = "FR-SEC-01",
                kontrol_adi    = "hassas_kolon",
                sonuc          = Sonuc.ERROR,
                severity       = 3,
                etkilenen_obje = f"{row[0]}.{row[1]}",
                detay          = f"Tip: {row[2]} — DDM maskesi eksik",
            ))
        return results

    def _check_offhours_queries(self) -> list[MetricSchema]:
        sql = """
            SELECT TOP 10
                r.session_id,
                s.login_name,
                r.start_time,
                r.total_elapsed_time / 1000 AS sure_sn,
                r.logical_reads,
                LEFT(st.text, 200) AS sorgu,
                DATEPART(HOUR, r.start_time) AS saat
            FROM sys.dm_exec_requests r
            JOIN sys.dm_exec_sessions s ON s.session_id = r.session_id
            CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) st
            WHERE
                r.status = 'running'
                AND r.logical_reads > 1000000
                AND (DATEPART(HOUR, GETDATE()) < 7 OR DATEPART(HOUR, GETDATE()) >= 20)
                AND s.is_user_process = 1
            ORDER BY r.logical_reads DESC
        """
        try:
            rows = self._fetchall(sql)
        except Exception:
            return [self._ok("FR-SEC-03", "mesai_disi_sorgu", "sys.dm_exec_requests erişim yetkisi yok — atlandı")]
        if not rows:
            return [self._ok("FR-SEC-03", "mesai_disi_sorgu", "Mesai dışı büyük sorgu tespit edilmedi")]
        results = []
        for row in rows:
            results.append(MetricSchema(
                db_type        = self.db_type,
                host           = self.host,
                db_name        = self.db_name,
                kategori       = Kategori.GUVENLIK,
                kontrol_kodu   = "FR-SEC-03",
                kontrol_adi    = "mesai_disi_sorgu",
                sonuc          = Sonuc.WARNING,
                severity       = 2,
                etkilenen_obje = f"session={row[0]} user={row[1]}",
                detay          = f"Saat: {row[6]}:00 | Süre: {row[3]}s | Reads: {row[4]} | {row[5]}",
            ))
        return results

    def _fetchall(self, sql: str) -> list:
        cur = self._conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cur.close()
        return rows

    def _fetchval(self, sql: str):
        cur = self._conn.cursor()
        cur.execute(sql)
        row = cur.fetchone()
        cur.close()
        return row[0] if row else None

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
    def _detect_driver() -> Optional[str]:
        if pyodbc is None:
            return None
        drivers = pyodbc.drivers()
        for preferred in ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"]:
            if preferred in drivers:
                return preferred
        for d in drivers:
            if "SQL Server" in d:
                return d
        return None
