# DWH İzleme Sistemi — Oturum Özeti

> Sıra: en yeni oturum en üstte. 11. ve 12. oturumlardaki "Sonraki" listeleri o günün durumudur; güncel liste `task.md`'dedir.
> Not: numaralar 2026-08 kayıtlarında çakışıyordu; ayırt için harf eklendi (11a, 11b, 12a, 12b).

## Oturum 15 — PR #2 birleştirme, sır dosyalarının git'ten çıkarılması, sunucu dağıtımı, md güncellemesi (2026-11-25)

### Yapılanlar
1. **PR #5 kapatıldı** (taslak, yerine PR #18 birleşti). Kapatma yorumu yazıldı.
2. **PR #2, #3, #8 CI'a bağlandı:** Dallarda `ci.yml` yoktu, CI çalışmıyordu. Her dal `origin/main` ile birleştirilip push edildi (`7d60963`, `5582b78`, `ddea741`). Lint, Test ve Docker build geçti.
3. **PR #2 için birim testleri ve doğrulama:** `tests/test_retention_manager.py` (6 test) ve `batch_size < 1` doğrulaması eklendi (`604f4a4`). `batch_size: 0` döngüyü sonsuz yapıyordu. Gerçek PostgreSQL'de (pgserver) doğrulandı: 25 arşiv, 5 kalan, arşivde tekrar yok, dry-run değişiklik yapmıyor, `batch_size: 0` reddediliyor. Bağımsız doğrulayıcı `PASS_WITH_NOTES` verdi (engelleyici yok; `_export_local` 1 saat penceresi ve dry-run'da `CALL` notları ayrı iş). CI yeşil. **PR #2 main'e birleşti (`b0c0e5c`).**
4. **PR #3 ve #8 açıklamaları** CI durumu ve açık risklerle güncellendi. Helm `values.yaml` içindeki `DB_USER: "dquser"` düzeltildi (`df64bce`, `apache`). Helm config kopyalarındaki parola satırlarının tamamı `REPLACE_ME` olduğu kontrol edildi.
5. **Sunucu analizi (salt okunur):** disk %92 (17 GB boş). Sunucu repo'su `f53b1ad`'de, GitHub `main`'den ayrışmış, 34 yerel değişiklik. Sunucu kodunda sabit bir parola varsayılanı varsayılanı vardı; compose'da `POSTGRES_PASSWORD` ve `DB_PASS` düz metindi; healthcheck `dqmetrics` kullanıyordu (gerçek DB `dwhmonitor`). Restic politikası zaten mevcut (14 gün / 8 hafta / 12 ay + prune); ek silme yapılmadı.
6. **Dağıtım (onaylı):** Yedek `/root/yedekler/pre-deploy-20261125-1308` (sır dosyaları, eski compose, DB dump, yerel değişiklik patch'i; hepsi mod 600). Mevcut Postgres parolası `.env`'e `DQ_DB_PASSWORD` olarak kopyalandı (değer yazdırılmadı). Sunucu repo'su `origin/main` `b0c0e5c`'ye alındı, `config/databases.yaml` yedekten geri konuldu. Yalnızca `dwh-monitor` yeniden build edilip başlatıldı (`--no-deps`, Postgres'e dokunulmadı). `/health` → `persist_ok: true`.
7. **Hata ve düzeltme:** Git reset'i `umask 077` ayarlıyken yapıldığı için 48 dosya mod 600 oluştu; Prometheus kuralları okuyamadı (`permission denied`). Dosyalar 644 yapıldı, sır dosyaları 600 kaldı. Sonra `promtool` (6 kural) ve `amtool` doğrulandı, Prometheus ve Alertmanager yeniden başlatıldı. Hedefler: alertmanager, dwh-metrics, prometheus hepsi `up`. Firing alarm 0.
8. **Geri alma:** Eski imaj `dwh-db-monitor-dwh-monitor:rollback-20261125` olarak etiketli. Bu imajda sabit bir parola varsayılanı var; stabil çalışma sonrası silinecek.
9. **Açık kalanlar:** Parolaların döndürülmesi (apache, etl_svc, SMTP, Postgres); Alertmanager alıcısı (`localhost:5001` gerçek alıcı değil); K-02 Vault kararı; PR #3 (staging MSSQL) için doğrulama; PR #15 CI düzeltmesi.
10. **PR #8 (Helm) birleşti (merge `66c3d48`, CI commit `55c6c2c`):** Helm lint ve template CI job'ı eklendi, yerelde ve CI'da geçti. Render çıktısındaki kimlik satırları yer tutucu. Doğrulayıcı PASS_WITH_NOTES.
11. **PR #20 (JSONL export) birleşti:** Eski "son 1 saat" penceresi, aynı saatteki turlarda satır tekrarına yol açıyordu. Gerçek PostgreSQL'de eski kod 53 satır, yeni kod 28 satır (olması gereken 28) üretti. Doğrulayıcı PASS_WITH_NOTES.
12. **PR #19 (md güncellemesi) birleşti (`06e5915`).** Doğrulayıcı PASS_WITH_NOTES; sunucu tarafı iddiaları ayrıca SSH ile doğrulandı.
13. **İç adres temizliği:** `docs/config`, `helm/files/config`, `README.md`, `config/databases.example.yaml`, `config/notifications.yaml` içindeki iç IP'ler ve kurumsal adresler yer tutucuya çevrildi. `tests/` ve `scripts/vault-init.py` bilerek değiştirilmedi (test fixture ve kod).

### Bulgular
- Sır dosyaları git'ten çıkarıldı (`587146d`), ama repo herkese açık ve geçmişte düz metin parolalar hâlâ var. Döndürme olmadan geçmiş temizliği bir koruma değildir.
- Dağıtımda `.env`'in tam içeriği main'in compose'unun beklediği değişkenlerle karşılaştırıldı: yalnızca `DQ_DB_PASSWORD` ve `VAULT_TOKEN` (değerler gösterilmedi).
- Doğrulayıcı agent'ın ilk denemesinde CI sorgusu araç hatasıyla başarısız oldu; CI durumu lead tarafından ayrıca doğrulandı.

### Sonraki
Bkz. `task.md` "Sonraki oturumda yapılacaklar". Öncelik: döndürme, ardından `.env` güncellemesi ve `dwh-monitor` restart'ı.

---

## Oturum 14 — Kapsam katmanı, PR birleştirme, sunucu nginx kısıtlaması, md denetimi (2026-11-13..24)

### Yapılanlar
1. PR birleştirmeleri (2026-11-13, `gh pr list` ile MERGED): #13 (CI pytest adımı: httpx, DB_PASS, `python -m`), #14 (collector: düşen DB izi, persist durumu, açılış toplaması, kilit; F08–F13), #11 (alarm kuralları değere göre ve zaman damgasına uygun; F02–F04), #12 (compose: doğru DB adı, oracledb bağımlılığı, parolasız roller; F06, F07, F20), #9 (kullanıcı `dquser` → `apache`).
2. Kapsam katmanı (alt ajanlar için) `chore/agent-scope-layer` dalında 3 commit: `bccc475` (hook, kapsam denetimi, sözleşme örneği), `00d66a3` (alt ajan deny, kanıt denetimi, tur sayacı), `7e3153b` (satır sonu ayırıcı açığı ve tur sayacı atomikliği). PR #15 taslak olarak açık.
3. Sunucu nginx: DWH bloğunda satır 8 `return 403;` (`.claude/findings/facts.json`, 2026-11-14 tarihli). `nginx -t` sonucu alınamadı.
4. Sunucu yedekleri (facts.json, 2026-11-14 tarihli): restic çalışması OK (2026-11-14 04:33:12, snapshot `fcace2e3`, depo 24G), restic cron uyarısı 0. `pg_dump` dosyaları 11-12, 11-13 ve 11-14 (04:30) için mevcut.
5. md denetimi, doküman commit'leri (doğrulanmadı): `CLAUDE.md` `7e33481` (`agent/doc-claude`), `architect.md` `a8cc893` (`agent/doc-architect`), `README.md` `e0a25eb` (`agent/doc-readme`), `backlog.md` `5012d4a` (`agent/doc-backlog`). Bu commit'ler origin/main'de yok (2026-11-24, `git merge-base --is-ancestor`).
   Not (2026-11-24): İçerikler origin/main'e farklı hash'lerle girdi: `cede537` (CLAUDE), `401e313` (architect), `928eab6` (README), `9f54572` (backlog); `3db0739`, `429e128`, `1682956` (session/task düzeltmeleri). Hepsi PR #10 (`1301be4`) ile birleşti.
6. `task.md` düzeltmesi (`249b05b`) doküman dalına alındı (`docs/update-md-status`'ta `1682956`).
7. PR #10 (doküman) birleştirildi (1301be4, 2026-11-24). PR #16 (`agent/doc-status`, `9507217`) birleştirildi (merge `12402de`, 2026-11-24).
8. Doküman doğrulama turu (2026-11-24): session, architect, backlog, README (örnek parola ve Vault bölümü), task ve CLAUDE, origin/main 12402de'ye göre kontrol edildi. Doğrulanamayan maddeler etiketli bırakıldı (`config/databases.yaml` okunamadı; sunucu durumu 2026-11-14 kaydı).
9. PR #15 (`chore/agent-scope-layer`, `bccc475`, `00d66a3`, `7e3153b`) DRAFT olarak kalır. İkinci bağımsız doğrulama tamamlanmadı; commit'ler origin/main'de yok (2026-11-24).

### Açık kalanlar (2026-11-24 durumu; sunucu maddeleri 2026-11-14 kaydıdır)
- Alertmanager webhook adresi: `config/alertmanager.yml` 16. satır `http://localhost:5001/alerts` (kod kontrolü 2026-11-24). Compose'da 5001'i dinleyen servis yok; gerçek alıcı tanımlı değil. Karar bekliyor.
- Sunucu dağıtımı: `dwh-monitor` imajı yeniden build edilecek ve yerel değişiklikler sunucuya alınacak. Onay bekliyor. İmaj 2026-11-09 tarihli; F08–F13 düzeltmelerini içerip içermediği doğrulanamadı (2026-11-14 itibarıyla, doğrulanamadı).
- Vault konteyneri çalışmıyor (2026-11-14 itibarıyla, facts.json `vault_running: 0`; doğrulanamadı); monitor çalışma zamanında Vault'tan okumuyor (kod kontrolü 2026-11-24).
- Sunucu diski %85 dolu (30G boş) (2026-11-14 itibarıyla; doğrulanamadı).
- F05: `API_KEY` ve Prometheus başlığı kararı açık (kod kontrolü 2026-11-24: `config/prometheus/prometheus.yml` `dwh-metrics` job'ında başlık yok).
- PR #5 (düz metin parola konusu): DRAFT, açık karar. Oturum 13 kaydına göre düz metin kimlik bilgileri repoda ve sunucuda vardı; sunucudaki güncel durum doğrulanamadı.
- Kapsam katmanı PR #15: DRAFT; ikinci bağımsız doğrulama bekliyor.
- Taslak PR'lar (2026-11-24, `gh pr list`): #2, #3, #5, #8, #15.
- PR birleşmeleri origin/main'de doğrulandı (2026-11-24).

### Sonraki
- Kapsam katmanı PR #15 için ikinci bağımsız doğrulama.
- Sunucu dağıtım onayı ve Alertmanager alıcı kararı.
- Vault kararı (K-02) ve PR #5 sonrası `.env` geçişi.
- Bkz. `task.md` "Sonraki oturumda yapılacaklar".

---

## Oturum 13 — Sunucu ↔ GitHub senkronu, güvenlik ve yedek denetimi (2026-11-08..12)

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
## Oturum 11a — F6-02 Vault Setup (2026-08-14)

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

## Oturum 12a — F6-04 Prometheus Alert Rules (2026-08-14)

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
   - Not: o tarihte alertmanager.yml inhibit_rules: [] idi; düzeltme PR #11 ile birleşti.

3. docker-compose.yml — Prometheus + Alertmanager services
4. prometheus.yml — scrape config (dwh-monitor:8005 scraping)

### Test Results
- Prometheus: http://localhost:9090 UP
- Alertmanager: http://localhost:9093 UP
- Targets: dwh-metrics UP (8 metrics scraping)
- Metrics: postgresql adapter 8 kontrol, tüm OK
- Alerts: 0 (tüm kontrol'ler başarılı)
- Not: kurallar hiçbir seriyle eşleşmiyordu (severity etiketi yoktu); 0 alarm bu nedenle başarı kanıtı değildi. Bkz. PR #11.

### Issues & Resolutions
- Vault dev-mode: restart'ta data kayboldu → credentials plain text YAML'a taşındı
- Prometheus scrape: localhost → container name (dwh-monitor:8005)
- Alert test: manuel test alert eklendi ama adapter kontrol'lerine ağırlık yok

### Next Steps
1. Slack webhook URL ayarla (alertmanager.yml'de)
2. F6-06 — Dokümantasyon
3. Production Vault setup (sealed mode)

---

## Oturum 11b — F6-06 Dokümantasyon Tamamlandı

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

## Oturum 12b — GitHub README.md

### Yapılanlar
- Kapsamlı GitHub README.md oluşturuldu (14.8 KB, 389 satır)
- Base64 yöntemiyle sunucuya yazıldı (backtick/heredoc çakışması nedeniyle)
- Commit: e7a1183 → main
- Not (2026-11-24): commit e7a1183 tarihi `git log`'da 2026-08-26; önceki kayıtlardaki 2026-08-16 tarihi hatalıdır (CLAUDE.md ve task.md düzeltildi).

### README İçeriği
- Badges, architecture diagram (ASCII), features, health check categories
- Supported databases tablosu, quick start, configuration örnekleri
- API endpoints, alerting (6 rule), database schema, adding new DB
- Ports, Vault integration, retention, project status, tech stack

### Sonraki Oturum Seçenekleri
1. F6-01 — Kubernetes Helm chart
2. Rakip analizi (Datadog, Grafana, SolarWinds, OpsRamp)
3. F3-04/05/06 — API log endpoints (/logs, /logs/summary, /adapters)
