
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
