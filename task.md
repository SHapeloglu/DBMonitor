# DWH İzleme Sistemi — Görev Listesi

Durum simgeleri: ⬜ Yapılmadı · 🔄 Devam ediyor · ✅ Tamamlandı · 🔴 Bloker

---

## Faz 0 — Temel altyapı

| # | Görev | Öncelik | Not |
|---|---|---|---|
| F0-01 | ✅ `preflight_check.py` | 🔴 Bloker | Tamamlandı |
| F0-02 | ✅ `dwh_health_log` DDL | 🔴 Bloker | PostgreSQL 16, monitor schema, 24 aylık partition (2025-01 … 2026-12, `sql/dwh_health_log.sql`). 2027 partition'ı aylık retention cron'u ile eklenir (`core/retention_manager.py` `_ensure_next_partition`) |
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
| F1-06 | 🔄 `RetentionManager` — 24 ay + cold storage | `core/retention_manager.py` | Kısmi: yalnızca yerel arşiv. S3/Azure export stub, K-06 açık. Tek ifadede arşivleme ve `batch_size` doğrulaması PR #2 ile main'de (`b0c0e5c`, 2026-11-25). Gerçek PostgreSQL'de doğrulandı (25 arşiv, 5 kalan, dry-run değişiklik yapmıyor). CI birim testleri: `tests/test_retention_manager.py` (6 test). JSONL export yalnızca bu turda arşive yazılan satırları alıyor (PR #20, `main`'de; gerçek PostgreSQL'de aynı saatteki iki turda tekrar yoktu). Açık: export tüm turu belleğe alıyor; `arsiv_tarihi` indeksi yok |

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
| F3-05 | ✅ `GET /logs/summary` | Tamamlandı (`api/main.py:150`) |
| F3-06 | ✅ `GET /adapters` | Tamamlandı (`api/main.py:201`) |
| F3-07 | ✅ API auth — `X-API-Key` | Tamamlandı (PR #6, `api/auth.py`). `API_KEY` boşsa kapalı; `/health` hariç hepsi korunur |

---

## Faz 4 — MSSQL adapter

| # | Görev | Durum |
|---|---|---|
| F4-01..F4-09 | ✅ MSSQLAdapter — 8 FR kontrolü | Tamamlandı. `enabled: false`, gerçek bağlantı bilgisi bekliyor. Mantık düzeltmeleri PR #3'te (taslak; CI geçti, gerçek SQL Server testi yapılmadı) |

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
| F6-01 | Kubernetes Helm chart | Yüksek | ✅ PR #8 main'de (merge `66c3d48`, CI commit `55c6c2c`). CI'da `helm lint` ve `helm template` geçiyor; varsayılan `DB_USER` `apache`. Kümede (`helm install --dry-run`) test edilmedi |
| F6-02 | 🔄 Secrets yönetimi — Vault | Yüksek | 🔄 Düz metin git'ten çıktı (PR #18, `587146d`); compose parolaları `.env`'den okuyor (2026-11-25 dağıtım). Vault dev modda, sunucuda durdurulmuş; prod Vault kararı (K-02) ve döndürme bekliyor. F0-03 ile birleştirildi (tekrar eden satır). |
| F6-03 | Grafana dashboard JSON | Orta | ⬜ Deferred |
| F6-04 | ✅ Prometheus alert rules | Orta | ✅ Tamamlandı (6 alert rule, Alertmanager UP). Kurallar değere göre ve pencereli (`last_over_time(...[70m])`, `absent_over_time`); PR #11 (MERGED), `config/prometheus/rules/dwh-health.yml` |
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
| K-02 | Secrets yönetimi | 🔄 Kısmi | Git'te düz metin kalmadı (PR #18, `587146d`); sunucuda `.env` (mod 600). Açık: geçmişteki parolaların döndürülmesi, prod Vault kararı (Vault dev modda, sunucuda durdurulmuş). PR #5 kapatıldı (#18 ile değiştirildi) |
| K-03 | Oracle AWR/ASH lisansı | ✅ Yok | Sadece V$/DBA_* kullanılıyor |
| K-04 | MySQL edition | ✅ Community | INFORMATION_SCHEMA + performance_schema |
| K-05 | Teradata BRD | ⬜ Açık | Rakip analizi sonrası |
| K-06 | Cold storage backend | ⬜ Açık | S3, Azure Blob, yerel |
| K-07 | /metrics endpoint auth | 🔄 API Key | PR #6 (MERGED). `API_KEY` tanımlıysa `X-API-Key` zorunlu (`api/auth.py`). Prometheus scrape (`config/prometheus/prometheus.yml`, job `dwh-metrics`) başlık göndermiyor (2026-11-24 kod kontrolü: job'da header/authorization tanımı yok); `API_KEY` tanımlıysa scrape 401 alır (sunucudaki `API_KEY` durumu doğrulanmadı). Bearer JWT / IP whitelist yapılmadı |

---

## Açık PR'lar (taslak) ve birleşenler

| PR | Dal | İçerik | Not |
|---|---|---|---|
| #3 | `fix/mssql-check-logic` | MSSQL DDM filtresi, yetki hatası, dinamik SQL | DRAFT. CI geçti (`5582b78`). Gerçek MSSQL ile test gerekli |
Kapatıldı: #5 (`chore/config-secrets-env`, yerine #18 birleşti). #15 (`chore/agent-scope-layer`, alt ajan kapsam koruyucusu): kapatıldı, CI başarısızdı ve doğrulayıcı FAIL verdi; dal korunuyor.

Birleşenler (main'de, 2026-11-25 `gh pr list --state merged`): #1, #2, #4, #6, #7, #8, #9, #10, #11, #12, #13, #14, #16, #17, #18, #19, #20.

---

## Sonraki oturumda yapılacaklar

1. **Döndürme (öncelik 1, DBA/sahip işi):** `apache`, `etl_svc`, SMTP kullanıcısı ve Postgres parolası (`DQ_DB_PASSWORD`). Tamamlanınca sunucuda `.env` güncellenip `dwh-monitor` yeniden başlatılır. Geçmiş commit'lerdeki eski kod sürümündeki parola varsayılanı ve eski parolalar da "ele geçirilmiş" sayılmalı.
2. **Geri alma imajını sil:** `dwh-db-monitor-dwh-monitor:rollback-20261125` içinde sabit bir parola varsayılanı var. Yeni sürüm birkaç gün stabil çalıştıktan sonra silinecek (onaylı).
3. **PR #3:** gerçek SQL Server (staging) testi, sonra birleştirme.
4. **Helm kümede test:** `helm install --dry-run` bir Kubernetes kümesinde yapılmalı (CI'da yok).
5. **`arsiv_tarihi` indeksi:** export sorgusu tam tarama yapabilir (PR #20 doğrulayıcı notu). Veri büyüdükçe indeks değerlendirilmeli.
6. **Kalan `10.0.0.x` referansları:** `tests/` (fixture) ve `scripts/vault-init.py` (kod). Ayrı karar gerekir; düşük öncelik.
7. **Alertmanager alıcısı:** `localhost:5001` yerine gerçek bir kanal (Slack veya e-posta) gerekli. Bilgi bekleniyor.
7. **K-02 kararı:** kalıcı üretim Vault mı, Vault'u kaldırmak mı (Vault dev modda, sunucuda durdurulmuş).
7. **Alertmanager alıcısı:** `config/alertmanager.yml` `localhost:5001`; gerçek bir alıcı (Slack/e-posta) gerekli. Gizli değerler `.env`'e girer, dokümana değil.
8. **`_export_local` 1 saat penceresi:** uzun süren arşiv işlerinde erken batch'ler JSONL'a yazılmayabilir. Ayrı bir düzeltme olarak ele alınmalı.
9. **Disk (%92, 17 GB boş):** restic politikası mevcut (`/opt/yedek/restic_yedek.sh`, gece `forget --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune`). Disk baskısının kaynağı başka projelerin verileri ve imajları; onlara dokunulmaz.
10. Uzak DB'lerde `etl_svc` hesaplarının şifrelerini değiştir (DBA işi) ve adapter'ları `enabled: true` yap.
11. Harici disk kopyasının (Windows, aylık) çalıştığını doğrula; sunucudan doğrulanamıyor.
12. Rakip analizi → DB2 / MongoDB / Teradata önceliklerini belirle.
13. F6-03 Grafana panoları, F6-05 yatay ölçekleme (düşük öncelik).

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
| 2026-08-26 | GitHub README.md | 389 satır (o commit), kapsamlı proje dokümantasyonu, commit e7a1183 (commit tarihi `git log`; önceki 08-16 kaydı hatalıydı) |
| 2026-11-09 | CI (F0-05) | PR #7: ruff, py_compile + pytest, docker build |
| 2026-11-24 | Doküman durum güncellemesi | PR #10 (`1301be4`), PR #16 (`12402de`) birleşti; 6 md dosyası origin/main 12402de'ye göre güncellendi |
| 2026-11-09 | `GET /logs` ve API anahtarı (F3-04, F3-07) | PR #6 |
| 2026-11-08..09 | Sunucu ↔ GitHub senkronu, güvenlik düzeltmeleri | PR #1: sabit şifre varsayılanları kaldırıldı, portlar 127.0.0.1'e bağlandı |
| 2026-11-09 | Md çelişkileri giderildi | PR #4 |
| 2026-11-09 | Sunucuda DB şifresi döndürüldü, kullanıcı `apache` yapıldı | Repoda PR #9 (2026-11-13 birleşti). Dosya izinleri 600, `.bak` kopyaları silindi |
| 2026-11-25 | PR #2 retention (tek CTE) | `b0c0e5c`: birim testleri (`tests/test_retention_manager.py`), `batch_size` doğrulaması, gerçek PostgreSQL doğrulaması. Doğrulayıcı PASS_WITH_NOTES |
| 2026-11-25 | PR #18 sır dosyaları | `587146d`: `config/databases.yaml` git'ten çıktı, örnek ve dokümanlar yer tutucu, `tests/test_config_example.py` |
| 2026-11-25 | Sunucu dağıtımı (`origin/main` `b0c0e5c`) | Dağıtım öncesi yedek `/root/yedekler/pre-deploy-20261125-1308`; `.env`'e `DQ_DB_PASSWORD`; yalnızca `dwh-monitor` yeniden build; `persist_ok: true`; Prometheus 3/3 up; 6 kural yüklü; firing alarm 0. Parolalar değişmedi |
| 2026-11-25 | PR #3 / #8 CI ve düzeltmeler | Dallar `origin/main` ile birleştirilip CI tetiklendi (`5582b78`, `ddea741`); helm `DB_USER` `apache` (`df64bce`); PR açıklamalarına doğrulama eksikleri yazıldı |
| 2026-11-25 | PR #5 kapatıldı | PR #18 ile değiştirildi |
| 2026-11-25 | PR #8 Helm chart | merge `66c3d48` (CI commit `55c6c2c`: `helm lint` + `helm template`); doğrulayıcı PASS_WITH_NOTES |
| 2026-11-25 | PR #20 JSONL export düzeltmesi | Aynı saatteki turlarda satır tekrarı giderildi (gerçek PostgreSQL: 53 → 28); doğrulayıcı PASS_WITH_NOTES |
| 2026-11-25 | Doküman durumu (PR #19) | Md dosyaları `b0c0e5c` durumuna göre güncellendi, doğrulayıcı PASS_WITH_NOTES |
| 2026-11-25 | İç adres temizliği | `docs/config`, `helm/files/config`, `README.md`, `config/databases.example.yaml`, `config/notifications.yaml`: IP ve kurumsal adresler yer tutucuya çevrildi |
