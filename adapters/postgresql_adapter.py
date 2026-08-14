"""
adapters/postgresql_adapter.py
==============================
PostgreSQL referans adapter implementasyonu.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import psycopg2
import psycopg2.extras

from core.base_adapter import (
    DBAdapter, HealthResult, DBMetadata,
    ConnectionError, AuthenticationError, QueryError, TimeoutError,
)
from core.metric_schema import MetricSchema, Sonuc, Kategori

logger = logging.getLogger(__name__)


class PostgreSQLAdapter(DBAdapter):

    ADAPTER_VERSION = "1.0.0"

    def __init__(self, config: dict):
        super().__init__(config)
        self._conn: Optional[object] = None

    def connect(self) -> None:
        creds = self.config.get("credentials", {})
        try:
            self._conn = psycopg2.connect(
                host            = self.host,
                port            = self.port or 5432,
                dbname          = self.db_name,
                user            = creds.get("user", ""),
                password        = creds.get("password", ""),
                connect_timeout = self.connect_timeout_s,
                options         = f"-c statement_timeout={self.query_timeout_s * 1000}",
            )
            self._conn.autocommit = True
            logger.info("PostgreSQL bağlantısı kuruldu: %s:%s/%s", self.host, self.port, self.db_name)
        except psycopg2.OperationalError as exc:
            msg = str(exc).lower()
            if "password" in msg or "authentication" in msg:
                raise AuthenticationError(str(exc), db_type=self.db_type, host=self.host, cause=exc)
            if "timeout" in msg:
                raise TimeoutError(str(exc), db_type=self.db_type, host=self.host, cause=exc)
            raise ConnectionError(str(exc), db_type=self.db_type, host=self.host, cause=exc)
        except Exception as exc:
            raise ConnectionError(str(exc), db_type=self.db_type, host=self.host, cause=exc)

    def disconnect(self) -> None:
        try:
            if self._conn and not self._conn.closed:
                self._conn.close()
        except Exception as exc:
            logger.warning("Bağlantı kapatma hatası: %s", exc)
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
            cur.execute("SELECT version()")
            version = cur.fetchone()[0]
        return DBMetadata(
            db_type         = "postgresql",
            host            = self.host,
            port            = self.port or 5432,
            db_name         = self.db_name,
            version         = version,
            adapter_version = self.ADAPTER_VERSION,
        )

    def collect_metrics(self) -> list[MetricSchema]:
        metrics = []
        checks = [
            (self._check_unused_tables,     "FR-COST-01"),
            (self._check_table_bloat,       "FR-COST-02"),
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

    # ------------------------------------------------------------------
    # FR-COST-01: Kullanılmayan tablolar
    # ------------------------------------------------------------------
    def _check_unused_tables(self) -> list[MetricSchema]:
        sql = """
            SELECT
                schemaname || '.' || relname AS tablo,
                GREATEST(last_seq_scan, last_idx_scan) AS son_erisim,
                pg_size_pretty(pg_total_relation_size(relid)) AS boyut
            FROM pg_stat_user_tables
            WHERE
                schemaname NOT IN ('pg_catalog','information_schema','monitor')
                AND (
                    GREATEST(last_seq_scan, last_idx_scan) < NOW() - INTERVAL '30 days'
                    OR (last_seq_scan IS NULL AND last_idx_scan IS NULL)
                )
            ORDER BY pg_total_relation_size(relid) DESC
            LIMIT 20
        """
        results = []
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()

        if not rows:
            return [self._ok("FR-COST-01", "kullanilmayan_tablo", "30+ gün erişilmeyen tablo yok")]

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
                etkilenen_obje = row["tablo"],
                detay          = f"Son erişim: {row['son_erisim']} | Boyut: {row['boyut']}",
            ))
        return results

    # ------------------------------------------------------------------
    # FR-COST-02: Tablo bloat
    # ------------------------------------------------------------------
    def _check_table_bloat(self) -> list[MetricSchema]:
        sql = """
            SELECT
                schemaname || '.' || relname AS tablo,
                pg_size_pretty(pg_total_relation_size(relid)) AS toplam_boyut,
                n_dead_tup,
                n_live_tup,
                CASE WHEN (n_dead_tup + n_live_tup) > 0
                     THEN ROUND(100.0 * n_dead_tup / (n_dead_tup + n_live_tup), 1)
                     ELSE 0 END AS bloat_pct
            FROM pg_stat_user_tables
            WHERE
                schemaname NOT IN ('pg_catalog','information_schema','monitor')
                AND n_dead_tup > 1000
                AND (n_dead_tup::float / NULLIF(n_live_tup + n_dead_tup, 0)) > 0.2
            ORDER BY bloat_pct DESC
            LIMIT 10
        """
        results = []
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()

        if not rows:
            return [self._ok("FR-COST-02", "tablo_bloat", "Anormal bloat tespit edilmedi")]

        for row in rows:
            severity = 3 if row["bloat_pct"] > 40 else 2
            results.append(MetricSchema(
                db_type        = self.db_type,
                host           = self.host,
                db_name        = self.db_name,
                kategori       = Kategori.MALIYET,
                kontrol_kodu   = "FR-COST-02",
                kontrol_adi    = "tablo_bloat",
                sonuc          = Sonuc.ERROR if severity == 3 else Sonuc.WARNING,
                severity       = severity,
                etkilenen_obje = row["tablo"],
                detay          = f"Bloat: %{row['bloat_pct']} | Boyut: {row['toplam_boyut']}",
            ))
        return results

    # ------------------------------------------------------------------
    # FR-COST-03: Partitionsiz büyük tablolar
    # ------------------------------------------------------------------
    def _check_unpartitioned(self) -> list[MetricSchema]:
        sql = """
            SELECT
                s.schemaname || '.' || s.relname AS tablo,
                pg_size_pretty(pg_total_relation_size(s.relid)) AS boyut,
                pg_total_relation_size(s.relid) AS boyut_bytes
            FROM pg_stat_user_tables s
            WHERE
                s.schemaname NOT IN ('pg_catalog','information_schema','monitor')
                AND NOT EXISTS (
                    SELECT 1 FROM pg_partitioned_table pt
                    JOIN pg_class c ON c.oid = pt.partrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = s.schemaname AND c.relname = s.relname
                )
                AND pg_total_relation_size(s.relid) > 1073741824
            ORDER BY boyut_bytes DESC
            LIMIT 10
        """
        results = []
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()

        if not rows:
            return [self._ok("FR-COST-03", "partitionsiz_buyuk_tablo", "1GB+ partitionsiz tablo yok")]

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
                etkilenen_obje = row["tablo"],
                detay          = f"Boyut: {row['boyut']} — partition önerilir",
            ))
        return results

    # ------------------------------------------------------------------
    # FR-DQ-01: NULL oranı yüksek kolonlar
    # ------------------------------------------------------------------
    def _check_null_ratio(self) -> list[MetricSchema]:
        sql = """
            SELECT
                schemaname || '.' || tablename AS tablo,
                attname AS kolon,
                null_frac
            FROM pg_stats
            WHERE
                schemaname NOT IN ('pg_catalog','information_schema','monitor')
                AND null_frac > 0.5
            ORDER BY null_frac DESC
            LIMIT 20
        """
        results = []
        try:
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql)
                rows = cur.fetchall()
        except Exception:
            return [self._ok("FR-DQ-01", "null_orani", "pg_stats erişim yetkisi yok — atlandı")]

        if not rows:
            return [self._ok("FR-DQ-01", "null_orani", "NULL oranı yüksek kolon yok")]

        for row in rows:
            pct = round(row["null_frac"] * 100, 1)
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
                etkilenen_obje = f"{row['tablo']}.{row['kolon']}",
                detay          = f"NULL oranı: %{pct}",
            ))
        return results

    # ------------------------------------------------------------------
    # FR-DQ-02: PK/UNIQUE kısıt eksik tablolar
    # ------------------------------------------------------------------
    def _check_duplicates(self) -> list[MetricSchema]:
        sql = """
            SELECT
                s.schemaname || '.' || s.relname AS tablo,
                s.n_live_tup AS kayit_sayisi
            FROM pg_stat_user_tables s
            WHERE
                s.schemaname NOT IN ('pg_catalog','information_schema','monitor')
                AND s.n_live_tup > 0
                AND NOT EXISTS (
                    SELECT 1 FROM pg_constraint c
                    JOIN pg_class cl ON cl.oid = c.conrelid
                    JOIN pg_namespace n ON n.oid = cl.relnamespace
                    WHERE n.nspname = s.schemaname
                      AND cl.relname = s.relname
                      AND c.contype IN ('p','u')
                )
            ORDER BY s.n_live_tup DESC
            LIMIT 10
        """
        results = []
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()

        if not rows:
            return [self._ok("FR-DQ-02", "duplicate_kontrol", "PK/UNIQUE kısıt eksik tablo yok")]

        for row in rows:
            results.append(MetricSchema(
                db_type        = self.db_type,
                host           = self.host,
                db_name        = self.db_name,
                kategori       = Kategori.KALITE,
                kontrol_kodu   = "FR-DQ-02",
                kontrol_adi    = "duplicate_kontrol",
                sonuc          = Sonuc.WARNING,
                severity       = 2,
                etkilenen_obje = row["tablo"],
                etkilenen_sayi = row["kayit_sayisi"],
                detay          = f"PK/UNIQUE kısıt yok. Kayıt: {row['kayit_sayisi']}",
            ))
        return results

    # ------------------------------------------------------------------
    # FR-PIPE-01: Bugün veri gelmeyen tablolar
    # ------------------------------------------------------------------
    def _check_daily_load(self) -> list[MetricSchema]:
        sql = """
            SELECT
                schemaname || '.' || relname AS tablo,
                n_tup_ins AS bugun_insert,
                last_autoanalyze
            FROM pg_stat_user_tables
            WHERE
                schemaname NOT IN ('pg_catalog','information_schema','monitor')
                AND n_live_tup > 10000
                AND n_tup_ins = 0
                AND (last_autoanalyze < NOW() - INTERVAL '1 day' OR last_autoanalyze IS NULL)
            ORDER BY n_live_tup DESC
            LIMIT 10
        """
        results = []
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()

        if not rows:
            return [self._ok("FR-PIPE-01", "gunluk_yukleme", "Tüm tablolarda bugün veri hareketi var")]

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
                etkilenen_obje = row["tablo"],
                detay          = f"Bugün INSERT yok. Son analyze: {row['last_autoanalyze']}",
            ))
        return results

    # ------------------------------------------------------------------
    # FR-SEC-01: Maskelenmemiş hassas kolon adları
    # ------------------------------------------------------------------
    def _check_sensitive_columns(self) -> list[MetricSchema]:
        HASSAS = ["password","parola","sifre","passwd","credit_card","kredi_kart",
                  "kart_no","ssn","tc_kimlik","tckn","iban","banka","token","secret","api_key"]
        sql = """
            SELECT
                table_schema || '.' || table_name AS tablo,
                column_name,
                data_type
            FROM information_schema.columns
            WHERE
                table_schema NOT IN ('pg_catalog','information_schema','monitor')
                AND LOWER(column_name) = ANY(%s)
            ORDER BY table_schema, table_name, column_name
            LIMIT 30
        """
        results = []
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (HASSAS,))
            rows = cur.fetchall()

        if not rows:
            return [self._ok("FR-SEC-01", "hassas_kolon", "Maskelenmemiş hassas kolon adı yok")]

        for row in rows:
            results.append(MetricSchema(
                db_type        = self.db_type,
                host           = self.host,
                db_name        = self.db_name,
                kategori       = Kategori.GUVENLIK,
                kontrol_kodu   = "FR-SEC-01",
                kontrol_adi    = "hassas_kolon",
                sonuc          = Sonuc.ERROR,
                severity       = 3,
                etkilenen_obje = f"{row['tablo']}.{row['column_name']}",
                detay          = f"Tip: {row['data_type']} — maskeleme kontrol edilmeli",
            ))
        return results

    # ------------------------------------------------------------------
    # FR-USER-01: Uzun süren sorgular
    # ------------------------------------------------------------------
    def _check_long_queries(self) -> list[MetricSchema]:
        sql = """
            SELECT
                pid,
                usename,
                EXTRACT(EPOCH FROM (NOW() - query_start)) AS sure_sn,
                LEFT(query, 200) AS sorgu
            FROM pg_stat_activity
            WHERE
                state = 'active'
                AND query_start < NOW() - INTERVAL '60 seconds'
                AND query NOT ILIKE '%pg_stat_activity%'
            ORDER BY sure_sn DESC
            LIMIT 10
        """
        results = []
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()

        if not rows:
            return [self._ok("FR-USER-01", "uzun_sorgu", "60s+ süren aktif sorgu yok")]

        for row in rows:
            sure = round(row["sure_sn"] or 0, 1)
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
                etkilenen_obje = f"pid={row['pid']} user={row['usename']}",
                detay          = f"Süre: {sure}s | Sorgu: {row['sorgu']}",
            ))
        return results

    # ------------------------------------------------------------------
    # Yardımcı
    # ------------------------------------------------------------------
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
