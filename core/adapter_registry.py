"""
core/adapter_registry.py
========================
databases.yaml'dan adapter'ları dinamik olarak yükler.
Vault entegrasyonu: credentials'ta "vault://..." ise Vault'tan çeker.
"""

from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path
from typing import Iterator

import yaml

from core.base_adapter import DBAdapter, ConfigurationError

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = ("name", "adapter", "host", "db_name")

# Vault config
VAULT_ADDR = os.getenv("VAULT_ADDR", "http://localhost:8200")
VAULT_TOKEN = os.getenv("VAULT_TOKEN", "")

_vault_client = None


def _get_vault_client():
    """Lazy-load Vault client"""
    global _vault_client
    if _vault_client is None:
        try:
            import hvac
            _vault_client = hvac.Client(url=VAULT_ADDR, token=VAULT_TOKEN)
            if not VAULT_TOKEN:
                logger.warning("VAULT_TOKEN env var boş — Vault secret'ler çekilemez")
            else:
                logger.info("Vault client initialized: %s", VAULT_ADDR)
        except ImportError:
            logger.warning("hvac kütüphanesi yüklenemedi — Vault desteği deaktif")
            _vault_client = False
    return _vault_client if _vault_client else None


def _resolve_vault_secret(path: str) -> dict:
    """
    Vault secret çeker. 
    Örnek: "vault://db/mssql-prod" → {"user": "...", "password": "..."}
    """
    if not path.startswith("vault://"):
        return {}
    
    secret_path = path.replace("vault://", "")
    client = _get_vault_client()
    if not client:
        logger.error("Vault client unavailable, cannot fetch: %s", secret_path)
        return {}
    
    try:
        response = client.secrets.kv.v2.read_secret_version(path=secret_path)
        data = response["data"]["data"]
        logger.info("Vault secret çekildi: %s", secret_path)
        return data
    except Exception as e:
        logger.error("Vault secret çekme hatası [%s]: %s", secret_path, e)
        return {}


def _validate_db_config(cfg: dict) -> None:
    missing = [f for f in _REQUIRED_FIELDS if not cfg.get(f)]
    if missing:
        name = cfg.get("name", "<isimsiz>")
        raise ConfigurationError(
            f"DB config '{name}' eksik alanlar: {missing}",
            db_type=cfg.get("db_type", ""),
            host=cfg.get("host", ""),
        )


class AdapterRegistry:

    def __init__(self, config_path: str = "config/databases.yaml"):
        self._config_path = Path(config_path)
        self._adapters:  dict[str, DBAdapter] = {}
        self._configs:   dict[str, dict]      = {}
        self._loaded:    bool                 = False

    def load_all(self) -> "AdapterRegistry":
        if not self._config_path.exists():
            raise FileNotFoundError(f"databases.yaml bulunamadı: {self._config_path.resolve()}")

        with open(self._config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        databases = raw.get("databases", [])
        if not databases:
            logger.warning("databases.yaml'da hiç DB tanımı yok.")
            return self

        loaded_count = skipped_count = 0

        for db_conf in databases:
            name = db_conf.get("name", "<isimsiz>")
            if not db_conf.get("enabled", True):
                logger.info("Adapter atlandı (enabled=false): %s", name)
                skipped_count += 1
                continue
            try:
                # Credentials resolve et (Vault varsa)
                db_conf = self._resolve_credentials(db_conf)
                
                _validate_db_config(db_conf)
                adapter = self._load_adapter(db_conf)
                self._adapters[name] = adapter
                self._configs[name]  = db_conf
                loaded_count += 1
                logger.info("Adapter yüklendi: %s → %s", name, db_conf["adapter"])
            except ConfigurationError as exc:
                logger.error("Config hatası [%s]: %s", name, exc)
            except (ImportError, AttributeError) as exc:
                logger.error("Adapter import hatası [%s → %s]: %s", name, db_conf.get("adapter", "?"), exc)
            except Exception as exc:
                logger.exception("Beklenmedik hata [%s]: %s", name, exc)

        logger.info("AdapterRegistry hazır: %d yüklendi, %d atlandı.", loaded_count, skipped_count)
        self._loaded = True
        return self

    def reload(self) -> "AdapterRegistry":
        self._adapters.clear()
        self._configs.clear()
        self._loaded = False
        return self.load_all()

    def get(self, name: str) -> DBAdapter:
        self._ensure_loaded()
        if name not in self._adapters:
            raise KeyError(f"Adapter bulunamadı: '{name}'. Mevcut: {list(self._adapters.keys())}")
        return self._adapters[name]

    def get_config(self, name: str) -> dict:
        self._ensure_loaded()
        return self._configs[name]

    def all(self) -> list[DBAdapter]:
        self._ensure_loaded()
        return list(self._adapters.values())

    def names(self) -> list[str]:
        self._ensure_loaded()
        return list(self._adapters.keys())

    def by_db_type(self, db_type: str) -> list[DBAdapter]:
        self._ensure_loaded()
        return [
            a for name, a in self._adapters.items()
            if self._configs[name].get("db_type", "").lower() == db_type.lower()
        ]

    def items(self) -> Iterator[tuple[str, DBAdapter]]:
        self._ensure_loaded()
        return iter(self._adapters.items())

    def __len__(self) -> int:
        return len(self._adapters)

    def __contains__(self, name: str) -> bool:
        return name in self._adapters

    def __repr__(self) -> str:
        status = "yüklendi" if self._loaded else "yüklenmedi"
        return f"AdapterRegistry(config={self._config_path}, adapters={list(self._adapters.keys())}, status={status})"

    def _resolve_credentials(self, db_conf: dict) -> dict:
        """
        Credentials'ta vault:// varsa Vault'tan çeker.
        Yoksa olduğu gibi bırakır.
        """
        creds = db_conf.get("credentials", {})
        
        if isinstance(creds, str) and creds.startswith("vault://"):
            # Tüm credentials Vault'tan
            vault_creds = _resolve_vault_secret(creds)
            if vault_creds:
                db_conf["credentials"] = vault_creds
                logger.info("Credentials Vault'tan çekildi: %s", db_conf.get("name"))
        elif isinstance(creds, dict):
            # Individual field'lar vault:// olabilir
            for key, val in creds.items():
                if isinstance(val, str) and val.startswith("vault://"):
                    vault_data = _resolve_vault_secret(val)
                    if key in vault_data:
                        db_conf["credentials"][key] = vault_data[key]
                        logger.debug("Credential field çekildi: %s.%s", db_conf.get("name"), key)
        
        return db_conf

    def _load_adapter(self, db_conf: dict) -> DBAdapter:
        adapter_path = db_conf["adapter"]
        try:
            module_path, class_name = adapter_path.rsplit(".", 1)
        except ValueError:
            raise ConfigurationError(
                f"Geçersiz adapter yolu: '{adapter_path}'. Beklenen: 'adapters.modul.SinifAdi'",
                host=db_conf.get("host", ""),
            )
        module = importlib.import_module(module_path)
        adapter_class = getattr(module, class_name)
        if not issubclass(adapter_class, DBAdapter):
            raise ConfigurationError(f"'{class_name}' DBAdapter'dan türemiş değil.", host=db_conf.get("host", ""))
        return adapter_class(db_conf)

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            logger.warning("AdapterRegistry henüz yüklenmemişti — otomatik yükleniyor.")
            self.load_all()
