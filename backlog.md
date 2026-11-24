# backlog.md — DWH DB Monitor Fikir Havuzu

Fazlara bölünmüş planlı iş `task.md`'de (Faz 0–6, açık kararlar K-01…K-07). Bu dosya henüz sıraya girmemiş fikirleri ve **rakip analizine bağlı bekleyen** maddeleri tutar; karar verilince `task.md`'ye taşınır.

## Rakip analizine bağlı bekleyenler (task.md "Rakip analizi")

- **F5-02 IBM DB2**, **F5-05 MongoDB**, **F5-06 Teradata** adapter'ları — öncelik Datadog, Grafana, SolarWinds, OpsRamp karşılaştırmasından sonra belirlenecek. Teradata için ayrıca BRD gerekli (K-05).

## Açık kararlardan türeyen işler

- **K-06 Cold storage**: eski ölçüm/log verisinin S3 / Azure Blob / yerel arşive taşınması ve saklama politikası.
- **K-07 `/metrics` erişim koruması**: API key yapıldı (PR #6). Kalan: Bearer JWT / IP whitelist ve Prometheus scrape'e `X-API-Key` başlığı eklenmesi.
- **K-02 Secrets**: Vault (F6-02) kodu hazır ama sunucuda vault konteyneri durdurulmuş (2026-11-14 itibarıyla çalışmıyor; bugün doğrulanamadı), düz metin fallback açık — prod modu (sealed, Raft/file backend, servis hesabı token'ı, audit log) ve fallback'in kapatılması.

## Ertelenmiş üretim işleri

- **F6-03 Grafana dashboard JSON** (deferred) — Prometheus metrikleri hazır, panolar yok.
- **F6-05 Yatay ölçekleme** — birden fazla worker için Redis tabanlı zamanlama koordinasyonu (APScheduler tek süreçte).

## Fikirler

- Kontrol sonuçlarını VCE / DQ projeleriyle ortak bir "kalite skoru" modelinde birleştirme.
- Adapter başına bağlantı testi CLI komutu (`scripts/`) — gerçek MSSQL/Oracle/MySQL bilgileri geldiğinde `enabled: true` öncesi doğrulama için.
- Sunucudaki `docker-compose.yml` ve `config/` değişikliklerini git'te tutmak (`.bak` kopyaları silindi; ayrı bir deploy deposu veya PR #5 sonrası `.env` ayrımı). (2026-11-12 uygulandı: `config/` gece yedeğinde; kalan iş: harici kopya doğrulaması.)
- Harici (Windows aylık disk) yedek kopyasını doğrulamak. (2026-11-12 uygulandı: `pg_dump` + `config/` gece yedeğinde; kalan iş: harici kopya doğrulaması.)
- Vault kararı: kalıcı üretim Vault kurmak ya da Vault'u ve `vault://` kodunu kaldırmak (şu an dev modda ve durdurulmuş).
- ~~Zayıf DB parolasını güçlü bir değerle değiştirmek (sunucuda).~~ (REDDEDİLDİ — kullanıcı kararı; parola değiştirilmeyecek)

## Doğrulanmış bulgular — takipsiz olanlar

Kaynak: doğrulayıcı kararları (V1–V5), 2026-11-14. Bu F-kodları `task.md`'de yok. Biçim: kod — özet — ciddiyet — karar/durum.

- **F05** — Prometheus scrape işinde `X-API-Key` başlığı yok; `API_KEY` tanımlanırsa `/metrics` 401 verir — orta — CONFIRMED, açık.
- **F14** — Partition yalnızca 2026-12'ye kadar elle tanımlı, DEFAULT partition yok; `add_monthly_partition` sadece retention'dan çağrılıyor — yüksek — CONFIRMED, açık.
- **F15** — Vault boş sözlük dönerse `credentials` `vault://...` dizesi olarak kalır, adapter yine yüklenir — düşük — CONFIRMED, açık.
- **F16** — Bildirimde dedup/cooldown yok; her toplama turunda aynı uyarı tekrar gönderilir — orta — CONFIRMED, açık.
- **F17** — `ts` naive `utcnow` ile dolduruluyor, `timestamp()` yerel saat sayar; saat dilimi kayması riski — düşük — PLAUSIBLE, açık.
- **F18** — MSSQL/ODBC bağlantı dizesinde UID/PWD `{...}` kaçışı yok (`;` veya `}` içeren parola kırılır) — düşük — CONFIRMED, açık.
- **F19** — Adapter'larda TLS/şifreleme ayarı (`Encrypt`, `sslmode` vb.) yok — orta — CONFIRMED, açık.
- **F21** — Notifier eşikleri `eval` ile değerlendiriyor; boş `__builtins__` yeterli sandbox değil — düşük — CONFIRMED, açık.
- **F22** — Dockerfile'da `USER` ve `HEALTHCHECK` yok (root çalışır), bağımlılıklar `>=` ile sabitlenmemiş, `vault:latest` — orta — CONFIRMED, açık.
- **F23** — API özel `_open_connection` ve `CircuitBreaker` özel alanlarına kilitsiz erişiyor — düşük — CONFIRMED, açık.
- **F25** — Varsayılan kullanıcı üç dosyada hâlâ `dquser` (PR #9 sonrası `apache` ile tutarsız) — düşük — CONFIRMED. ✅ kapandı: PR #9 ile birleşti (2026-11-13); `dquser` origin/main'de yok.
- **F26** — `databases.yaml` iddiası: sır dosyası okunamadığından kanıt alınamadı — düşük — REJECTED (kanıtsız).
- **F27** — Test kapsamı: `tests/test_api.py` ve `tests/test_collector_engine.py` (PR #14). Notifier ve AdapterRegistry hâlâ testsiz; CircuitBreaker doğrudan test edilmiyor; RetentionManager yalnızca collector testinde dolaylı geçiyor (2026-11-24, `tests/` içeriği) — orta — CONFIRMED, kısmen açık.
- **F28** — `ruff.toml` yalnızca 4 kural grubu seçiyor (F401/F841 yakalanmaz); CI `tests/` yoksa atlıyor — düşük — CONFIRMED, açık.

PR'ı olan bulgular (bilgi için; durum 2026-11-24, `gh pr list`):

- **F01** — PR #2 (DRAFT, retention); **F24** — PR #2 (DRAFT, ölü kod temizliği). Açık.
- ✅ **F02, F03, F04** — PR #11 (MERGED).
- ✅ **F06, F07, F20** — PR #12 (MERGED).
- ✅ **F08, F09, F10, F11, F12, F13** — PR #14 (MERGED).
- ✅ **F25** — PR #9 (MERGED, 2026-11-13).

## Ekleme Şablonu

```markdown
### Başlık
- **Kategori:** yeni özellik / iyileştirme / teknik borç / araştırma
- **Neden:** kısa gerekçe
- **Notlar:** büyüklük, bağımlılıklar, riskler
```
