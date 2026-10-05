# backlog.md — DWH DB Monitor Fikir Havuzu

Fazlara bölünmüş planlı iş `task.md`'de (Faz 0–6, açık kararlar K-01…K-07). Bu dosya henüz sıraya girmemiş fikirleri ve **rakip analizine bağlı bekleyen** maddeleri tutar; karar verilince `task.md`'ye taşınır.

## Rakip analizine bağlı bekleyenler (task.md "Rakip analizi")

- **F5-02 IBM DB2**, **F5-05 MongoDB**, **F5-06 Teradata** adapter'ları — öncelik Datadog, Grafana, SolarWinds, OpsRamp karşılaştırmasından sonra belirlenecek. Teradata için ayrıca BRD gerekli (K-05).

## Açık kararlardan türeyen işler

- **K-06 Cold storage**: eski ölçüm/log verisinin S3 / Azure Blob / yerel arşive taşınması ve saklama politikası.
- **K-07 `/metrics` erişim koruması**: API key, Bearer JWT veya IP whitelist — Prometheus scrape yapılandırmasıyla birlikte.
- **K-02 Secrets**: Vault (F6-02) dev modda çalışıyor, düz metin fallback açık — prod modu (sealed, Raft/file backend, servis hesabı token'ı, audit log) ve fallback'in kapatılması.

## Ertelenmiş üretim işleri

- **F6-03 Grafana dashboard JSON** (deferred) — Prometheus metrikleri hazır, panolar yok.
- **F6-05 Yatay ölçekleme** — birden fazla worker için Redis tabanlı zamanlama koordinasyonu (APScheduler tek süreçte).

## Fikirler

- Kontrol sonuçlarını VCE / DQ projeleriyle ortak bir "kalite skoru" modelinde birleştirme.
- Adapter başına bağlantı testi CLI komutu (`scripts/`) — gerçek MSSQL/Oracle/MySQL bilgileri geldiğinde `enabled: true` öncesi doğrulama için.
- Tekrarlayan bozuk `docker-compose.yml.bak` / `.backup` kopyalarını temizleyip değişiklikleri git'te tutmak.

## Ekleme Şablonu

```markdown
### Başlık
- **Kategori:** yeni özellik / iyileştirme / teknik borç / araştırma
- **Neden:** kısa gerekçe
- **Notlar:** büyüklük, bağımlılıklar, riskler
```
