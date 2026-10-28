from core import graph_builder, pattern_detector


def _peel_chain_txs(n_hops=4):
    nodes = [f"P{i}" for i in range(n_hops + 1)]
    txs = []
    for i in range(n_hops):
        txs.append({
            "txid": f"peel_{i}",
            "inputs": [{"address": nodes[i], "value_btc": 1.0 - i * 0.1}],
            "outputs": [
                {"address": nodes[i + 1], "value_btc": 0.9 - i * 0.1},
                {"address": f"sink_{i}", "value_btc": 0.1},
            ],
        })
    return txs, nodes


def test_peel_chain_detected():
    txs, nodes = _peel_chain_txs(4)
    g = graph_builder.build_flow_graph(txs)
    chains = pattern_detector.detect_peel_chains(g)
    assert any(c["hops"] == 4 and c["path"] == nodes for c in chains)


def test_peel_chain_stops_at_cycle_not_double_counted():
    txs = [
        {"txid": "c1", "inputs": [{"address": "F", "value_btc": 1.0}],
         "outputs": [{"address": "G", "value_btc": 0.99}]},
        {"txid": "c2", "inputs": [{"address": "G", "value_btc": 0.99}],
         "outputs": [{"address": "F", "value_btc": 0.98}]},
    ]
    g = graph_builder.build_flow_graph(txs)
    chains = pattern_detector.detect_peel_chains(g)
    # F->G->F is a cycle; the walker must not treat it as a long peel chain
    assert all(c["hops"] < 10 for c in chains)


def test_fan_out_detected():
    txs = [{"txid": "fo", "inputs": [{"address": "HUB", "value_btc": 6.0}],
            "outputs": [{"address": f"OUT{i}", "value_btc": 1.0} for i in range(6)]}]
    g = graph_builder.build_flow_graph(txs)
    results = pattern_detector.detect_fan_out(g)
    assert any(r["address"] == "HUB" and r["count"] == 6 for r in results)


def test_fan_in_detected():
    txs = [{"txid": "fi", "inputs": [{"address": f"IN{i}", "value_btc": 1.0} for i in range(6)],
            "outputs": [{"address": "HUB", "value_btc": 5.9}]}]
    g = graph_builder.build_flow_graph(txs)
    results = pattern_detector.detect_fan_in(g)
    assert any(r["address"] == "HUB" and r["count"] == 6 for r in results)


def test_coinjoin_detected():
    txs = [{"txid": "cj", "inputs": [{"address": f"IN{i}", "value_btc": 0.5} for i in range(4)],
            "outputs": [{"address": f"OUT{i}", "value_btc": 0.2} for i in range(4)]}]
    results = pattern_detector.detect_coinjoin(txs)
    assert any(r["output_count"] == 4 for r in results)


def test_coinjoin_below_threshold_not_flagged():
    txs = [{"txid": "small", "inputs": [{"address": "A", "value_btc": 0.5}],
            "outputs": [{"address": "B", "value_btc": 0.2}, {"address": "C", "value_btc": 0.2}]}]
    results = pattern_detector.detect_coinjoin(txs)
    assert results == []


def test_circular_flow_detected():
    txs = [
        {"txid": "c1", "inputs": [{"address": "F", "value_btc": 1.0}],
         "outputs": [{"address": "G", "value_btc": 0.99}]},
        {"txid": "c2", "inputs": [{"address": "G", "value_btc": 0.99}],
         "outputs": [{"address": "F", "value_btc": 0.98}]},
    ]
    g = graph_builder.build_flow_graph(txs)
    results = pattern_detector.detect_circular_flows(g)
    assert any(set(r["cycle"]) == {"F", "G"} for r in results)
