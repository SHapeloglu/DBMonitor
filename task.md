# DWH İzleme Sistemi — Görev Listesi

Durum simgeleri: ⬜ Yapılmadı · 🔄 Devam ediyor · ✅ Tamamlandı · 🔴 Bloker

---

## Faz 0 — Temel altyapı

| # | Görev | Öncelik | Not |
|---|---|---|---|
| F0-01 | ✅ `preflight_check.py` | 🔴 Bloker | Tamamlandı |
| F0-02 | ✅ `dwh_health_log` DDL | 🔴 Bloker | PostgreSQL 16, monitor schema, 24 aylık partition |
| F0-03 | ⬜ Secrets yönetimi (Vault entegrasyonu) | Orta | Şu an düz text, K-02 kararı bekliyor |
| F0-04 | ✅ `docker-compose.yml` | Yüksek | dq-postgres + dwh-monitor, port 8005 |
| F0-05 | ⬜ CI pipeline — lint + test + docker build | Orta | GitHub Actions önerilir |

---

## Faz 1 — Core Engine

| # | Görev | Dosya | Durum |
|---|---|---|---|
| F1-01 | ✅ `DBAdapter` ABC | `core/base_adapter.py` | Tamamlandı |
| F1-02 | ✅ `MetricSchema` Pydantic + Prometheus + log_row | `core/metric_schema.py` | Tamamlandı |
| F1-03 | ✅ `AdapterRegistry` — YAML + importlib | `core/adapter_registry.py` | Tamamlandı |
| F1-04 | ✅ `CollectorEngine` — APScheduler + circuit breaker | `core/collector_engine.py` | Tamamlandı. K-01 → APScheduler seçildi |
| F1-05 | ✅ `Notifier` — SMTP + Slack + PagerDuty + Teams | `core/notifier.py` | Tamamlandı, 3 kural yüklü |
| F1-06 | ✅ `RetentionManager` — 24 ay + cold storage | `core/retention_manager.py` | Tamamlandı |

---

## Faz 2 — Referans adapter (PostgreSQL)

| # | Görev | Durum |
|---|---|---|
| F2-01..F2-12 | ✅ PostgreSQLAdapter — 8 FR kontrolü | Tamamlandı. Saatlik çalışıyor, `dwh_health_log` + `/metrics` doğrulandı |

**Çalışan FR kontrolleri:** FR-COST-01/02/03, FR-DQ-01/02, FR-PIPE-01, FR-SEC-01, FR-USER-01

---

## Faz 3 — API katmanı

| # | Görev | Durum |
|---|---|---|
| F3-01 | ✅ FastAPI app — `api/main.py` | Tamamlandı, port 8005 |
| F3-02 | ✅ `GET /health` | Tamamlandı |
| F3-03 | ✅ `GET /metrics` — Prometheus format | Tamamlandı, doğrulandı |
| F3-04 | ⬜ `GET /logs` — JSON filtreli | Yapılmadı |
| F3-05 | ⬜ `GET /logs/summary` | Yapılmadı |
| F3-06 | ⬜ `GET /adapters` | Yapılmadı |
| F3-07 | ⬜ API auth — Bearer / API key | Yapılmadı. K-07 kararı bekliyor |

---

## Faz 4 — MSSQL adapter

| # | Görev | Durum |
|---|---|---|
| F4-01..F4-09 | ✅ MSSQLAdapter — 8 FR kontrolü | Tamamlandı. `enabled: false`, gerçek bağlantı bilgisi bekliyor |

**Çalışan FR kontrolleri:** FR-COST-01/03, FR-DQ-04, FR-PIPE-01/04, FR-USER-04, FR-SEC-01/03  
**Driver:** ODBC Driver 18 for SQL Server — host + Docker image'a kuruldu  
**Not:** Gerçek MSSQL bilgileri gelince `databases.yaml`'da host/user/pass güncelle → `enabled: true` → restart

---

## Faz 5 — Diğer adapter'lar

| # | Adapter | Durum | Not |
|---|---|---|---|
| F5-01 | ✅ Oracle | Tamamlandı | K-03 → AWR yok, sadece V$/DBA_* kullanılıyor. `enabled: false` |
| F5-02 | ⬜ IBM DB2 | Yapılmadı | Rakip analizi sonrası değerlendirilecek |
| F5-03 | ✅ MySQL | Tamamlandı | K-04 → Community edition. `enabled: false` |
| F5-04 | ✅ MariaDB | Tamamlandı | mysql_adapter.py paylaşılıyor, `db_type: mariadb`. `enabled: false` |
| F5-05 | ⬜ MongoDB | Yapılmadı | Rakip analizi sonrası değerlendirilecek |
| F5-06 | ⬜ Teradata | Yapılmadı | Rakip analizi sonrası değerlendirilecek |
| F5-07 | ✅ Generic ODBC | Tamamlandı | 3 FR kontrolü (COST-03, DQ-02, SEC-01). ANSI INFORMATION_SCHEMA. `enabled: false` |

