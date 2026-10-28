import sqlite3
import tempfile
from pathlib import Path

import pytest

from db import database


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    database.init_db(db_path=db_path)
    return db_path


def test_init_db_creates_tables(temp_db):
    conn = sqlite3.connect(temp_db)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    expected = {"investigations", "addresses", "transactions", "tx_inputs",
                "tx_outputs", "clusters", "cluster_addresses", "patterns",
                "threat_matches", "entity_attributions", "risk_scores"}
    assert expected.issubset(tables)


def test_create_and_get_investigation(temp_db, monkeypatch):
    import config
    monkeypatch.setattr(config, "DB_PATH", temp_db)
    inv_id = database.create_investigation("1TESTADDRESS", 3, notes="unit test")
    row = database.get_investigation(inv_id)
    assert row is not None
    assert row["root_address"] == "1TESTADDRESS"
    assert row["notes"] == "unit test"


def test_upsert_and_get_address(temp_db, monkeypatch):
    import config
    monkeypatch.setattr(config, "DB_PATH", temp_db)
    database.upsert_address("1ADDR", total_received=1.5, tx_count=2)
    row = database.get_address("1ADDR")
    assert row is not None
    assert row["address"] == "1ADDR"
    assert row["total_received"] == 1.5


def test_cluster_roundtrip(temp_db, monkeypatch):
    import config
    monkeypatch.setattr(config, "DB_PATH", temp_db)
    inv_id = database.create_investigation("1ROOT", 3, notes="test")
    cluster_id = database.create_cluster(inv_id, label="cl1")
    database.add_address_to_cluster(cluster_id, "1A", reason="common-input")
    database.add_address_to_cluster(cluster_id, "1B", reason="change")
    members = database.get_cluster_addresses(cluster_id)
    assert {m["address"] for m in members} == {"1A", "1B"}


def test_risk_score_roundtrip(temp_db, monkeypatch):
    import config
    monkeypatch.setattr(config, "DB_PATH", temp_db)
    inv_id = database.create_investigation("1ROOT", 3, notes="test")
    database.save_risk_score(inv_id, "1A", 80.0, "high", {"breakdown": []})
    scores = database.get_risk_scores_for_investigation(inv_id)
    assert len(scores) == 1
    assert scores[0]["address"] == "1A"
    assert scores[0]["band"] == "high"


def test_delete_investigation_removes_scoped_rows_but_keeps_shared_transactions(temp_db, monkeypatch):
    import config
    monkeypatch.setattr(config, "DB_PATH", temp_db)
    inv_id = database.create_investigation("1ROOT", 1)
    database.upsert_transaction("tx1", 1, 123, None, {"txid": "tx1"})
    database.create_cluster(inv_id, label="cluster")
    database.save_pattern(inv_id, "fan_out", ["1ROOT"], {"count": 1})
    database.save_risk_score(inv_id, "1ROOT", 60, "high", {"breakdown": []})

    assert database.delete_investigation(inv_id) is True
    assert database.get_investigation(inv_id) is None
    assert database.get_transaction("tx1") is not None
    assert database.get_clusters_for_investigation(inv_id) == []
    assert database.get_patterns_for_investigation(inv_id) == []
    assert database.get_risk_scores_for_investigation(inv_id) == []
