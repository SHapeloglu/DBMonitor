"""
core/retention_manager.py
=========================
24 ay aktif saklama → cold storage arşiv.
DB'nin TTL veya partition özelliğine bağımlılık yok.
Her ay başı CollectorEngine tarafından tetiklenir.
"""

from __future__ import annotations

import gzip
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psycopg2
import psycopg2.extras
import yaml

logger = logging.getLogger(__name__)


class RetentionManager:
    """
    dwh_health_log tablosundaki eski kayıtları arşive taşır.

    Akış:
      1. cutoff tarihi hesapla (şimdi - active_months)
      2. Eski kayıtları dwh_health_log_archive'e INSERT et
      3. Aktif tablodan DELETE et
      4. Yeni ay partition'ını oluştur (add_monthly_partition prosedürü)
      5. Arşiv backend'ine yaz (local / s3 / azure)
    """

    def __init__(self, config_path: str = "config/retention.yaml",
                 db_config: Optional[dict] = None):
        self._config_path = Path(config_path)
        self._db_config   = db_config  # databases.yaml'daki monitor DB config'i

        # Defaults
        self.active_months    = 24
        self.archive_backend  = "local"
        self.archive_path     = "/opt/dwh-db-monitor/archive"
        self.batch_size       = 10_000
        self.dry_run          = False

        if self._config_path.exists():
            self._load_config()
        else:
            logger.warning("retention.yaml bulunamadı, varsayılan değerler kullanılıyor.")

    def _load_config(self) -> None:
        with open(self._config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        self.active_months   = cfg.get("active_months", 24)
        self.archive_backend = cfg.get("archive_backend", "local")
        self.archive_path    = cfg.get("archive_path", "/opt/dwh-db-monitor/archive")
        self.batch_size      = cfg.get("batch_size", 10_000)
        self.dry_run         = cfg.get("dry_run", False)
        logger.info(
            "RetentionManager config: active_months=%d, backend=%s, dry_run=%s",
            self.active_months, self.archive_backend, self.dry_run,
        )

    # ------------------------------------------------------------------
    # Ana giriş noktası
    # ------------------------------------------------------------------

    def run(self, conn=None) -> dict:
        """
        Retention döngüsünü çalıştır.

        conn: açık psycopg2 connection (verilmezse db_config'den açar)

        Dönüş:
          {"archived": int, "deleted": int, "partition_added": bool}
        """
        own_conn = conn is None
        if own_conn:
            conn = self._open_connection()

        result = {"archived": 0, "deleted": 0, "partition_added": False}

        try:
            cutoff = self._cutoff_date()
            logger.info("Retention başladı. Cutoff: %s", cutoff.isoformat())

            # 1. Archive'e taşı
            archived = self._archive_old_rows(conn, cutoff)
            result["archived"] = archived

            # 2. Aktif tablodan sil
            if not self.dry_run:
                deleted = self._delete_old_rows(conn, cutoff)
                result["deleted"] = deleted
                conn.commit()
                logger.info("Retention tamamlandı: %d arşivlendi, %d silindi.", archived, deleted)
            else:
                conn.rollback()
                logger.info("[DRY RUN] %d kayıt arşivlenecekti.", archived)

            # 3. Gelecek ay partition'ını oluştur
            added = self._ensure_next_partition(conn)
            result["partition_added"] = added

        except Exception as exc:
            conn.rollback()
            logger.exception("Retention hatası: %s", exc)
            raise
        finally:
            if own_conn:
                conn.close()

        return result

    # ------------------------------------------------------------------
    # Archive işlemleri
    # ------------------------------------------------------------------

    def _archive_old_rows(self, conn, cutoff: datetime) -> int:
        """Eski kayıtları dwh_health_log_archive'e kopyala."""
        sql = """
            INSERT INTO monitor.dwh_health_log_archive
                (kontrol_tarihi, db_type, host, db_name, kategori,
                 kontrol_kodu, kontrol_adi, sonuc, severity,
                 etkilenen_obje, etkilened_sayi, detay, arsiv_tarihi)
            SELECT
                kontrol_tarihi, db_type, host, db_name, kategori,
                kontrol_kodu, kontrol_adi, sonuc, severity,
                etkilenen_obje, etkilened_sayi, detay, NOW()
            FROM monitor.dwh_health_log
            WHERE kontrol_tarihi < %s
            ON CONFLICT DO NOTHING
        """
        if self.dry_run:
            # Sadece sayı döndür
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM monitor.dwh_health_log WHERE kontrol_tarihi < %s",
                    (cutoff,)
                )
                return cur.fetchone()[0]

        total = 0
        while True:
            with conn.cursor() as cur:
                # Batch INSERT
                cur.execute(f"""
                    INSERT INTO monitor.dwh_health_log_archive
                        (kontrol_tarihi, db_type, host, db_name, kategori,
                         kontrol_kodu, kontrol_adi, sonuc, severity,
                         etkilenen_obje, etkilenen_sayi, detay, arsiv_tarihi)
                    SELECT
                        kontrol_tarihi, db_type, host, db_name, kategori,
                        kontrol_kodu, kontrol_adi, sonuc, severity,
                        etkilenen_obje, etkilenen_sayi, detay, NOW()
                    FROM monitor.dwh_health_log
                    WHERE kontrol_tarihi < %s
                    LIMIT %s
                    ON CONFLICT DO NOTHING
                """, (cutoff, self.batch_size))
                batch = cur.rowcount
            total += batch
            conn.commit()
            logger.debug("Archive batch: %d kayıt taşındı (toplam: %d)", batch, total)
            if batch < self.batch_size:
                break

        # Local/S3/Azure'a yaz
        self._export_to_backend(conn, cutoff)
        return total

    def _delete_old_rows(self, conn, cutoff: datetime) -> int:
        """Archive'e taşınan eski kayıtları aktif tablodan sil."""
        total = 0
        while True:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM monitor.dwh_health_log
                    WHERE id IN (
                        SELECT id FROM monitor.dwh_health_log
                        WHERE kontrol_tarihi < %s
                        LIMIT %s
                    )
                """, (cutoff, self.batch_size))
                batch = cur.rowcount
            total += batch
            conn.commit()
            if batch == 0:
                break
            logger.debug("Delete batch: %d kayıt silindi (toplam: %d)", batch, total)
        return total

    # ------------------------------------------------------------------
    # Partition yönetimi
    # ------------------------------------------------------------------

    def _ensure_next_partition(self, conn) -> bool:
        """Gelecek ay için partition oluştur (yoksa)."""
        from datetime import timedelta
        next_month = (datetime.now(timezone.utc).replace(day=1) +
                      timedelta(days=32)).replace(day=1)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "CALL monitor.add_monthly_partition(%s)",
                    (next_month.date(),)
                )
            conn.commit()
            logger.info("Partition kontrol edildi: %s", next_month.strftime("%Y-%m"))
            return True
        except Exception as exc:
            conn.rollback()
            logger.error("Partition oluşturma hatası: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Backend export
    # ------------------------------------------------------------------

    def _export_to_backend(self, conn, cutoff: datetime) -> None:
        """Arşivlenen kayıtları backend'e yaz."""
        if self.archive_backend == "local":
            self._export_local(conn, cutoff)
        elif self.archive_backend == "s3":
            self._export_s3(conn, cutoff)
        elif self.archive_backend == "azure_blob":
            self._export_azure(conn, cutoff)
        else:
            logger.warning("Bilinmeyen archive_backend: %s", self.archive_backend)

    def _export_local(self, conn, cutoff: datetime) -> None:
        """Eski kayıtları gzip'li JSONL olarak diske yaz."""
        archive_dir = Path(self.archive_path)
        archive_dir.mkdir(parents=True, exist_ok=True)

        month_str = cutoff.strftime("%Y%m")
        out_path  = archive_dir / f"dwh_health_{month_str}.jsonl.gz"

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM monitor.dwh_health_log_archive WHERE arsiv_tarihi >= NOW() - INTERVAL '1 hour'",
            )
            rows = cur.fetchall()

        if not rows:
            return

        with gzip.open(out_path, "at", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(dict(row), default=str) + "\n")

        logger.info("Local archive yazıldı: %s (%d kayıt)", out_path, len(rows))

    def _export_s3(self, conn, cutoff: datetime) -> None:
        """S3'e yükle — boto3 gerekli."""
        try:
            import boto3
        except ImportError:
            logger.error("boto3 kurulu değil. pip install boto3")
            return
        logger.info("S3 export henüz tam implemente edilmedi.")

    def _export_azure(self, conn, cutoff: datetime) -> None:
        """Azure Blob'a yükle — azure-storage-blob gerekli."""
        try:
            from azure.storage.blob import BlobServiceClient
        except ImportError:
            logger.error("azure-storage-blob kurulu değil.")
            return
        logger.info("Azure export henüz tam implemente edilmedi.")

    # ------------------------------------------------------------------
    # Yardımcı
    # ------------------------------------------------------------------

    def _cutoff_date(self) -> datetime:
        from dateutil.relativedelta import relativedelta
        return datetime.now(timezone.utc) - relativedelta(months=self.active_months)

    def _open_connection(self):
        if not self._db_config:
            raise ValueError("db_config verilmedi ve bağlantı açılamıyor.")
        creds = self._db_config.get("credentials", {})
        return psycopg2.connect(
            host     = self._db_config["host"],
            port     = self._db_config.get("port", 5432),
            dbname   = self._db_config["db_name"],
            user     = creds.get("user", "dquser"),
            password = creds.get("password", ""),
            connect_timeout = self._db_config.get("connect_timeout_s", 10),
        )
