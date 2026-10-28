from core import entity_attribution, threat_intel, graph_builder


def test_dataset_match_hits_real_wannacry_address():
    index = threat_intel.build_lookup_index()
    hits = entity_attribution.attribute_by_dataset("13AM4VW2dhxYgXeQepoHkHSQuy6NgaEb94", index)
    assert any(h["entity_type"] == "ransomware" for h in hits)


def test_dataset_match_no_hit_for_unknown_address():
    index = threat_intel.build_lookup_index()
    hits = entity_attribution.attribute_by_dataset("1SOMERANDOMADDRESSNOTLISTED0000", index)
    assert hits == []


def test_exchange_heuristic_requires_outgoing_activity():
    # Only incoming - should NOT trigger the exchange heuristic
    txs = [{"txid": f"in_{i}", "inputs": [{"address": f"S{i}", "value_btc": 1.0}],
            "outputs": [{"address": "COLLECTOR", "value_btc": 0.99}]} for i in range(6)]
    g = graph_builder.build_flow_graph(txs)
    hits = entity_attribution.attribute_by_behavior("COLLECTOR", g)
    assert hits == []


def test_exchange_heuristic_fires_with_outgoing_activity():
    txs = [{"txid": f"in_{i}", "inputs": [{"address": f"S{i}", "value_btc": 1.0}],
            "outputs": [{"address": "HUB", "value_btc": 0.99}]} for i in range(6)]
    txs.append({"txid": "out_1", "inputs": [{"address": "HUB", "value_btc": 5.0}],
                "outputs": [{"address": "W1", "value_btc": 2.4}, {"address": "W2", "value_btc": 2.4}]})
    g = graph_builder.build_flow_graph(txs)
    hits = entity_attribution.attribute_by_behavior("HUB", g)
    assert any(h["entity_type"] == "exchange" for h in hits)
