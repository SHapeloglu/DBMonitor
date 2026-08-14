"""
adapters/oracle_adapter.py
==========================
Oracle Database adapter implementasyonu.
BRD Faz 5 — F5-01

K-03 kararı: AWR/ASH (Diagnostics Pack) lisansı OLMADAN çalışacak şekilde
tasarlandı. Yalnızca V$, DBA_*, ALL_* view'ları kullanılır.
AWR desteği ileride opsiyonel modül olarak eklenebilir.

Driver: python-oracledb (Thin mode — Oracle Client kurulumu gerekmez)
"""

from __future__ import annotations

import logging
import time
from typing import Optional

try:
    import oracledb
except ImportError:
    oracledb = None  # preflight_check.py yakalar

from core.base_adapter import (
    DBAdapter, HealthResult, DBMetadata,
    ConnectionError, AuthenticationError, QueryError, TimeoutError,
)
from core.metric_schema import MetricSchema, Sonuc, Kategori

logger = logging.getLogger(__name__)

HASSAS_KOLONLAR = [
    "PASSWORD", "PAROLA", "SIFRE", "PASSWD",
    "CREDIT_CARD", "KREDI_KART", "KART_NO",
    "SSN", "TC_KIMLIK", "TCKN", "IBAN", "BANKA",
    "TOKEN", "SECRET", "API_KEY",
]

# Oracle sistem schema'ları — tarama dışı
SISTEM_SCHEMAS = (
    "'SYS'", "'SYSTEM'", "'DBSNMP'", "'SYSMAN'", "'OUTLN'",
    "'MDSYS'", "'ORDSYS'", "'EXFSYS'", "'DMSYS'", "'WMSYS'",
    "'CTXSYS'", "'ANONYMOUS'", "'XDB'", "'XS$NULL'",
    "'APEX_PUBLIC_USER'", "'SPATIAL_CSW_ADMIN_USR'",
)
SISTEM_SCHEMAS_SQL = ", ".join(SISTEM_SCHEMAS)


