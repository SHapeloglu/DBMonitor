"""
core/config_env.py
==================
YAML konfigürasyonundaki ${NAME} ve ${NAME:?mesaj} referanslarını ortam
değişkenlerinden çözer. Parolalar bu sayede YAML dosyalarında düz metin
olarak tutulmaz.

Kurallar:
- Referans içermeyen değerler olduğu gibi döner (davranış değişmez).
- Tanımsız veya boş bir ortam değişkeni ValueError fırlatır. Hata mesajı
  yalnızca değişken adını içerir, değerini asla yazdırmaz.
"""

from __future__ import annotations

import os
import re
from typing import Any, Mapping

_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::\?([^}]*))?\}")


def _expand_str(value: str, env: Mapping[str, str]) -> str:
    def _sub(match: re.Match) -> str:
        name, hint = match.group(1), match.group(2)
        resolved = env.get(name)
        if not resolved:
            msg = f"ortam değişkeni tanımlı değil: {name}"
            if hint:
                msg += f" ({hint})"
            raise ValueError(msg)
        return resolved

    return _REF.sub(_sub, value)


def expand_env(data: Any, env: Mapping[str, str] | None = None) -> Any:
    """dict/list/str yapısındaki ${NAME} referanslarını genişletir.

    env verilmezse os.environ kullanılır. Sayı, bool ve None gibi diğer
    değerler değiştirilmeden döner.
    """
    source = os.environ if env is None else env

    if isinstance(data, str):
        return _expand_str(data, source) if "${" in data else data
    if isinstance(data, dict):
        return {k: expand_env(v, source) for k, v in data.items()}
    if isinstance(data, list):
        return [expand_env(v, source) for v in data]
    return data
