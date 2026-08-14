
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
