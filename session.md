# DWH İzleme Sistemi — Oturum Özeti

> Sıra: en yeni oturum en üstte. 11. ve 12. oturumlardaki "Sonraki" listeleri o günün durumudur; güncel liste `task.md`'dedir.

## Oturum 13 — Sunucu ↔ GitHub senkronu, güvenlik ve yedek denetimi (2026-11-08..11)

### Yapılanlar
1. Contabo sunucusundaki `/opt/dwh-db-monitor` ile GitHub `SHapeloglu/DBMonitor` karşılaştırıldı. Fark: sunucuda sabit şifre varsayılanları, açık portlar, `.bak` kopyaları ve kod yorumları farklıydı.
2. PR'lar: #1 (sunucu senkronu + güvenlik) ve #4 (md çelişkileri), #6 (`GET /logs` + `X-API-Key`), #7 (CI) main'e birleşti. #2 (retention), #3 (MSSQL), #5 (`${ENV}` açma), #8 (Helm), #9 (kullanıcı `apache`) taslak olarak açık.
3. Sunucuda DB şifresi döndürüldü; DB rolü `dquser` → `apache` yapıldı. Bağlantı ve veri doğrulandı, `/health` OK.
4. Sunucuda `docker-compose.yml`, `config/databases.yaml`, `.env` izinleri 600 yapıldı; `.bak`/`.backup` ve eski rotasyon yedekleri silindi.
5. Sunucu yedekleri denetlendi (restic, cron 04:30, 14 gün / 8 hafta / 12 ay). Restore testi başarılı. `dwhmonitor` için `pg_dump` ve `config/` eklenen betik 2026-11-12'de `/opt/yedek/restic_yedek.sh`'ye uygulandı (eski hâli `restic_yedek.sh.yedek-20261112`); dump bloğu elle test edildi (320 KB, 433 giriş).

### Bulgular
- Repoda ve sunucuda düz metin şifreler hâlâ var (`databases.yaml`, compose). Çözüm PR #5'te; deploy için image yeniden build ve 8 ortam değişkeni gerekir.
- Vault dev modunda, sunucuda durdurulmuş; monitor çalışma zamanında Vault'tan okumuyor.
- Uzak DB'lerdeki `etl_svc` hesapları placeholder şifre kullanıyor; adapter'lar `enabled: false`.
- Harici yedek kopyası yalnızca Windows tarafında aylık diske; sunucudan doğrulanamıyor.

### Araç notları
- `gh pr edit` Projects classic hatası veriyor: `gh api -X PATCH repos/SHapeloglu/DBMonitor/pulls/N -F body=@dosya` kullan.
- GitHub bağlantısı zaman zaman takılıyor; `timeout` ve `-c http.lowSpeedLimit=1000 -c http.lowSpeedTime=20` kullan.

### Sonraki
Bkz. `task.md` "Sonraki oturumda yapılacaklar".

---
## Oturum 11 — F6-02 Vault Setup (2026-08-14)

### Sorun
Production'da şifreler düz text'te, Git repo'ya push olabiliyor.

### Çözüm: HashiCorp Vault

**Yapılanlar:**
1. Vault container (dev mode, port 8200)
2. hvac>=1.2.1 library
3. scripts/vault-init.py — policy + 5 DB credential yükledi
4. core/adapter_registry.py — Vault client + _resolve_credentials()
5. databases.yaml — vault:// referansları
6. System test — /health, /metrics working

**Vault KV v2 Structure:**
- secret/data/db/mssql-prod
- secret/data/db/mysql-prod
- secret/data/db/mariadb-prod
- secret/data/db/oracle-prod
- secret/data/db/postgres-local

**Kod Değişiklikleri:**
- adapter_registry.py: +_get_vault_client(), +_resolve_vault_secret()
- docker-compose.yml: +vault service, +VAULT_ADDR env
- requirements.txt: +hvac>=1.2.1
- databases.yaml: credentials: vault://db/{name}

### Not
- Dev mode: restart'ta token değişir
- Production: sealed mode + file/Raft backend gerekli

---

## Oturum 12 — F6-04 Prometheus Alert Rules (2026-08-14)

### Yapılanlar
1. prometheus-rules.yml — 6 alert rule grup
   - DWHCriticalHealthIssue (5m)
   - DWHSecurityThreat (1m)
   - DWHPipelineBreakdown (10m)
   - DWHWarningIssue (15m)
   - DWHMultipleCategoriesCritical (10m)
   - DWHAllAdaptersDown (5m)