class OracleAdapter(DBAdapter):

    ADAPTER_VERSION = "1.0.0"

    def __init__(self, config: dict):
        super().__init__(config)
        self._conn: Optional[object] = None
        # Oracle'da db_name yerine service_name kullanılabilir
        self._service_name = config.get("service_name", self.db_name)

    # ------------------------------------------------------------------
    # Bağlantı — Thin mode (Oracle Client gerekmez)
    # ------------------------------------------------------------------
    def connect(self) -> None:
        if oracledb is None:
            raise ConnectionError(
                "oracledb yüklü değil. 'pip install oracledb' çalıştırın.",
                db_type=self.db_type, host=self.host,
            )
        creds = self.config.get("credentials", {})
        try:
            self._conn = oracledb.connect(
                user        = creds.get("user", ""),
                password    = creds.get("password", ""),
                host        = self.host,
                port        = self.port or 1521,
                service_name = self._service_name,
            )
            # Sorgu timeout — Oracle JDBC tarzı (ms cinsinden değil, saniye)
            self._conn.call_timeout = self.query_timeout_s * 1000
            logger.info("Oracle bağlantısı kuruldu: %s:%s/%s",
                        self.host, self.port, self._service_name)
        except oracledb.DatabaseError as exc:
            error, = exc.args
            msg = str(error.message).lower() if hasattr(error, 'message') else str(exc).lower()
            if "ora-01017" in msg or "invalid username" in msg or "logon denied" in msg:
                raise AuthenticationError(str(exc), db_type=self.db_type, host=self.host, cause=exc)
            if "ora-12170" in msg or "timeout" in msg:
                raise TimeoutError(str(exc), db_type=self.db_type, host=self.host, cause=exc)
            raise ConnectionError(str(exc), db_type=self.db_type, host=self.host, cause=exc)
        except Exception as exc:
            raise ConnectionError(str(exc), db_type=self.db_type, host=self.host, cause=exc)

    def disconnect(self) -> None:
        try:
            if self._conn:
                self._conn.close()
        except Exception as exc:
            logger.warning("Oracle bağlantı kapatma hatası: %s", exc)
        finally:
            self._conn = None

    def health_check(self) -> HealthResult:
        try:
            t0 = time.perf_counter()
            with self._conn.cursor() as cur:
                cur.execute("SELECT 1 FROM DUAL")
                cur.fetchone()
            latency_ms = (time.perf_counter() - t0) * 1000
            return HealthResult(is_healthy=True, latency_ms=latency_ms)
        except Exception as exc:
            return HealthResult(is_healthy=False, latency_ms=0, message=str(exc))

    def get_metadata(self) -> DBMetadata:
        with self._conn.cursor() as cur:
            cur.execute("SELECT BANNER FROM V$VERSION WHERE ROWNUM = 1")
            version = cur.fetchone()[0]
        return DBMetadata(
            db_type         = "oracle",
            host            = self.host,
            port            = self.port or 1521,
            db_name         = self._service_name,
            version         = version,
            adapter_version = self.ADAPTER_VERSION,
        )

    # ------------------------------------------------------------------
    # Ana toplama metodu
    # ------------------------------------------------------------------
    def collect_metrics(self) -> list[MetricSchema]:
        metrics = []
        checks = [
            (self._check_unused_tables,      "FR-COST-01"),
            (self._check_large_segments,     "FR-COST-02"),
            (self._check_unpartitioned,      "FR-COST-03"),
            (self._check_null_ratio,         "FR-DQ-01"),
            (self._check_duplicates,         "FR-DQ-02"),
            (self._check_daily_load,         "FR-PIPE-01"),
            (self._check_sensitive_columns,  "FR-SEC-01"),
            (self._check_long_queries,       "FR-USER-01"),
        ]
        for fn, kod in checks:
            metrics.extend(self._safe_collect(fn, kod))
        return metrics

    # ------------------------------------------------------------------
    # FR-COST-01: Kullanılmayan tablolar
    # DBA_TAB_MODIFICATIONS — son DML tarihi (DBMS_STATS.FLUSH_DATABASE_MONITORING_INFO sonrası güvenilir)
    # ------------------------------------------------------------------
    def _check_unused_tables(self) -> list[MetricSchema]:
        sql = f"""
            SELECT * FROM (
                SELECT
                    t.OWNER || '.' || t.TABLE_NAME AS tablo,
                    m.TIMESTAMP AS son_dml,
                    ROUND(s.BYTES / 1024 / 1024, 2) AS boyut_mb
                FROM DBA_TABLES t
                LEFT JOIN DBA_TAB_MODIFICATIONS m
                    ON m.TABLE_OWNER = t.OWNER AND m.TABLE_NAME = t.TABLE_NAME
                LEFT JOIN DBA_SEGMENTS s
                    ON s.OWNER = t.OWNER AND s.SEGMENT_NAME = t.TABLE_NAME
                    AND s.SEGMENT_TYPE = 'TABLE'
                WHERE
                    t.OWNER NOT IN ({SISTEM_SCHEMAS_SQL})
                    AND (
                        m.TIMESTAMP < SYSDATE - 30
                        OR m.TIMESTAMP IS NULL
                    )
                ORDER BY s.BYTES DESC NULLS LAST
            ) WHERE ROWNUM <= 20
        """
        rows = self._fetchall(sql)
        if not rows:
            return [self._ok("FR-COST-01", "kullanilmayan_tablo", "30+ gün erişilmeyen tablo yok")]

        results = []
        for tablo, son_dml, boyut_mb in rows:
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
                detay          = f"Son DML: {son_dml} | Boyut: {boyut_mb} MB",
            ))
        return results

    # ------------------------------------------------------------------
    # FR-COST-02: Büyük segment / yüksek HWM (High Water Mark)
    # DBA_SEGMENTS — ayrılmış alan ile gerçek kullanım farkı
    # ------------------------------------------------------------------
    def _check_large_segments(self) -> list[MetricSchema]:
        sql = f"""
            SELECT * FROM (
                SELECT
                    s.OWNER || '.' || s.SEGMENT_NAME AS obje,
                    s.SEGMENT_TYPE,
                    ROUND(s.BYTES / 1024 / 1024, 2) AS boyut_mb,
                    t.NUM_ROWS,
                    ROUND(t.BLOCKS * 8 / 1024.0, 2) AS kullanilan_mb
                FROM DBA_SEGMENTS s
                LEFT JOIN DBA_TABLES t
                    ON t.OWNER = s.OWNER AND t.TABLE_NAME = s.SEGMENT_NAME
                WHERE
                    s.OWNER NOT IN ({SISTEM_SCHEMAS_SQL})
                    AND s.SEGMENT_TYPE IN ('TABLE', 'TABLE PARTITION')
                    AND s.BYTES > 500 * 1024 * 1024
                ORDER BY s.BYTES DESC
            ) WHERE ROWNUM <= 10
        """
        rows = self._fetchall(sql)
        if not rows:
            return [self._ok("FR-COST-02", "buyuk_segment", "500MB+ büyük segment yok")]

        results = []
        for obje, seg_tip, boyut_mb, num_rows, kullanilan_mb in rows:
            # HWM atığı: ayrılan alan kullanılanın 2 katından fazlaysa
            if kullanilan_mb and boyut_mb and boyut_mb > kullanilan_mb * 2:
                severity = 2
                detay = f"Boyut: {boyut_mb} MB | Kullanılan: {kullanilan_mb} MB | HWM atığı yüksek — SHRINK önerilir"
            else:
                severity = 2
                detay = f"Boyut: {boyut_mb} MB | Satır: {num_rows} | Tip: {seg_tip}"
            results.append(MetricSchema(
                db_type        = self.db_type,
                host           = self.host,
                db_name        = self.db_name,
                kategori       = Kategori.MALIYET,
                kontrol_kodu   = "FR-COST-02",
                kontrol_adi    = "buyuk_segment",
                sonuc          = Sonuc.WARNING,
                severity       = severity,
                etkilenen_obje = obje,
                detay          = detay,
            ))
        return results

    # ------------------------------------------------------------------
    # FR-COST-03: Partitionsiz büyük tablolar
    # ------------------------------------------------------------------
    def _check_unpartitioned(self) -> list[MetricSchema]:
        sql = f"""
            SELECT * FROM (
                SELECT
                    s.OWNER || '.' || s.SEGMENT_NAME AS tablo,
                    ROUND(s.BYTES / 1024 / 1024, 2) AS boyut_mb
                FROM DBA_SEGMENTS s
                JOIN DBA_TABLES t
                    ON t.OWNER = s.OWNER AND t.TABLE_NAME = s.SEGMENT_NAME
                WHERE
                    s.OWNER NOT IN ({SISTEM_SCHEMAS_SQL})
                    AND s.SEGMENT_TYPE = 'TABLE'
                    AND s.BYTES > 1024 * 1024 * 1024
                    AND t.PARTITIONED = 'NO'
                ORDER BY s.BYTES DESC
            ) WHERE ROWNUM <= 10
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

    # ------------------------------------------------------------------
    # FR-DQ-01: NULL oranı yüksek kolonlar
    # DBA_TAB_COL_STATISTICS — DBMS_STATS tarafından toplanan istatistikler
    # ------------------------------------------------------------------
    def _check_null_ratio(self) -> list[MetricSchema]:
        sql = f"""
            SELECT * FROM (
                SELECT
                    c.OWNER || '.' || c.TABLE_NAME AS tablo,
                    c.COLUMN_NAME,
                    ROUND(100.0 * c.NUM_NULLS / NULLIF(t.NUM_ROWS, 0), 1) AS null_pct
                FROM DBA_TAB_COL_STATISTICS c
                JOIN DBA_TABLES t
                    ON t.OWNER = c.OWNER AND t.TABLE_NAME = c.TABLE_NAME
                WHERE
                    c.OWNER NOT IN ({SISTEM_SCHEMAS_SQL})
                    AND t.NUM_ROWS > 0
                    AND c.NUM_NULLS > 0
                    AND (100.0 * c.NUM_NULLS / NULLIF(t.NUM_ROWS, 0)) > 50
                ORDER BY null_pct DESC
            ) WHERE ROWNUM <= 20
        """
        rows = self._fetchall(sql)
        if not rows:
            return [self._ok("FR-DQ-01", "null_orani", "NULL oranı yüksek kolon yok")]

        results = []
        for tablo, kolon, null_pct in rows:
            severity = 3 if (null_pct or 0) > 80 else 2
            results.append(MetricSchema(
                db_type        = self.db_type,
                host           = self.host,
                db_name        = self.db_name,
                kategori       = Kategori.KALITE,
                kontrol_kodu   = "FR-DQ-01",
                kontrol_adi    = "null_orani",
                sonuc          = Sonuc.ERROR if severity == 3 else Sonuc.WARNING,
                severity       = severity,
                etkilenen_obje = f"{tablo}.{kolon}",
                detay          = f"NULL oranı: %{null_pct} (istatistik bazlı)",
            ))
        return results

    # ------------------------------------------------------------------
    # FR-DQ-02: PK/UNIQUE kısıt eksik tablolar
    # ------------------------------------------------------------------
    def _check_duplicates(self) -> list[MetricSchema]:
        sql = f"""
            SELECT * FROM (
                SELECT
                    t.OWNER || '.' || t.TABLE_NAME AS tablo,
                    t.NUM_ROWS
                FROM DBA_TABLES t
                WHERE
                    t.OWNER NOT IN ({SISTEM_SCHEMAS_SQL})
                    AND t.NUM_ROWS > 0
                    AND NOT EXISTS (
                        SELECT 1 FROM DBA_CONSTRAINTS c
                        WHERE c.OWNER = t.OWNER
                          AND c.TABLE_NAME = t.TABLE_NAME
                          AND c.CONSTRAINT_TYPE IN ('P', 'U')
                          AND c.STATUS = 'ENABLED'
                    )
                ORDER BY t.NUM_ROWS DESC
            ) WHERE ROWNUM <= 10
        """
        rows = self._fetchall(sql)
        if not rows:
            return [self._ok("FR-DQ-02", "duplicate_kontrol", "PK/UNIQUE kısıt eksik tablo yok")]

        results = []
        for tablo, num_rows in rows:
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
                etkilenen_sayi = num_rows,
                detay          = f"Aktif PK/UNIQUE kısıt yok. Satır: {num_rows}",
            ))
        return results

    # ------------------------------------------------------------------
    # FR-PIPE-01: Bugün veri gelmeyen tablolar
    # DBA_TAB_MODIFICATIONS — bugün INSERT/UPDATE/DELETE yok
    # ------------------------------------------------------------------
    def _check_daily_load(self) -> list[MetricSchema]:
        sql = f"""
            SELECT * FROM (
                SELECT
                    t.OWNER || '.' || t.TABLE_NAME AS tablo,
                    t.NUM_ROWS,
                    m.TIMESTAMP AS son_dml
                FROM DBA_TABLES t
                LEFT JOIN DBA_TAB_MODIFICATIONS m
                    ON m.TABLE_OWNER = t.OWNER AND m.TABLE_NAME = t.TABLE_NAME
                WHERE
                    t.OWNER NOT IN ({SISTEM_SCHEMAS_SQL})
                    AND t.NUM_ROWS > 10000
                    AND (
                        TRUNC(m.TIMESTAMP) < TRUNC(SYSDATE)
                        OR m.TIMESTAMP IS NULL
                    )
                ORDER BY t.NUM_ROWS DESC
            ) WHERE ROWNUM <= 10
        """
        rows = self._fetchall(sql)
        if not rows:
            return [self._ok("FR-PIPE-01", "gunluk_yukleme", "Tüm tablolarda bugün veri hareketi var")]

        results = []
        for tablo, num_rows, son_dml in rows:
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
                etkilenen_sayi = num_rows,
                detay          = f"Bugün DML yok. Son: {son_dml} | Satır: {num_rows}",
            ))
        return results

    # ------------------------------------------------------------------
    # FR-SEC-01: Maskelenmemiş hassas kolonlar
    # Oracle Data Redaction (lisanssız): kolon adı bazlı tespit
    # REDACTION_COLUMNS view'ı varsa maskeleme durumu kontrol edilir
    # ------------------------------------------------------------------
    def _check_sensitive_columns(self) -> list[MetricSchema]:
        hassas_sql = ", ".join(f"'{k}'" for k in HASSAS_KOLONLAR)
        sql = f"""
            SELECT
                c.OWNER || '.' || c.TABLE_NAME AS tablo,
                c.COLUMN_NAME,
                c.DATA_TYPE
            FROM DBA_TAB_COLUMNS c
            WHERE
                c.OWNER NOT IN ({SISTEM_SCHEMAS_SQL})
                AND UPPER(c.COLUMN_NAME) IN ({hassas_sql})
            ORDER BY c.OWNER, c.TABLE_NAME, c.COLUMN_NAME
        """
        rows = self._fetchall(sql)
        if not rows:
            return [self._ok("FR-SEC-01", "hassas_kolon", "Hassas kolon adı tespit edilmedi")]

        # REDACTION_COLUMNS mevcut mu? (Oracle Advanced Security / Data Redaction)
        try:
            redacted = self._fetchall(
                "SELECT OBJECT_OWNER || '.' || OBJECT_NAME AS tablo, COLUMN_NAME FROM REDACTION_COLUMNS"
            )
            redacted_set = {(r[0], r[1]) for r in redacted}
        except Exception:
            redacted_set = set()  # view yoksa tümünü raporla

        results = []
        for tablo, kolon, veri_tipi in rows:
            if (tablo, kolon) in redacted_set:
                continue  # Data Redaction aktif — OK
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
                detay          = f"Tip: {veri_tipi} — Data Redaction kontrolü yapılmalı",
            ))

        if not results:
            return [self._ok("FR-SEC-01", "hassas_kolon", "Tüm hassas kolonlar redact edilmiş")]
        return results

    # ------------------------------------------------------------------
    # FR-USER-01: Uzun süren sorgular
    # V$SESSION + V$SQL — lisanssız, her Oracle'da çalışır
    # ------------------------------------------------------------------
    def _check_long_queries(self) -> list[MetricSchema]:
        sql = """
            SELECT * FROM (
                SELECT
                    s.SID,
                    s.USERNAME,
                    ROUND((SYSDATE - s.LOGON_TIME) * 86400 - s.LAST_CALL_ET) AS bekleme_sn,
                    s.LAST_CALL_ET AS sure_sn,
                    SUBSTR(q.SQL_TEXT, 1, 200) AS sorgu
                FROM V$SESSION s
                LEFT JOIN V$SQL q ON q.SQL_ID = s.SQL_ID
                WHERE
                    s.STATUS = 'ACTIVE'
                    AND s.TYPE = 'USER'
                    AND s.LAST_CALL_ET > 60
                    AND s.USERNAME IS NOT NULL
                ORDER BY s.LAST_CALL_ET DESC
            ) WHERE ROWNUM <= 10
        """
        try:
            rows = self._fetchall(sql)
        except Exception:
            return [self._ok("FR-USER-01", "uzun_sorgu", "V$SESSION erişim yetkisi yok — atlandı")]

        if not rows:
            return [self._ok("FR-USER-01", "uzun_sorgu", "60s+ süren aktif sorgu yok")]

        results = []
        for sid, username, bekleme, sure, sorgu in rows:
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
                etkilenen_obje = f"sid={sid} user={username}",
                detay          = f"Süre: {sure}s | Sorgu: {sorgu}",
            ))
        return results

    # ------------------------------------------------------------------
    # Yardımcı metodlar
    # ------------------------------------------------------------------
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
