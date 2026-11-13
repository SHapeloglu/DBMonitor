# DWH İzleme Sistemi — Görev Listesi

Durum simgeleri: ⬜ Yapılmadı · 🔄 Devam ediyor · ✅ Tamamlandı · 🔴 Bloker

---

## Faz 0 — Temel altyapı

| # | Görev | Öncelik | Not |
|---|---|---|---|
| F0-01 | ✅ `preflight_check.py` | 🔴 Bloker | Tamamlandı |
| F0-02 | ✅ `dwh_health_log` DDL | 🔴 Bloker | PostgreSQL 16, monitor schema, 24 aylık partition |
| F0-04 | ✅ `docker-compose.yml` | Yüksek | dq-postgres + dwh-monitor, port 8005 |
| F0-05 | ✅ CI pipeline — lint + test + docker build | Orta | Tamamlandı (PR #7, `.github/workflows/ci.yml`) |

---

## Faz 1 — Core Engine

| # | Görev | Dosya | Durum |
|---|---|---|---|
| F1-01 | ✅ `DBAdapter` ABC | `core/base_adapter.py` | Tamamlandı |
| F1-02 | ✅ `MetricSchema` Pydantic + Prometheus + log_row | `core/metric_schema.py` | Tamamlandı |
| F1-03 | ✅ `AdapterRegistry` — YAML + importlib | `core/adapter_registry.py` | Tamamlandı |
| F1-04 | ✅ `CollectorEngine` — APScheduler + circuit breaker | `core/collector_engine.py` | Tamamlandı. K-01 → APScheduler seçildi |
| F1-05 | ✅ `Notifier` — SMTP + Slack + PagerDuty + Teams | `core/notifier.py` | Tamamlandı, 3 kural yüklü |
| F1-06 | 🔄 `RetentionManager` — 24 ay + cold storage | `core/retention_manager.py` | Kısmi: yalnızca yerel arşiv. S3/Azure export stub, K-06 açık. Tek ifadede arşivleme düzeltmesi PR #2'de (taslak, staging testi bekliyor) |

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
| F3-04 | ✅ `GET /logs` — JSON filtreli | Tamamlandı (PR #6, `api/logs.py`) |
| F3-05 | ✅ `GET /logs/summary` | Tamamlandı (`api/main.py:118`) |
| F3-06 | ✅ `GET /adapters` | Tamamlandı (`api/main.py:127`) |
| F3-07 | ✅ API auth — `X-API-Key` | Tamamlandı (PR #6, `api/auth.py`). `API_KEY` boşsa kapalı; `/health` hariç hepsi korunur |

---

## Faz 4 — MSSQL adapter

| # | Görev | Durum |
|---|---|---|
| F4-01..F4-09 | ✅ MSSQLAdapter — 8 FR kontrolü | Tamamlandı. `enabled: false`, gerçek bağlantı bilgisi bekliyor. Mantık düzeltmeleri PR #3'te (taslak) |

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
| F6-01 | Kubernetes Helm chart | Yüksek | 🔄 PR #8 (taslak), helm ile test edilmedi |
| F6-02 | ✅ Secrets yönetimi — Vault | Yüksek | ✅ Tamamlandı (dev mode + plain text fallback). Not: dev modunda tamamlandı; prod kurulumu ve düz metin kaldırma K-02'de açık. F0-03 ile birleştirildi (tekrar eden satır). |
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
| K-02 | Secrets yönetimi | ⬜ Açık | Düz metin. PR #5 (`${ENV}` açma) taslak; Vault dev modda, sunucuda durdurulmuş |
| K-03 | Oracle AWR/ASH lisansı | ✅ Yok | Sadece V$/DBA_* kullanılıyor |
| K-04 | MySQL edition | ✅ Community | INFORMATION_SCHEMA + performance_schema |
| K-05 | Teradata BRD | ⬜ Açık | Rakip analizi sonrası |
| K-06 | Cold storage backend | ⬜ Açık | S3, Azure Blob, yerel |
| K-07 | /metrics endpoint auth | ✅ API Key | PR #6. Bearer JWT / IP whitelist yapılmadı. Prometheus scrape'e başlık eklenmeli |

---

## Açık PR'lar (hepsi taslak, main'e alınmadı)

| PR | Dal | İçerik | Not |
|---|---|---|---|
| #2 | `fix/retention-cte-move` | Retention: tek ifadede arşivleme, ölü kod | Staging testi gerekli |
| #3 | `fix/mssql-check-logic` | MSSQL DDM filtresi, yetki hatası, dinamik SQL | Gerçek MSSQL ile test gerekli |
| #5 | `chore/config-secrets-env` | YAML'da `${NAME}` açma, şifreleri `.env`'e taşıma | Uyumsuz: 8 ortam değişkeni zorunlu; sunucuda image yeniden build gerekir |
| #8 | `feat/helm-chart` | Helm chart (F6-01) | `helm lint/template` çalıştırılmadı |
| #9 | `chore/rename-db-user-apache` | DB kullanıcısı `dquser` → `apache` | #5 ile çakışması beklenir; sunucuda zaten uygulandı |

---

## Sonraki oturumda yapılacaklar

1. Açık PR'ları sırayla incele, staging'de test et ve birleştir (önce #2, #3; sonra #5 ve #9 çakışmasını çöz; #8 en son)
2. Sunucuda PR #5 sonrası düz metin şifreleri `.env`'e taşı (image yeniden build gerekir)
3. K-02 kararı: kalıcı üretim Vault mı, Vault'u kaldırmak mı (dev konteyner sunucuda durdurulmuş, `postgres-local` sırrı eski)
4. Uzak DB'lerde `etl_svc` hesaplarının şifrelerini gerçek değerle değiştir (DBA işi) ve adapter'ları `enabled: true` yap
5. Harici disk kopyasının (Windows, aylık) çalıştığını doğrula. `pg_dump` + `config/` gece yedeğine eklendi (2026-11-12); ilk cron çalışması 04:30'da `restic_son.txt` / `restic_cron.log` ile kontrol edilmeli
6. Rakip analizi → DB2 / MongoDB / Teradata önceliklerini belirle
7. F6-03 Grafana panoları, F6-05 yatay ölçekleme (düşük öncelik)

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

---

## Tamamlanan görevler (ek)

| Tarih | Görev | Detay |
|---|---|---|
| 2026-08-16 | GitHub README.md | 389 satır, kapsamlı proje dokümantasyonu, commit e7a1183 |
| 2026-11-09 | CI (F0-05) | PR #7: ruff, py_compile + pytest, docker build |
| 2026-11-09 | `GET /logs` ve API anahtarı (F3-04, F3-07) | PR #6 |
| 2026-11-08..09 | Sunucu ↔ GitHub senkronu, güvenlik düzeltmeleri | PR #1: sabit şifre varsayılanları kaldırıldı, portlar 127.0.0.1'e bağlandı |
| 2026-11-09 | Md çelişkileri giderildi | PR #4 |
| 2026-11-09 | Sunucuda DB şifresi döndürüldü, kullanıcı `apache` yapıldı | Repoda yalnızca PR #9 (taslak). Dosya izinleri 600, `.bak` kopyaları silindi |
