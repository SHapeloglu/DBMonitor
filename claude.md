
---

## F6-02 Vault Integration (New)

Secrets merkezi yönetimi için HashiCorp Vault entegrasyonu yapıldı.

### Design Decision
- **Why**: Şifreler düz text'te → security risk + Git exposure
- **How**: Vault KV v2 + hvac client + adapter_registry hook
- **When**: Load time (adapter registry'de credentials resolve)

### Scope
- Database credentials only (5 adapters × {user, password})
- No application secrets (yet)
- No dynamic credentials (yet)

### Dev vs Prod
- **Dev mode**: in-memory, auto-unseal, auto-generate token
- **Prod mode**: sealed, file/Raft backend, service account token, audit logs

### Note
Vault token hardcoded in code is anti-pattern. Use:
- Kubernetes auth
- AWS IAM auth
- Environment variable + .gitignore

---

## F6-02 Vault Integration (Oturum 11)

### Why Vault?
Production'da şifreler düz text → security risk + Git exposure.
Merkezi secrets yönetimi gerekli.

### What Changed
- Docker: Vault container (dev mode)
- Python: hvac client + adapter_registry entegrasyonu
- Config: databases.yaml vault:// referansları
- Deployment: VAULT_ADDR + VAULT_TOKEN env vars

### How It Works
1. adapter_registry.load_all() başladığında
2. Her DB config için _resolve_credentials() çağırılır
3. credentials: vault://db/name ise Vault'tan çeker
4. DB adapter şifreli credentials ile connect() yapır

### Dev vs Prod
- Dev: in-memory, auto-unseal, easy testing
- Prod: sealed mode, persistent backend, audit logs

### Next
F6-04 Prometheus alert rules devam et.

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
