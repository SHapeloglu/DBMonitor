#!/usr/bin/env python3
"""Vault'a database credentials yükler"""

import hvac
import time
import sys

VAULT_ADDR = "http://localhost:8200"
VAULT_TOKEN = os.getenv("VAULT_TOKEN", "")

def wait_for_vault(max_retries=30):
    """Vault'un start olmasını bekle"""
    for i in range(max_retries):
        try:
            client = hvac.Client(url=VAULT_ADDR, token=VAULT_TOKEN)
            client.is_authenticated()
            print("✅ Vault bağlantısı sağlandı")
            return client
        except Exception as e:
            print(f"⏳ Vault bekleniyor ({i+1}/{max_retries})...")
            time.sleep(2)
    raise Exception("❌ Vault başlanamadı")

def setup_policy(client):
    """DB credentials policy oluştur"""
    policy = """
    path "secret/data/db/*" { 
        capabilities = ["read", "list"] 
    }
    """
    client.sys.create_or_update_policy("db-credentials", policy)
    print("✅ Policy oluşturuldu: db-credentials")

def setup_secrets(client):
    """Database credentials yükle"""
    secrets = {
        "mssql-prod": {
            "host": "10.0.0.5",
            "port": "1433",
            "user": "etl_svc",
            "password": "changeme"
        },
        "mysql-prod": {
            "host": "10.0.0.6",
            "port": "3306",
            "user": "etl_svc",
            "password": "changeme"
        },
        "mariadb-prod": {
            "host": "10.0.0.7",
            "port": "3306",
            "user": "etl_svc",
            "password": "changeme"
        },
        "oracle-prod": {
            "host": "10.0.0.8",
            "port": "1521",
            "user": "etl_svc",
            "password": "changeme"
        },
        "postgres-local": {
            "host": "postgres",
            "port": "5432",
            "user": "dquser",
            "password": "dqpass"
        }
    }
    
    for name, creds in secrets.items():
        client.secrets.kv.v2.create_or_update_secret(
            path=f"db/{name}",
            secret=creds
        )
        print(f"✅ Secret yüklendi: db/{name}")

if __name__ == "__main__":
    try:
        client = wait_for_vault()
        setup_policy(client)
        setup_secrets(client)
        print("\n🎉 Vault initialization tamamlandı!")
        print(f"VAULT_ADDR: {VAULT_ADDR}")
        print(f"VAULT_TOKEN: {VAULT_TOKEN}")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Hata: {e}", file=sys.stderr)
        sys.exit(1)
