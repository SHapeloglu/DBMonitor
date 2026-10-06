
---

## 10. Sır Yönetimi — Vault Entegrasyonu (F6-02)

### Vault Mimarisi

databases.yaml (credentials: vault://db/name)
↓
adapter_registry.py (_resolve_credentials)
↓
hvac.Client (http://localhost:8200)
↓
Vault KV v2 (secret/data/db/*)
↓
db_conf["credentials"] = {user, password, host, port}
↓
adapter.init() → connect()
### Vault Kurulumu
- Image: hashicorp/vault:latest
- Port: 8200
- Mod: dev (bellek içi, otomatik unseal)
- KV v2 mount: secret/

### Uygulama
- Tembel yükleme: _vault_client singleton
- Yedek: Vault erişilemezse → kimlik bilgileri değiştirilmeden kalır
- İki format da destekleniyor:
  - credentials: vault://db/name (sözlüğün tamamı)
  - credentials: {password: vault://db/name} (tek alan)

### Üretim Değerlendirmeleri
- Dev modu verisi yeniden başlatmada kaybolur
- Sealed mod + kalıcı backend (file/Raft/S3) kullan
- Servis hesabı token'ı + denetim loglaması

---

## 10. Sır Yönetimi — Vault Entegrasyonu

### Mimari
Vault KV v2 sırları → adapter_registry → db kimlik bilgileri

### Bileşenler
- Vault konteyneri (port 8200, dev modu)
- hvac istemcisi (Python)
- Policy: db-credentials (path "secret/data/db/*")
- Sırlar: 5 DB kimlik bilgisi (mssql, mysql, mariadb, oracle, postgres)

### Uygulama
adapter_registry.py:
- _get_vault_client(): Lazy-load hvac.Client
- _resolve_vault_secret(path): Vault'tan secret çek
- _resolve_credentials(db_conf): credentials'ta vault:// varsa resolve et

### Kullanım
databases.yaml:
credentials: vault://db/postgres-local
Load time'da adapter_registry şifreleri Vault'tan çeker.

### Üretim Notları
- Dev modu: bellek içi, restart'ta kaybolur
- Üretimde sealed mod + file/Raft/S3 backend kullan
- Servis hesabı token'ı + denetim loglaması gerekli

---

## 10. F6-06 Dokümantasyon — Production-Ready Configs

`docs/config/` altında 7 YAML dosyası ve `docs/sql/` altında DDL şeması.
Tüm deployment artifact'ları annotated, örnek değerler ve Vault path'ları ile hazır.

**docs/README.md** gitignore'da — sadece YAML + SQL push edilir.

---

## 11. GitHub README.md

Repo ana sayfasında kapsamlı README yayında.
Mimari diagram, adapter tablosu, quick start, API docs, alert rules dahil.
Commit: e7a1183
