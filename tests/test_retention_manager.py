"""RetentionManager birim testleri (veritabanı gerektirmez).

Gerçek PostgreSQL yerine sahte bir bağlantı kullanılır: her execute çağrısında
rowcount, sıradaki değer olarak döner. Bu sayede batch döngüsünün bitmesi,
commit sayısı ve dry-run davranışı CI'da doğrulanır.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.retention_manager import RetentionManager


class FakeCursor:
    def __init__(self, conn: "FakeConn"):
        self._conn = conn
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._conn.executed.append(sql)
        if self._conn.rowcounts:
            self.rowcount = self._conn.rowcounts.pop(0)
        else:
            self.rowcount = 0

    def fetchone(self):
        return (self._conn.dry_run_count,)


class FakeConn:
    def __init__(self, rowcounts=None, dry_run_count=0):
        self.rowcounts = list(rowcounts or [])
        self.dry_run_count = dry_run_count
        self.executed: list[str] = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, *args, **kwargs):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


CUTOFF = datetime(2024, 1, 1, tzinfo=timezone.utc)


def make_manager(batch_size=10, dry_run=False) -> RetentionManager:
    rm = RetentionManager(config_path="does-not-exist.yaml")
    rm.batch_size = batch_size
    rm.dry_run = dry_run
    rm.archive_backend = "unknown"  # export adımını atla
    return rm


def test_loop_moves_all_batches_until_short_batch():
    conn = FakeConn(rowcounts=[10, 10, 3])
    total = make_manager(batch_size=10)._archive_old_rows(conn, CUTOFF)

    assert total == 23
    assert len(conn.executed) == 3
    assert conn.commits == 3


def test_each_batch_is_single_delete_insert_statement():
    conn = FakeConn(rowcounts=[2])
    make_manager(batch_size=10)._archive_old_rows(conn, CUTOFF)

    sql = conn.executed[0]
    assert "WITH moved AS" in sql
    assert "DELETE FROM monitor.dwh_health_log" in sql
    assert "INSERT INTO monitor.dwh_health_log_archive" in sql


def test_empty_first_batch_returns_zero():
    conn = FakeConn(rowcounts=[0])
    assert make_manager(batch_size=10)._archive_old_rows(conn, CUTOFF) == 0
    assert len(conn.executed) == 1


def test_run_reports_deleted_equal_to_archived():
    conn = FakeConn(rowcounts=[10, 4])
    result = make_manager(batch_size=10).run(conn=conn)

    assert result["archived"] == 14
    assert result["deleted"] == result["archived"]
    assert conn.rollbacks == 0


def test_dry_run_counts_without_delete_and_rolls_back():
    conn = FakeConn(dry_run_count=42)
    result = make_manager(batch_size=10, dry_run=True).run(conn=conn)

    assert result["archived"] == 42
    assert result["deleted"] == 0
    assert not any("DELETE" in sql for sql in conn.executed)
    assert conn.rollbacks >= 1


def test_batch_size_zero_is_rejected_at_load(tmp_path):
    cfg = tmp_path / "retention.yaml"
    cfg.write_text("batch_size: 0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="batch_size"):
        RetentionManager(config_path=str(cfg))
