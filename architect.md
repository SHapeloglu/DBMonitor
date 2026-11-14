# DWH İzleme Sistemi — Mimari

Bu dosya `origin/main` kodu okunarak yazılmıştır (son güncelleme: 2026-11-14). Main'e birleşenler: PR #1, #4, #6, #7, #9, #11, #12, #13, #14. Açık PR'larda olan ama henüz main'e girmemiş değişiklikler (#2, #3, #5, #8, #10, #15) "Bekleyen" olarak işaretlidir.

## 1. Amaç

Birden fazla veritabanı platformunun (PostgreSQL, MSSQL, MySQL, MariaDB, Oracle, genel ODBC) DWH sağlığını tek bir ortak ölçüm modeliyle izler. Sonuçlar PostgreSQL'e yazılır, Prometheus formatında sunulur ve alarm kurallarına bağlanır.

## 2. Katmanlar

```
config/databases.yaml ──► AdapterRegistry ──► DBAdapter (5 platform)
                                                  │ collect_metrics()
                                                  ▼
                          CollectorEngine (APScheduler + circuit breaker)
                           │            │              │
                           ▼            ▼              ▼
                     monitor.dwh_    Notifier     RetentionManager
                     health_log     (SMTP/Slack/   (aylık, arşive taşır)
                     (PostgreSQL)   PagerDuty/
                           │        Teams/webhook)
                           ▼
                   FastAPI (api/main.py)  ──►  Prometheus ──► Alertmanager
```

## 3. Bileşenler

| Bileşen | Dosya | Görev |
|---|---|---|
| Ortak sözleşme | `core/base_adapter.py` | `DBAdapter` ABC, `HealthResult`, `DBMetadata`, `AdapterError` ailesi |
| Veri modeli | `core/metric_schema.py` | `MetricSchema` (Pydantic), `Sonuc` (OK/WARNING/ERROR), Prometheus ve log satırı dönüşümü |
| Yükleyici | `core/adapter_registry.py` | YAML okur, adapter sınıfını `importlib` ile yükler, `vault://` referanslarını çözer |
| Zamanlayıcı | `core/collector_engine.py` | Saatlik toplama (`COLLECT_CRON`, varsayılan `0 * * * *`), adapter başına circuit breaker (3 hata → 300 sn bekleme), sonuçları loga yazar. Bağlantı/sağlık hatası veren veya devresi açık DB için o tura ERROR metriği üretir (kategori `sistem`, `kontrol_kodu` `FR-SYS-01`, severity 3). Aynı anda tek tur: toplama kilidi alınamazsa scheduler turu atlar, elle istek `CollectionBusy` alır. Açılışta cron'u beklemeden bir toplama yapılır (PR #14) |
| Bildirim | `core/notifier.py` | SMTP, Slack, PagerDuty, Teams, genel webhook; DB'ye bağımlı değil |
| Saklama | `core/retention_manager.py` | 24 ay aktif saklama, eski satırları tek CTE ifadesiyle arşiv tablosuna taşır; `RETENTION_CRON` varsayılan `0 1 1 * *` |
| Adapter'lar | `adapters/*.py` | `postgresql` (8 FR), `mssql` (8 FR), `mysql` (MySQL + MariaDB), `oracle`, `generic_odbc` (3 FR) |
| API | `api/main.py`, `api/logs.py`, `api/auth.py` | Aşağıda |

Yeni DB eklemek için `DBAdapter`'ı miras alan bir sınıf yazıp `databases.yaml`'a blok eklemek yeterlidir; motor kodu değişmez.

