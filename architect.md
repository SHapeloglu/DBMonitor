
---

## 10. Secrets Management — Vault Integration (F6-02)

### Vault Architecture

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
- Mode: dev (in-memory, auto-unseal)
- KV v2 mount: secret/

### Implementation
- Lazy-load: _vault_client singleton
- Fallback: Vault unavailable → credentials unchanged
- Both formats supported:
  - credentials: vault://db/name (entire dict)
  - credentials: {password: vault://db/name} (individual field)

### Production Considerations
- Dev mode data evaporates on restart
- Use sealed mode + persistent backend (file/Raft/S3)
- Service account token + audit logging

---

## 10. Secrets Management — Vault Integration

### Architecture
Vault KV v2 secrets → adapter_registry → db credentials

### Components
- Vault container (port 8200, dev mode)
- hvac client (Python)
- Policy: db-credentials (path "secret/data/db/*")
- Secrets: 5 DB credentials (mssql, mysql, mariadb, oracle, postgres)

### Implementation
adapter_registry.py:
- _get_vault_client(): Lazy-load hvac.Client
- _resolve_vault_secret(path): Vault'tan secret çek
- _resolve_credentials(db_conf): credentials'ta vault:// varsa resolve et

### Usage
databases.yaml:
credentials: vault://db/postgres-local
Load time'da adapter_registry şifreleri Vault'tan çeker.

### Production Notes
- Dev mode: in-memory, restart'ta kaybolur
- Use sealed mode + file/Raft/S3 backend for production
- Service account token + audit logging required
