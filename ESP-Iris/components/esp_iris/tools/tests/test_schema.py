from __future__ import annotations

import sqlite3

import pytest

from iris_gateway.schema import SCHEMA_VERSION
from iris_gateway.store import GatewayStore


def test_fresh_store_initializes_02_schema_and_reopens(tmp_path):
    store = GatewayStore(tmp_path)
    assert store.schema_version == SCHEMA_VERSION
    store.set_setting("sentinel", "retained")
    store.close()
    store = GatewayStore(tmp_path)
    assert store.get_setting("sentinel") == "retained"
    store.close()


@pytest.mark.parametrize("version", [0, 1, 4, 7, 201])
def test_foreign_state_is_rejected_without_modification(tmp_path, version):
    path = tmp_path / "gateway.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE old_evidence (value TEXT)")
    db.execute("INSERT INTO old_evidence VALUES ('original')")
    db.execute(f"PRAGMA user_version={version}")
    db.commit()
    db.close()
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="fresh state directory"):
        GatewayStore(tmp_path)
    assert path.read_bytes() == before