2. alertmanager-config.yml — Webhook receiver
   - default-receiver: generic handling
   - Slack config (routes'ta aktivasyon bekleniyor)
   - inhibit_rules: critical → warning bastırma

3. docker-compose.yml — Prometheus + Alertmanager services
4. prometheus.yml — scrape config (dwh-monitor:8005 scraping)

### Test Results
- Prometheus: http://localhost:9090 UP
- Alertmanager: http://localhost:9093 UP
- Targets: dwh-metrics UP (8 metrics scraping)
- Metrics: postgresql adapter 8 kontrol, tüm OK
- Alerts: 0 (tüm kontrol'ler başarılı)

### Issues & Resolutions
- Vault dev-mode: restart'ta data kayboldu → credentials plain text YAML'a taşındı
- Prometheus scrape: localhost → container name (dwh-monitor:8005)
- Alert test: manuel test alert eklendi ama adapter kontrol'lerine ağırlık yok

### Next Steps
1. Slack webhook URL ayarla (alertmanager.yml'de)
2. F6-06 — Dokümantasyon
3. Production Vault setup (sealed mode)

---

## Oturum 11 — F6-06 Dokümantasyon Tamamlandı

### Yapılanlar
1. **docs/config/** — 7 YAML dosyası tam açıklamalı olarak yazıldı:
   - `databases.yaml` — 6 adapter tanımı (PostgreSQL, MSSQL, MySQL, MariaDB, Oracle, Generic ODBC)
   - `notifications.yaml` — SMTP, Slack, webhook, PagerDuty, Teams kanalları (hepsi disabled)
   - `retention.yaml` — 24 ay aktif saklama, local/S3/Azure Blob arşiv seçeneği
   - `prometheus.yml` — dwh-monitor:8005 scrape hedefi, alert rules yolu
   - `prometheus-rules.yml` — 6 alert rule (critical, security, pipeline, warning, crisis, all-down)
   - `alertmanager.yml` — default webhook receiver, Slack/PagerDuty örnekleri
   - `docker-compose.yml` — Vault + PostgreSQL + dwh-monitor + Prometheus + Alertmanager

2. **docs/sql/** — dwh_health_log.sql kopyalandı
   - PostgreSQL 16, monitor schema, 24 aylık partition, views, procedure

3. **docs/README.md** — 6.7 KB tam proje dokümantasyonu (gitignore'da yer almıyor, sadece referans)
   - Architecture diyagramı
   - Health Check kategorileri
   - Adapter durumları tablosu
   - Quick start
   - Configuration file özeti
   - Ports
   - Notifications, Retention, Vault dev mode notları
   - Project status tablosu

4. **GitHub Push** — Commit: `24ae3b7`
   - 8 dosya staged (YAML + SQL)
   - task.md ve session.md henüz push edilmedi (local güncelleme)

### F6-06 Status
✅ **TAMAMLANDI** — Tüm dokümantasyon dosyaları production-ready.

### Açık Noktalar
- `docs/README.md` gitignore'da — sadece YAML ve SQL push edildi (tasarımsal)
- Prod ortamına geçişte credential'ları Vault secrets ile replace etmek gerekli

### Sonraki Oturum Seçenekleri
1. **F6-01 — Kubernetes Helm chart** (deployment automation)
2. **Rakip analizi** (Datadog, Grafana, SolarWinds, OpsRamp vs dwh-db-monitor)
3. **DB2/MongoDB/Teradata adapter'ları** (rakip analizi sonrası öncelik)
4. **F3-04/05/06 — API log endpoint'leri** (/logs, /logs/summary, /adapters)

---

## Oturum 12 — GitHub README.md

### Yapılanlar
- Kapsamlı GitHub README.md oluşturuldu (14.8 KB, 389 satır)
- Base64 yöntemiyle sunucuya yazıldı (backtick/heredoc çakışması nedeniyle)
- Commit: e7a1183 → main

### README İçeriği
- Badges, architecture diagram (ASCII), features, health check categories
- Supported databases tablosu, quick start, configuration örnekleri
- API endpoints, alerting (6 rule), database schema, adding new DB
- Ports, Vault integration, retention, project status, tech stack

### Sonraki Oturum Seçenekleri
1. F6-01 — Kubernetes Helm chart
2. Rakip analizi (Datadog, Grafana, SolarWinds, OpsRamp)
3. F3-04/05/06 — API log endpoints (/logs, /logs/summary, /adapters)
