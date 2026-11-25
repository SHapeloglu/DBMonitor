"""
api/logs.py
===========
GET /logs için filtreli okuma: monitor.dwh_health_log tablosunu parametreli
SQL ile sorgular.

Güvenlik notları:
- WHERE koşulları yalnızca FILTER_CLAUSES sözlüğündeki sabit SQL parçalarından
  kurulur; kullanıcı girdisi asla SQL metnine eklenmez, her zaman %s parametresidir.
- Bağlantı salt okunur açılır.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

import psycopg2.extras
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# API'nin döndürdüğü kolonlar (id bilinçli olarak dahil değil).
RESULT_COLUMNS: tuple[str, ...] = (
    "kontrol_tarihi", "db_type", "host", "db_name", "kategori",
    "kontrol_kodu", "kontrol_adi", "sonuc", "severity",
    "etkilenen_obje", "etkilenen_sayi", "detay",
)

# Whitelist: filtre adı -> sabit SQL koşulu. Değerler her zaman parametre olarak geçer.
FILTER_CLAUSES: dict[str, str] = {
    "db_name":      "db_name = %s",
    "kontrol_kodu": "kontrol_kodu = %s",
    "sonuc":        "sonuc = %s",
    "severity":     "severity = %s",
    "since":        "kontrol_tarihi >= %s",
    "until":        "kontrol_tarihi <= %s",
}


class LogItem(BaseModel):
    kontrol_tarihi: datetime
    db_type:        str
    host:           str
    db_name:        str
    kategori:       str
    kontrol_kodu:   str
    kontrol_adi:    str
    sonuc:          str
    severity:       int
    etkilenen_obje: Optional[str] = None
    etkilenen_sayi: Optional[int] = None
    detay:          Optional[str] = None


class LogPage(BaseModel):
    items:  list[LogItem]
    limit:  int
    offset: int
    count:  int


def to_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Zaman damgasız değerleri UTC kabul eder."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def build_logs_query(
    filters: dict[str, object],
    limit: int,
    offset: int,
) -> tuple[str, list]:
    """Filtrelerden (sql, params) üretir. None değerli filtreler atlanır."""
    clauses: list[str] = []
    params:  list     = []
    for key, value in filters.items():
        if value is None:
            continue
        if key not in FILTER_CLAUSES:
            raise ValueError(f"Bilinmeyen filtre: {key}")
        clauses.append(FILTER_CLAUSES[key])
        params.append(value)

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = (
        f"SELECT {', '.join(RESULT_COLUMNS)} "
        f"FROM monitor.dwh_health_log"
        f"{where} "
        f"ORDER BY kontrol_tarihi DESC LIMIT %s OFFSET %s"
    )
    params.extend([limit, offset])
    return sql, params


def fetch_logs(
    open_connection: Callable[[], object],
    filters: dict[str, object],
    limit: int,
    offset: int,
) -> list[dict]:
    """
    Sorguyu çalıştırır. Bağlantı hataları (psycopg2.Error) çağırana iletilir;
    çağıran bunları 503'e çevirir.
    """
    sql, params = build_logs_query(filters, limit, offset)
    conn = open_connection()
    try:
        conn.set_session(readonly=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
