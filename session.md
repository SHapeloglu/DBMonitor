# DWH İzleme Sistemi — Oturum Özeti

## Oturum 11 — F6-02 Vault Setup (2026-08-14)

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
