# backlog.md — DWH DB Monitor Fikir Havuzu

Fazlara bölünmüş planlı iş `task.md`'de (Faz 0–6, açık kararlar K-01…K-07). Bu dosya henüz sıraya girmemiş fikirleri ve **rakip analizine bağlı bekleyen** maddeleri tutar; karar verilince `task.md`'ye taşınır.

## Rakip analizine bağlı bekleyenler (task.md "Rakip analizi")

- **F5-02 IBM DB2**, **F5-05 MongoDB**, **F5-06 Teradata** adapter'ları — öncelik Datadog, Grafana, SolarWinds, OpsRamp karşılaştırmasından sonra belirlenecek. Teradata için ayrıca BRD gerekli (K-05).

## Açık kararlardan türeyen işler

- **K-06 Cold storage**: eski ölçüm/log verisinin S3 / Azure Blob / yerel arşive taşınması ve saklama politikası.
- **K-07 `/metrics` erişim koruması**: API key yapıldı (PR #6). Kalan: Bearer JWT / IP whitelist ve Prometheus scrape'e `X-API-Key` başlığı eklenmesi.
- **K-02 Secrets**: Vault (F6-02) dev modda çalışıyor, düz metin fallback açık — prod modu (sealed, Raft/file backend, servis hesabı token'ı, audit log) ve fallback'in kapatılması.

## Ertelenmiş üretim işleri

- **F6-03 Grafana dashboard JSON** (deferred) — Prometheus metrikleri hazır, panolar yok.
- **F6-05 Yatay ölçekleme** — birden fazla worker için Redis tabanlı zamanlama koordinasyonu (APScheduler tek süreçte).

## Fikirler

- Kontrol sonuçlarını VCE / DQ projeleriyle ortak bir "kalite skoru" modelinde birleştirme.
- Adapter başına bağlantı testi CLI komutu (`scripts/`) — gerçek MSSQL/Oracle/MySQL bilgileri geldiğinde `enabled: true` öncesi doğrulama için.
- Sunucudaki `docker-compose.yml` ve `config/` değişikliklerini git'te tutmak (`.bak` kopyaları silindi; ayrı bir deploy deposu veya PR #5 sonrası `.env` ayrımı).
- Harici (Windows aylık disk) yedek kopyasını doğrulamak. `pg_dump` + `config/` 2026-11-12'de gece yedeğine eklendi.
- Vault kararı: kalıcı üretim Vault kurmak ya da Vault'u ve `vault://` kodunu kaldırmak (şu an dev modda ve durdurulmuş).
- Zayıf DB parolasını güçlü bir değerle değiştirmek (sunucuda).

## Ekleme Şablonu

```markdown
### Başlık
- **Kategori:** yeni özellik / iyileştirme / teknik borç / araştırma
- **Neden:** kısa gerekçe
- **Notlar:** büyüklük, bağımlılıklar, riskler
```
