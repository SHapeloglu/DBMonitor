
---

## F6-02 Vault Entegrasyonu (Yeni)

Secrets merkezi yönetimi için HashiCorp Vault entegrasyonu yapıldı.

### Tasarım Kararı
- **Neden**: Şifreler düz metinde → güvenlik riski + Git'te ifşa
- **Nasıl**: Vault KV v2 + hvac istemcisi + adapter_registry kancası
- **Ne zaman**: Yükleme anında (kimlik bilgileri adapter registry'de çözümlenir)

### Kapsam
- Yalnızca veritabanı kimlik bilgileri (5 adaptör × {user, password})
- Uygulama sırları yok (henüz)
- Dinamik kimlik bilgisi yok (henüz)

### Dev ve Prod
- **Dev modu**: bellek içi, otomatik unseal, otomatik token üretimi
- **Prod modu**: sealed, file/Raft backend, servis hesabı token'ı, denetim logları

### Not
Vault token'ını koda gömmek anti-pattern'dir. Bunun yerine kullan:
- Kubernetes auth
- AWS IAM auth
- Ortam değişkeni + .gitignore

---

## F6-02 Vault Entegrasyonu (Oturum 11)

### Neden Vault?
Üretimde şifreler düz metin → güvenlik riski + Git'te ifşa.
Merkezi sır yönetimi gerekli.

### Neler Değişti
- Docker: Vault konteyneri (dev modu)
- Python: hvac istemcisi + adapter_registry entegrasyonu
- Yapılandırma: databases.yaml vault:// referansları
- Kurulum: VAULT_ADDR + VAULT_TOKEN ortam değişkenleri

### Nasıl Çalışır
1. adapter_registry.load_all() başladığında
2. Her DB config için _resolve_credentials() çağırılır
3. credentials: vault://db/name ise Vault'tan çeker
4. DB adaptörü çözümlenen kimlik bilgileriyle connect() yapar

### Dev ve Prod
- Dev: bellek içi, otomatik unseal, kolay test
- Prod: sealed mod, kalıcı backend, denetim logları

### Sonraki
F6-04 Prometheus alarm kurallarıyla devam et.

---

## F6-06 Dokümantasyon — Tamamlandı ✅

**2026-08-16 — F6-06 Tamamlandı**

7 YAML config file + SQL schema + README:
- Tümü production-ready, fully annotated
- Vault secret path örnekleri, plain-text backup notları
- GitHub: docs/config/, docs/sql/
- Push: commit 24ae3b7

**Next: F6-01 (Helm) veya Rakip Analizi?**

---

## GitHub README.md — Tamamlandı ✅

**2026-08-16 — Kapsamlı GitHub README push edildi**

Commit: e7a1183 — README.md (389 satır)

İçerik:
- Badges (Python, FastAPI, PostgreSQL, Prometheus, Docker)
- ASCII architecture diagram
- Health check categories tablosu (FR-COST/DQ/PIPE/USER/SEC)
- Supported adapters tablosu (6 adapter + driver + status)
- Quick start (4 adım)
- Configuration örnekleri (databases.yaml, notifications.yaml)
- API endpoints + Prometheus örnek çıktı
- Alert rules tablosu (6 kural)
- Database schema özeti (DDL, partitions, views)
- Adding a new database (3 adım, Teradata örneği)
- Vault integration notu
- Project status tablosu
- Tech stack tablosu

**Next: F6-01 (Helm) veya Rakip Analizi veya F3-04/05/06 (API log endpoints)**
