"""
adapters/postgresql_adapter.py
==============================
PostgreSQL için referans adapter implementasyonu. Diğer adapter'lar bu dosyanın yapısını örnek alabilir:
bağlan, bağlantıyı kapat, sağlık kontrolü yap, metadata al ve kontrolleri çalıştır.
Kontroller pg_stat_* ve information_schema görünümlerini okur; veriye dokunmaz.
Sonuçlar core/metric_schema.MetricSchema olarak döner ve core/collector_engine tarafından işlenir.
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

    """PostgreSQL için referans adapter. Diğer adapter'lar bu dosyanın yapısını örnek alabilir: bağlan, sağlık kontrolü, metadata ve kontrol metotları. Kontroller pg_stat_* ve information_schema görünümlerini okur."""
    ADAPTER_VERSION = "1.0.0"

    def __init__(self, config: dict):
        """config: databases.yaml'daki bu veritabanının ayar sözlüğü. Bağlantı nesnesi başta None'dır; connect() çağrılınca dolar."""
        super().__init__(config)
        self._conn: Optional[object] = None

    def connect(self) -> None:
        """PostgreSQL'e bağlanır. Sunucu tarafında sorgu zaman aşımı (statement_timeout) da ayarlanır. Şifre veya yetki hatası AuthenticationError, zaman aşımı TimeoutError, diğer hatalar ConnectionError olarak fırlatılır."""
        creds = self.config.get("credentials", {})
        try:
            self._conn = psycopg2.connect(
                host            = self.host,
                port            = self.port or 5432,
                dbname          = self.db_name,
                user            = creds.get("user", ""),
                password        = creds.get("password", ""),
                connect_timeout = self.connect_timeout_s,
                # Sunucu tarafında her sorguya zaman sınırı koyar (milisaniye cinsinden). Uygulama takılsa bile veritabanı sorguyu kendisi iptal eder.
                options         = f"-c statement_timeout={self.query_timeout_s * 1000}",
            )
            # Monitör sadece okuma yaptığı için her sorgu hemen tamamlanır; elle işlem (transaction) yönetmeye gerek yoktur.
            self._conn.autocommit = True
            logger.info("PostgreSQL bağlantısı kuruldu: %s:%s/%s", self.host, self.port, self.db_name)
        except psycopg2.OperationalError as exc:
            # Hata metnine bakarak türünü ayırırız: şifre hatası kimlik doğrulama, timeout zaman aşımı, diğerleri genel bağlantı hatasıdır.
            msg = str(exc).lower()
            if "password" in msg or "authentication" in msg:
                raise AuthenticationError(str(exc), db_type=self.db_type, host=self.host, cause=exc)
            if "timeout" in msg:
                raise TimeoutError(str(exc), db_type=self.db_type, host=self.host, cause=exc)
            raise ConnectionError(str(exc), db_type=self.db_type, host=self.host, cause=exc)
        except Exception as exc:
            raise ConnectionError(str(exc), db_type=self.db_type, host=self.host, cause=exc)

    def disconnect(self) -> None:
        """Bağlantıyı kapatır. Kapatma sırasında hata olursa sadece uyarı yazılır; _conn her durumda None yapılır."""
        try:
            if self._conn and not self._conn.closed:
                self._conn.close()
        except Exception as exc:
            logger.warning("Bağlantı kapatma hatası: %s", exc)
        finally:
            self._conn = None

    def health_check(self) -> HealthResult:
        """SELECT 1 sorgusunu çalıştırıp süresini ölçer. Hata olursa exception fırlatmaz, is_healthy=False olan bir HealthResult döner."""
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
        """PostgreSQL sürümünü (SELECT version()) alıp DBMetadata olarak döner."""
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
        """Tüm kontrolleri sırayla çalıştırır. Her kontrol _safe_collect ile sarılır: biri hata verse bile diğerleri çalışmaya devam eder."""
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
        """FR-COST-01: 30 gündür okunmamış (seq ve idx scan yok) kullanıcı tablolarını bulur. Büyükten küçüğe en fazla 20 tablo listelenir. Sonuç yoksa tek bir OK kaydı döner."""
        # Son erişimi 30 günden eski veya hiç erişilmemiş tablolar. DİKKAT: pg_stat_* sayaçları sunucu yeniden başlayınca sıfırlanabilir.
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
        """FR-COST-02: Ölü satır (dead tuple) oranı %20'yi aşan ve en az 1000 ölü satırı olan tabloları bulur. Ölü satır çoksa VACUUM yetersiz demektir. Oran %40'ı aşarsa önem derecesi 3 olur."""
        # Ölü satır oranı yüksek tablolar. Ölü satır birikirse VACUUM çalışmamış ya da yetersiz demektir.
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
        """FR-COST-03: 1 GB'tan büyük ve partition edilmemiş tabloları listeler. Partition, büyük tabloyu parçalara bölerek sorgu ve bakımı hızlandırır."""
        # 1 GB (1073741824 bayt) üzeri ve partition edilmemiş tablolar.
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
        """FR-DQ-01: pg_stats içinden NULL oranı yarıdan fazla olan kolonları bulur. pg_stats'a erişim yoksa kontrol hata vermeden atlanır ve OK döner."""
        # pg_stats NULL oranı ANALYZE ile tahmin edilen bir değerdir; kesin sayı değildir.
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
        """FR-DQ-02: PK veya UNIQUE kısıtı olmayan, kayıt içeren tabloları bulur. Kontrol adı tekrar kaydı arar gibi görünse de gerçekte sadece kısıt eksikliğine bakar."""
        # DİKKAT: Kontrol adı tekrar kayıtlarını arar gibi görünür ama bu sorgu PK/UNIQUE kısıtı eksik tabloları bulur. contype 'p' primary key, 'u' unique anlamına gelir.
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
        """FR-PIPE-01: 10.000'den fazla satırı olan ama son bir gündür hiç INSERT almamış tabloları bulur. Veri yükleme işinin durduğunu gösterebilir."""
        # Büyük ama son bir gündür INSERT almamış tablolar. n_tup_ins istatistiği sayaç olduğu için sıfırlanmalara karşı dikkatli yorumlanmalıdır.
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
        """FR-SEC-01: Adı hassas veri gibi görünen kolonları (parola, kart no, TCKN, IBAN vb.) bulur. Sadece kolon adına bakar; veri içeriğini okumaz."""
        HASSAS = ["password","parola","sifre","passwd","credit_card","kredi_kart",
                  "kart_no","ssn","tc_kimlik","tckn","iban","banka","token","secret","api_key"]
        # Kolon adına bakılır; içerik taranmaz. Bu yüzden sadece bir ipucudur, kesin hassas veri kanıtı değildir.
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
        """FR-USER-01: pg_stat_activity üzerinden 60 saniyeden uzun süredir çalışan aktif sorguları bulur. En fazla 10 kayıt döner. Monitörün kendi sorguları hariç tutulur."""
        # 60 saniyeden uzun süren aktif sorgular. Bu sınırı aşan sorgular önem derecesi 3 (kritik) olarak raporlanır (300 sn).
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
        """Bir kontrolün sorunsuz olduğunu gösteren OK kaydı üretir. OK kaydında severity her zaman 1 olmalıdır (MetricSchema kuralı)."""
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
