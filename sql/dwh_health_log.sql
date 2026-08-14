-- =============================================================================
-- dwh_health_log — DWH Sağlık İzleme Ana Tablosu
-- PostgreSQL 16
-- DB: dwhmonitor
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS monitor;

DO $$ BEGIN
    CREATE TYPE monitor.sonuc_tip AS ENUM ('OK', 'WARNING', 'ERROR');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE monitor.kategori_tip AS ENUM (
        'maliyet', 'kalite', 'pipeline', 'kullanici', 'guvenlik', 'sistem'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS monitor.dwh_health_log (
    id               BIGSERIAL        NOT NULL,
    kontrol_tarihi   TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    db_type          VARCHAR(20)      NOT NULL,
    host             VARCHAR(255)     NOT NULL,
    db_name          VARCHAR(255)     NOT NULL,
    kategori         monitor.kategori_tip  NOT NULL,
    kontrol_kodu     VARCHAR(30)      NOT NULL,
    kontrol_adi      VARCHAR(100)     NOT NULL,
    sonuc            monitor.sonuc_tip     NOT NULL,
    severity         SMALLINT         NOT NULL CHECK (severity BETWEEN 1 AND 3),
    etkilenen_obje   VARCHAR(255),
    etkilenen_sayi   INTEGER          CHECK (etkilenen_sayi >= 0),
    detay            TEXT,
    CONSTRAINT dwh_health_log_pkey PRIMARY KEY (id, kontrol_tarihi)
) PARTITION BY RANGE (kontrol_tarihi);

CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2025_01 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2025_02 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2025-02-01') TO ('2025-03-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2025_03 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2025-03-01') TO ('2025-04-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2025_04 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2025-04-01') TO ('2025-05-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2025_05 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2025-05-01') TO ('2025-06-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2025_06 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2025-06-01') TO ('2025-07-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2025_07 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2025-07-01') TO ('2025-08-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2025_08 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2025-08-01') TO ('2025-09-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2025_09 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2025-09-01') TO ('2025-10-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2025_10 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2025-10-01') TO ('2025-11-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2025_11 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2025-11-01') TO ('2025-12-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2025_12 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2026_01 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2026_02 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2026_03 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2026_04 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2026_05 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2026_06 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2026_07 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2026_08 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2026_09 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2026_10 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2026_11 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_2026_12 PARTITION OF monitor.dwh_health_log FOR VALUES FROM ('2026-12-01') TO ('2027-01-01');

CREATE INDEX IF NOT EXISTS idx_dwh_health_log_tarihi_sonuc ON monitor.dwh_health_log (kontrol_tarihi DESC, sonuc) WHERE sonuc IN ('WARNING', 'ERROR');
CREATE INDEX IF NOT EXISTS idx_dwh_health_log_host_db ON monitor.dwh_health_log (host, db_name, kontrol_tarihi DESC);
CREATE INDEX IF NOT EXISTS idx_dwh_health_log_kontrol_kodu ON monitor.dwh_health_log (kontrol_kodu, kontrol_tarihi DESC);
CREATE INDEX IF NOT EXISTS idx_dwh_health_log_kategori ON monitor.dwh_health_log (kategori, kontrol_tarihi DESC);
CREATE INDEX IF NOT EXISTS idx_dwh_health_log_severity ON monitor.dwh_health_log (severity, kontrol_tarihi DESC) WHERE severity >= 2;

CREATE TABLE IF NOT EXISTS monitor.dwh_health_log_archive (
    LIKE monitor.dwh_health_log INCLUDING ALL,
    arsiv_tarihi TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dwh_health_log_archive_tarihi ON monitor.dwh_health_log_archive (kontrol_tarihi DESC);

CREATE OR REPLACE VIEW monitor.v_son_24s_ozet AS
SELECT db_type, host, db_name, kategori, sonuc, severity, COUNT(*) AS adet, MAX(kontrol_tarihi) AS son_kontrol
FROM monitor.dwh_health_log
WHERE kontrol_tarihi >= NOW() - INTERVAL '24 hours'
GROUP BY db_type, host, db_name, kategori, sonuc, severity
ORDER BY severity DESC, adet DESC;

CREATE OR REPLACE VIEW monitor.v_aktif_sorunlar AS
SELECT kontrol_tarihi, db_type, host, db_name, kategori, kontrol_kodu, kontrol_adi, sonuc, severity, etkilenen_obje, etkilenen_sayi, detay
FROM monitor.dwh_health_log
WHERE sonuc = 'ERROR' AND kontrol_tarihi >= NOW() - INTERVAL '1 hour'
ORDER BY severity DESC, kontrol_tarihi DESC;

CREATE OR REPLACE VIEW monitor.v_trend_7gun AS
SELECT DATE_TRUNC('day', kontrol_tarihi) AS gun, kontrol_kodu, kontrol_adi, db_type, sonuc, COUNT(*) AS adet
FROM monitor.dwh_health_log
WHERE kontrol_tarihi >= NOW() - INTERVAL '7 days'
GROUP BY 1, 2, 3, 4, 5
ORDER BY gun DESC, adet DESC;

CREATE OR REPLACE PROCEDURE monitor.add_monthly_partition(target_month DATE)
LANGUAGE plpgsql AS $$
DECLARE
    partition_name TEXT;
    start_date     DATE;
    end_date       DATE;
BEGIN
    start_date     := DATE_TRUNC('month', target_month);
    end_date       := start_date + INTERVAL '1 month';
    partition_name := 'dwh_health_log_' || TO_CHAR(start_date, 'YYYY_MM');
    IF NOT EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'monitor' AND c.relname = partition_name
    ) THEN
        EXECUTE FORMAT(
            'CREATE TABLE monitor.%I PARTITION OF monitor.dwh_health_log FOR VALUES FROM (%L) TO (%L)',
            partition_name, start_date, end_date
        );
        RAISE NOTICE 'Partition oluşturuldu: monitor.%', partition_name;
    ELSE
        RAISE NOTICE 'Partition zaten mevcut: monitor.%', partition_name;
    END IF;
END;
$$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dwh_monitor_writer') THEN
        CREATE ROLE dwh_monitor_writer LOGIN PASSWORD 'changeme_writer';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dwh_monitor_reader') THEN
        CREATE ROLE dwh_monitor_reader LOGIN PASSWORD 'changeme_reader';
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Rol oluşturma atlandı: %', SQLERRM;
END $$;

GRANT USAGE ON SCHEMA monitor TO dwh_monitor_writer, dwh_monitor_reader;
GRANT INSERT ON monitor.dwh_health_log TO dwh_monitor_writer;
GRANT INSERT ON monitor.dwh_health_log_archive TO dwh_monitor_writer;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA monitor TO dwh_monitor_writer;
GRANT SELECT ON ALL TABLES IN SCHEMA monitor TO dwh_monitor_reader;

SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS boyut
FROM pg_tables WHERE schemaname = 'monitor' ORDER BY tablename;
