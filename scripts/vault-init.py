#!/usr/bin/env python3
"""
Vault'a database credentials yükler (Vault ilk kurulum betiği).
Ne yapar: 1) Gerekli şifre ortam değişkenlerini kontrol eder, 2) Vault hazır olana kadar bekler,
3) 'db-credentials' policy'sini oluşturur, 4) db/<ad> yollarına DB kullanıcı bilgilerini yazar.
Ne zaman: Vault konteyneri ayağa kalktıktan sonra elle, bir kez çalıştırılır.
DİKKAT: Şifreler koda yazılmaz; her biri ortam değişkeninden okunur (bkz. REQUIRED_PASSWORD_ENVS).
Eksik bir ortam değişkeni varsa betik hiçbir şey yazmadan hata verip çıkar.
VAULT_TOKEN ortam değişkeni çalıştırmadan önce ayarlanmalıdır.
"""

import hvac
import os
import time
import sys

# Vault adresi. Yerel çalıştırma içindir; 8200, Vault'un varsayılan portudur.
VAULT_ADDR = "http://localhost:8200"
VAULT_TOKEN = os.getenv("VAULT_TOKEN", "")

# Her DB'nin şifresi için okunacak ortam değişkeni. Varsayılan değer yoktur.
REQUIRED_PASSWORD_ENVS = {
    "mssql-prod": "DB_MSSQL_PROD_PASS",
    "mysql-prod": "DB_MYSQL_PROD_PASS",
    "mariadb-prod": "DB_MARIADB_PROD_PASS",
    "oracle-prod": "DB_ORACLE_PROD_PASS",
    "postgres-local": "DB_POSTGRES_LOCAL_PASS",
}

def load_passwords():
    """Tüm şifre ortam değişkenlerini okur. Eksik veya boş olanları tek bir hatada listeler."""
    passwords = {}
    missing = []
    for name, env_name in REQUIRED_PASSWORD_ENVS.items():
        value = os.getenv(env_name, "")
        if value:
            passwords[name] = value
        else:
            missing.append(env_name)
    if missing:
        raise RuntimeError(
            "Eksik ortam değişkenleri (Vault'a hiçbir şey yazılmadı): " + ", ".join(missing)
        )
    return passwords

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
    # Vault policy (HCL biçiminde): db/ altındaki gizlilere sadece okuma ve listeleme yetkisi verir. Yazma yetkisi verilmez.
    policy = """
    path "secret/data/db/*" {
        capabilities = ["read", "list"]
    }
    """
    client.sys.create_or_update_policy("db-credentials", policy)
    print("✅ Policy oluşturuldu: db-credentials")

def setup_secrets(client, passwords):
    """Database credentials yükle"""
    # Host/port/kullanıcı bilgileri sabit; şifreler ortam değişkenlerinden gelir.
    secrets = {
        "mssql-prod": {
            "host": "10.0.0.5",
            "port": "1433",
            "user": "etl_svc",
            "password": passwords["mssql-prod"]
        },
        "mysql-prod": {
            "host": "10.0.0.6",
            "port": "3306",
            "user": "etl_svc",
            "password": passwords["mysql-prod"]
        },
        "mariadb-prod": {
            "host": "10.0.0.7",
            "port": "3306",
            "user": "etl_svc",
            "password": passwords["mariadb-prod"]
        },
        "oracle-prod": {
            "host": "10.0.0.8",
            "port": "1521",
            "user": "etl_svc",
            "password": passwords["oracle-prod"]
        },
        "postgres-local": {
            "host": "postgres",
            "port": "5432",
            "user": "apache",
            "password": passwords["postgres-local"]
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
        # Şifreler Vault'a hiçbir şey yazılmadan önce kontrol edilir.
        passwords = load_passwords()
        client = wait_for_vault()
        setup_policy(client)
        setup_secrets(client, passwords)
        print("\n🎉 Vault initialization tamamlandı!")
        print(f"VAULT_ADDR: {VAULT_ADDR}")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Hata: {e}", file=sys.stderr)
        sys.exit(1)