Sonuç değerleri: `OK`, `WARNING`, `ERROR`. Severity 1–3. **Bekleyen (PR #3):** MSSQL'de yetki hatası ve okunamayan DDM durumunda `ERROR` (severity 3) döndürülür; main'de bazı yollar `WARNING` döner.

## 4. Veri modeli

- DB: `dwhmonitor`, şema `monitor`.
- `monitor.dwh_health_log` — `kontrol_tarihi`'ne göre RANGE bölümlü, PK `(id, kontrol_tarihi)`. Aylık bölüm `add_monthly_partition(date)` ile eklenir.
- `dwh_health_log_archive` — 24 aydan eski satırlar.
- View'lar: `v_son_24s_ozet`, `v_aktif_sorunlar`, `v_trend_7gun`.
- DDL: `sql/dwh_health_log.sql` (kopya: `docs/sql/`).

## 5. API

| Endpoint | Auth | Açıklama |
|---|---|---|
| `GET /health` | yok | `status`: `ok` veya `degraded` (tüm devreler açıksa; engine hazır değilse `starting`), `persist_ok` (son log yazımı başarılı mı), `circuits` |
| `GET /metrics` | API anahtarı | Prometheus formatı |
| `GET /collect` | API anahtarı | Elle toplama tetikler; toplama zaten çalışıyorsa HTTP 409 |
| `GET /logs/summary` | API anahtarı | Kategori bazlı özet |
| `GET /logs` | API anahtarı | Filtreli liste: `db_name`, `kontrol_kodu`, `sonuc`, `severity`, `since`, `until`, `limit` (≤1000), `offset` |
| `GET /adapters` | API anahtarı | Adapter'ların circuit breaker durumları |

`API_KEY` ortam değişkeni tanımlıysa `/health` dışındaki endpoint'ler `X-API-Key` başlığı ister (`secrets.compare_digest`, yanlışsa 401). Tanımsızsa doğrulama kapalıdır ve başlangıçta uyarı loglanır (geriye dönük davranış). Prometheus kullanıyorsan scrape yapılandırmasına başlık eklemek gerekir.

## 6. Yapılandırma

`config/` altında: `databases.yaml`, `notifications.yaml`, `retention.yaml`, `alertmanager.yml`, `prometheus/prometheus.yml`, `prometheus/rules/dwh-health.yml` (6 alarm kuralı: `DWHCriticalHealthIssue`, `DWHSecurityThreat`, `DWHPipelineBreakdown`, `DWHWarningIssue`, `DWHMultipleCategoriesCritical`, `DWHAllAdaptersDown`). Kurallar PR #11 ile örnek değerine göre yazıldı (OK=0, WARNING=2, ERROR=3) ve pencerelidir: `last_over_time(dwh_health_check[70m])`; `DWHAllAdaptersDown` `absent_over_time(dwh_health_check[2h])` kullanır. Pencereler saatlik `COLLECT_CRON` varsayılanına göre seçilmiştir; cron değişirse ayarlanmalıdır. Metrikte `severity` etiketi yoktur (`severity` yalnızca alarm etiketidir). Açıklamalı örnekler `docs/config/` altındadır.

Monitor'ün kendi log DB bağlantısı ortam değişkenlerinden gelir: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASS`. `DB_PASS` zorunludur, kodda varsayılan şifre yoktur.

**Bekleyen (PR #5):** YAML yükleyicileri `${NAME}` ortam değişkenlerini açar; böylece `databases.yaml`'daki şifreler `.env`'e taşınır. Değişiklik uyumsuzdur: dağıtımda 8 değişkenin tanımlı olması gerekir.

## 7. Dağıtım

`docker-compose.yml` servisleri: `postgres` (container `dq-postgres`, host portu 127.0.0.1:5433), `dwh-monitor` (127.0.0.1:8005), `prometheus` (9090), `alertmanager` (9093), `vault` (8200, dev). Tüm portlar yalnızca 127.0.0.1'e bağlıdır. `DQ_DB_PASSWORD` `.env`'den zorunlu okunur.

DB kullanıcısı `apache` (PR #9 main'de; `api/main.py` varsayılanı `apache`).

**Bekleyen:** Helm chart (PR #8, F6-01, taslak).

Sunucuda nginx yalnızca `/health` yolunu dışarıya açar; diğer yollar 403 döner (`return 403;`). `nginx -t` doğrulanamadı (DOĞRULANAMADI).

CI: `.github/workflows/ci.yml` — ruff, py_compile + pytest, docker build (PR'larda ve main'e push'ta).

## 8. Sır yönetimi (Vault, F6-02)

Kod tarafı: `adapter_registry._resolve_credentials()` `credentials: vault://db/<ad>` değerini hvac ile Vault KV v2'den (`secret/data/db/*`) çözer (`core/adapter_registry.py`); Vault erişilemezse kimlik bilgileri olduğu gibi kalır. İki biçim desteklenir: tüm sözlük (`vault://db/ad`) veya tek alan (`password: vault://db/ad`). `scripts/vault-init.py` policy ve kimlik bilgilerini yükler.

Gerçek durum: Vault **dev modunda** (bellek içi, her açılışta rastgele token, veri kaybolur). `config/databases.yaml`'da `vault://` referansı yoktur, kimlik bilgileri düz metindir; monitor çalışma zamanında Vault'tan okumaz. Sunucuda Vault konteyneri durdurulmuştur. Üretim için sealed mod, kalıcı backend (file/Raft), servis hesabı token'ı ve audit log gerekir (K-02 açık).

## 9. Saklama

`RetentionManager`: `active_months: 24`, `archive_backend: local` (S3/Azure stub, K-06 açık; bu iki backend yalnızca log yazar, `core/retention_manager.py` içinde "henüz tam implemente edilmedi" — arşivleme yapılmaz), `batch_size: 10000`. Eski satırlar `WITH moved AS (DELETE ... RETURNING ...) INSERT ...` ile tek ifadede arşive taşınır. Bu düzeltme PR #2'de (taslak), main'de hâlâ eski kod vardır.

## 10. Dokümantasyon

`docs/config/` (7 YAML), `docs/sql/` (DDL). Kök dizindeki çalışma dosyaları: `CLAUDE.md` (proje kuralları), `task.md` (görevler), `session.md` (oturum günlüğü), `backlog.md` (fikir havuzu), `README.md` (genel tanıtım), `yedek.md` (yedekleme notları; git'te izlenmiyor), `.claude/` (ajan çalışma klasörü: worktree'ler, bulgular; izlenmiyor).