---

## Faz 6 — Production hazırlık

| # | Görev | Öncelik | Durum |
|---|---|---|---|
| F6-01 | Kubernetes Helm chart | Yüksek | ⬜ Yapılmadı |
| F6-02 | ✅ Secrets yönetimi — Vault | Yüksek | ✅ Tamamlandı (dev mode + plain text fallback) |
| F6-03 | Grafana dashboard JSON | Orta | ⬜ Deferred |
| F6-04 | ✅ Prometheus alert rules | Orta | ✅ Tamamlandı (6 alert rule, Alertmanager UP) |
| F6-05 | Horizontal scaling — Redis koordinasyon | Düşük | ⬜ Yapılmadı |
| F6-06 | ✅ Dokümantasyon | Orta | ✅ Tamamlandı (7 YAML config + SQL + README) |

---

## Rakip analizi (sonraki oturum)

DB2, MongoDB, Teradata adapter öncelikleri rakip analizine göre yeniden belirlenecek.
Karşılaştırılacak ürünler: Datadog, Grafana, SolarWinds, OpsRamp ve diğerleri.

---

## Açık kararlar

| # | Karar | Durum | Not |
|---|---|---|---|
| K-01 | APScheduler mi, Celery mi? | ✅ APScheduler | Seçildi, çalışıyor |
| K-02 | Secrets yönetimi | ⬜ Açık | Şu an düz text |
| K-03 | Oracle AWR/ASH lisansı | ✅ Yok | Sadece V$/DBA_* kullanılıyor |
| K-04 | MySQL edition | ✅ Community | INFORMATION_SCHEMA + performance_schema |
| K-05 | Teradata BRD | ⬜ Açık | Rakip analizi sonrası |
| K-06 | Cold storage backend | ⬜ Açık | S3, Azure Blob, yerel |
| K-07 | /metrics endpoint auth | ⬜ Açık | API Key, Bearer JWT, IP whitelist |

---

## Sonraki oturumda yapılacaklar

1. **Helm chart (F6-01)** veya **Rakip analizi** — hangisi öncelikli?
2. Rakip analizine göre DB2 / MongoDB / Teradata önceliklerini belirle
3. Gerçek MSSQL/Oracle/MySQL bağlantı bilgileri gelince adapter'ları aktif et
4. F3-04/05/06 — API log endpoint'leri
5. F6 — Production hazırlık (kalan görevler)

---

## Tamamlanan görevler özeti

| Tarih | Görev | Karar |
|---|---|---|
| 2026-08 | GitHub araştırması | datachecks, metREx, query-exporter bulundu |
| 2026-08 | Genel mimari | 5 katman belirlendi |
| 2026-08 | Plugin mimarisi | DBAdapter ABC + Registry + YAML config |
| 2026-08 | BRD analizi | 7 platform × 5 kategori matrisi |
| 2026-08 | Core engine | base_adapter, metric_schema, registry, collector, notifier, retention |
| 2026-08 | PostgreSQL adapter | 8 FR kontrolü, saatlik çalışıyor, log + /metrics doğrulandı |
| 2026-08 | MSSQL adapter | 8 FR kontrolü, ODBC Driver 18 kuruldu |
| 2026-08 | MySQL/MariaDB adapter | 8 FR kontrolü, pymysql, tek adapter çift platform |
| 2026-08 | Oracle adapter | 8 FR kontrolü, oracledb Thin mode, AWR yok |
| 2026-08 | Generic ODBC adapter | 3 FR kontrolü, ANSI INFORMATION_SCHEMA fallback |
| 2026-08 | Docker altyapısı | dq-postgres + dwh-monitor, build, end-to-end doğrulama |
| 2026-08 | Vault integration (F6-02) | HashiCorp Vault dev mode, credentials YAML backup |
| 2026-08 | Prometheus alerts (F6-04) | 6 alert rule, Alertmanager, dwh-health.yml |
| 2026-08-16 | Dokümantasyon (F6-06) | 7 YAML config, SQL schema, README, GitHub push |
