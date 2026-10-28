from core import clustering


def test_common_input_ownership_merges_addresses():
    tx = {
        "txid": "tx1",
        "inputs": [
            {"vin_index": 0, "address": "A", "value_btc": 0.5, "script_type": "p2pkh"},
            {"vin_index": 1, "address": "B", "value_btc": 0.5, "script_type": "p2pkh"},
        ],
        "outputs": [
            {"vout_index": 0, "address": "C", "value_btc": 0.99, "script_type": "p2pkh"},
        ],
    }
    clusters = clustering.cluster_transactions([tx])
    groups = clustering.cluster_summary(clusters)
    a_group = next(g for g in groups if "A" in g["members"])
    assert "B" in a_group["members"]


def test_change_detection_pulls_change_into_cluster():
    tx = {
        "txid": "tx1",
        "inputs": [
            {"vin_index": 0, "address": "A", "value_btc": 0.7, "script_type": "p2pkh"},
            {"vin_index": 1, "address": "B", "value_btc": 0.3, "script_type": "p2pkh"},
        ],
        "outputs": [
            {"vout_index": 0, "address": "PAYEE", "value_btc": 0.5, "script_type": "p2pkh"},
            {"vout_index": 1, "address": "CHANGE", "value_btc": 0.49872311, "script_type": "p2pkh"},
        ],
    }
    clusters = clustering.cluster_transactions([tx])
    groups = clustering.cluster_summary(clusters)
    a_group = next(g for g in groups if "A" in g["members"])
    assert "CHANGE" in a_group["members"]
    assert "PAYEE" not in a_group["members"]


def test_round_amount_is_not_flagged_as_change():
    assert clustering._is_round_amount(0.5) is True
    assert clustering._is_round_amount(1.0) is True
    assert clustering._is_round_amount(0.49872311) is False


def test_union_find_basic():
    uf = clustering.UnionFind()
    uf.union("x", "y")
    uf.union("y", "z")
    assert uf.find("x") == uf.find("z")
