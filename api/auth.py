"""
api/auth.py
===========
İsteğe bağlı API anahtarı doğrulaması (F3-07).

- Ortam değişkeni API_KEY tanımlı ve boş değilse: /health hariç tüm endpoint'ler
  X-API-Key başlığı ister. Eşleşmezse 401 döner.
- API_KEY tanımsız veya boşsa kimlik doğrulama KAPALIDIR (geriye dönük davranış).
  Bu durumda lifespan başlangıcında uyarı loglanır.
- Anahtar hiçbir zaman loglanmaz ve yanıtta geri yansıtılmaz.
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Optional

from fastapi import Header, HTTPException, Request

logger = logging.getLogger(__name__)

API_KEY_ENV    = "API_KEY"
API_KEY_HEADER = "X-API-Key"


def _expected_key() -> str:
    # Her istekte okunur: anahtar değişince yeniden başlatma gerekmez.
    return os.getenv(API_KEY_ENV, "")


def auth_enabled() -> bool:
    return bool(_expected_key())


def log_auth_mode() -> None:
    """Başlangıçta kimlik doğrulama modunu loglar. Anahtar değeri loglanmaz."""
    if auth_enabled():
        logger.info("API kimlik doğrulaması AKTİF (%s başlığı gerekli).", API_KEY_HEADER)
    else:
        logger.warning(
            "API_KEY tanımlı değil — API kimlik doğrulaması KAPALI. "
            "Üretimde API_KEY ortam değişkenini tanımlayın."
        )


def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias=API_KEY_HEADER),
) -> None:
    expected = _expected_key()
    if not expected:
        return  # Kimlik doğrulama kapalı

    if x_api_key is None or not secrets.compare_digest(
        x_api_key.encode("utf-8"), expected.encode("utf-8")
    ):
        logger.warning("API anahtarı reddedildi: %s %s", request.method, request.url.path)
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "ApiKey"})
