# DWH DB Monitor

> Production-ready multi-database Data Warehouse health monitoring platform

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue.svg)](https://postgresql.org)
[![Prometheus](https://img.shields.io/badge/Prometheus-2.x-orange.svg)](https://prometheus.io)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue.svg)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

DWH DB Monitor is a plugin-based health monitoring platform that continuously checks the quality, cost, pipeline integrity, security, and user behavior of your Data Warehouse databases. It supports PostgreSQL, MSSQL, MySQL, MariaDB, Oracle, and any ODBC-compatible database out of the box — and adding a new one takes roughly 150 lines of Python and 3 lines of YAML.

---

## Table of Contents

- [Architecture](#architecture)
- [Features](#features)
- [Health Check Categories](#health-check-categories)
- [Supported Databases](#supported-databases)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [API Endpoints](#api-endpoints)
- [Alerting](#alerting)
- [Adding a New Database](#adding-a-new-database)
- [Project Status](#project-status)

---

## Architecture

```
+----------------------------------------------------------------+
|  Source Databases                                              |
|  PostgreSQL  MSSQL  MySQL  MariaDB  Oracle  ODBC              |
+-------------------------+--------------------------------------+
                          |  native drivers
+-------------------------v--------------------------------------+
|  Collector Engine  (Python / FastAPI / APScheduler)          |
|                                                                 |
|  AdapterRegistry -----> DBAdapter ABC                         |
|  (YAML-driven,          connect()                              |
|   importlib)            collect_metrics()  --> MetricSchema  |
|                         health_check()                         |
|                                                                 |
|  CollectorEngine  (circuit breaker + scheduler)               |
|  Notifier         (SMTP / Slack / PagerDuty / Teams)          |
|  RetentionManager (24-month active + cold archive)            |
+----------+--------------------+------------------------------+
           |                    |
+----------v------+   +---------v---------+
|  dwh_health_log |   |  /metrics         |
|  PostgreSQL 16  |   |  Prometheus format|
|  24-month       |   |  port 8005        |
|  partitioned    |   +---+---------------+
+----------+------+       |
           |                +---> Prometheus (9090)
           |                          |
           |                      Alertmanager (9093)
           |
           +---> Power BI / Tableau / Superset / super_bi
                  (direct SQL connection to dwh_health_log)
```

**Key design principle:** The Collector Engine never knows the database type. It only calls `adapter.collect_metrics()`. Adding a new database requires no changes to the engine.

---

## Features

- **Plugin architecture** — DBAdapter ABC + AdapterRegistry; new DB = ~150 lines Python + 3 lines YAML
- **Two output points** — `dwh_health_log` PostgreSQL table (SQL-queryable) + `/metrics` HTTP endpoint (Prometheus format); no dashboard lock-in
- **5 check categories** — Cost, Data Quality, Pipeline, User Behavior, Security
- **Independent Notifier** — SMTP, Slack, PagerDuty, Teams, generic webhook; no DB-specific stored procedures
- **Central RetentionManager** — 24-month active storage + cold archive (local / S3 / Azure Blob)
- **Circuit breaker** — per-adapter failure isolation; 3 consecutive failures open the circuit
- **Prometheus + Alertmanager** — 6 pre-built alert rules (critical, security, pipeline, warning, crisis, all-adapters-down)
- **HashiCorp Vault** — credential resolution via `vault://` URI format

---

## Health Check Categories

| Code | Category | What It Checks | Severity |
|------|----------|----------------|----------|
| **FR-COST** | Cost | Unused tables (30+ days), table bloat, large unpartitioned tables | 2-3 |
| **FR-DQ** | Data Quality | High NULL rate (>50%), missing PK/UNIQUE c

---

## Quick Start

### Prerequisites

- Docker + Docker Compose v2
- Git

### 1. Clone

```bash
git clone https://github.com/SHapeloglu/DBMonitor.git
cd DBMonitor
```

### 2. Configure

```bash
cp docs/config/databases.yaml config/databases.yaml
# Edit config/databases.yaml:
#   - Set host, port, db_name, credentials for your database
#   - Set enabled: true for adapters you want active
```

### 3. Start

```bash
export VAULT_TOKEN=<your-vault-token>   # or leave empty if not using Vault
docker compose up -d --build
```

### 4. Verify

```bash
# Health check
curl http://localhost:8005/health

# Prometheus metrics
curl http://localhost:8005/metrics

# Prometheus UI
open http://localhost:9090

# Alertmanager UI
open http://localhost:9093
```

---

## Configuration

All configuration lives in `config/`. Annotated reference copies are in `docs/config/`.

### databases.yaml

```yaml
databases:
  - name: prod-postgresql
    adapter: adapters.postgresql_adapter.PostgreSQLAdapter
    host: postgres
    port: 5432
    db_name: dwhmonitor
    db_type: postgresql
    connect_timeout_s: 10
    query_timeout_s: 30
    enabled: true
    credentials:
      user: dquser
      password: dqpass          # or: vault://secret/dwh/postgresql

  - name: prod-mssql
    adapter: adapters.mssql_adapter.MSSQLAdapter
    host: 10.0.0.5
    port: 1433
    db_name: DWH_PROD
    db_type: mssql
    enabled: false             # flip to true after setting credentials
    credentials:
      user: etl_svc
      password: changeme
```

### notifications.yaml

```yaml
notifications:
  - channel: smtp
    enabled: false
    threshold: "severity >= 3"
    smtp_host: mail.company.com
    to: [dwh-team@company.com]

  - channel: slack_webhook
    enabled: false
    threshold: "severity >= 2"
    webhook_url: https://hooks.slack.com/services/XXX/YYY/ZZZ
```

### Config File Reference

| File | Purpose |
|------|---------|
| `config/databases.yaml` | DB adapter definitions |
| `config/notifications.yaml` | Alert channels (SMTP, Slack, PagerDuty, Teams, webhook) |
| `config/retention.yaml` | 24-month retention + cold archive backend |
| `config/prometheus/prometheus.yml` | Prometheus scrape config |
| `config/prometheus/rules/dwh-health.yml` | 6 Prometheus alert rules |
| `config/alertmanager.yml` | Alertmanager routing and receivers |

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Adapter status and engine health |
| `/metrics` | GET | Prometheus exposition format |

### /metrics Sample Output

```
# HELP dwh_health_check DWH health check result
# TYPE dwh_health_check gauge
dvwh_health_check{db_type="postgresql",host="postgres",db_name="dwhmonitor",kategori="maliyet",kontrol_kodu="FR-COST-01",sonuc="WARNING"} 2
dwh_health_check{db_type="postgresql",host="postgres",db_name="dwhmonitor",kategori="guvenlik",kontrol_kodu="FR-SEC-01",sonuc="OK"} 0
```

---

## Alerting

6 pre-built Prometheus alert rules:

| Alert | Condition | For | Severity |
|--------|-----------|-----|----------|
| `DWHCriticalHealthIssue` | Any severity=3 metric | 5m | critical |
| `DWHSecurityThreat` | Security category severity=3 | 1m | critical |
| `DWHPipelineBreakdown` | Pipeline category severity=3 | 10m | critical |
| `DWHWarningIssue` | Any severity=2 metric | 15m | warning |
| `DWHMultipleCategoriesCritical` | More than 3 critical issues | 10m | critical |
| `DWHAllAdaptersDown` | Zero metrics received | 5m | critical |

Configure receivers in `config/alertmanager.yml`.

---

## Database Schema

`dwh_health_log` — PostgreSQL 16, `monitor` schema

```sql
CREATE TABLE monitor.dwh_health_log (
    id               BIGSERIAL,
    kontrol_tarihi   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    db_type          VARCHAR(20)  NOT NULL,
    host             VARCHAR(255) NOT NULL,
    db_name          VARCHAR(255) NOT NULL,
    kategori         kategori_tip NOT NULL,
    kontrol_kodu     VARCHAR(30)  NOT NULL,
    kontrol_adi      VARCHAR(100) NOT NULL,
    sonuc            sonuc_tip    NOT NULL,
    severity         SMALLINT     NOT NULL,
    etkilenen_obje   VARCHAR(255),
    etkilenen_sayi   INTEGER,
    detay            TEXT,
    PRIMARY KEY (id, kontrol_tarihi)
) PARTITION BY RANGE (kontrol_tarihi�;
```

- **24 monthly partitions** (2025-01 through 2026-12)
- **5 indexes** optimized for dashboard and alert queries
- **3 views:** `v_son_24s_ozet`, `v_aktif_sorunlar`, `v_trend_7gun`
- **Archive table:** `dwh_health_log_archive` for rows older than 24 months
- **Stored procedure:** `add_monthly_partition(date)` called by RetentionManager

Full DDL: [`docs/sql/dwh_health_log.sql`](docs/sql/dwh_health_log.sql)

---

## Adding a New Database

### Step 1 - Write the adapter (~150 lines)

```python
# adapters/teradata_adapter.py
from core.base_adapter import DBAdapter, HealthResult, DBMetadata
from core.metric_schema import MetricSchema, Kategori, Sonuc

class TeradataAdapter(DBAdapter):
    def connect(self): ...
    def disconnect(self): ...
    def health_check(self) -> HealthResult: ...
    def get_metadata(self) -> DBMetadata: ...
    def collect_metrics(self) -> list[MetricSchema]:
        metrics = []
        metrics.extend(self._check_amp_skew())
        metrics.extend(self._check_perm_space())
        metrics.extend(self._check_slow_queries())
        return metrics
```

### Step 2 - Add 3 lines to databases.yaml

```yaml
  - name: prod-teradata
    adapter: adapters.teradata_adapter.TeradataAdapter
    host: 10.0.0.10
    db_type: teradata
    enabled: true
    credentials:
      user: etl_svc
      password: changeme
```

### Step 3 - Restart

```bash
docker compose restart dwh-monitor
```

No engine code changes. The new adapter is auto-discovered via AdapterRegistry.

---

## Ports

| Service | Port | Purpose |
|---------|------|---------|
| dwh-monitor | 8005 | FastAPI - /health, /metrics |
| Prometheus | 9090 | Metrics scraping + alert rule evaluation |
| Alertmanager | 9093 | Alert routing and deduplication |
| PostgreSQL | 5433 | dwh_health_log storage (host port) |
| Vault | 8200 | Secrets management (dev mode) |

---

## Vault Integration

Credentials can be stored in HashiCorp Vault using the `vault://` URI format:

```yaml
credentials:
  user: etl_svc
  password: vault://secret/dwh/postgresql
```

After Vault container restart (dev mode):

```bash
export VAULT_TOKEN=<new-token>
python vault-init.py          # run from host
docker compose restart dwh-monitor
```

---

## Retention

RetentionManager operates independently of DB-native TTL or partitioning:

- **Active:** 24 months in `dwh_health_log`
- **Archive:** rows older than 24 months moved to `dwh_health_log_archive`
-- **Backends:** local filesystem (default), S3, Azure Blob

---

## Project Status

| Phase | Description | Status |
|--------|-------------|--------|
| F0 | Infrastructure - DDL, Docker, preflight check | Done |
| F1 | Core engine - registry, scheduler, notifier, retention | Done |
| F2 | PostgreSQL adapter (reference implementation) | Done |
| F3 | API layer - /health, /metrics | Done |
| F4 | MSSQL adapter - 8 FR checks, ODBC Driver 18 | Done, awaiting credentials |
| F5 | MySQL, MariaDB, Oracle, Generic ODBC adapters | Done, awaiting credentials |
| F6-02 | HashiCorp Vault integration | Done |
| F6-04 | Prometheus alert rules (6 rules) + Alertmanager | Done |
| F6-06 | Documentation - config files, SQL schema | Done |
| F6-01 | Kubernetes Helm chart | Planned |
| F6-03 | Grafana dashboard JSON | Deferred |
| F6-05 | Horizontal scaling - Redis coordination | Planned |
| - | IBM DB2 adapter | Pending competitor analysis |
| - | MongoDB adapter | Pending competitor analysis |
| - | Teradata adapter | Pending competitor analysis |

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| API Egngine | Python 3.12, FastAPI, APScheduler |
| Data validation | Pydantic v2 |
| DB drivers | psycopg2, pyodbc, pymysql, python-oracledb |
| Metrics | Prometheus, Alertmanager |
| Secrets | HashiCorp Vault |
| Storage | PostgreSQL 16 (partitioned) |
| Deployment | Docker Compose (dev), Kubernetes + Helm (prod) |
