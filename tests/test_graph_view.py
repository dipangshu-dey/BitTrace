from core import graph_builder
from core.graph_view import build_focus_view

ROOT = "ROOT"


def _txs():
    txs = []
    # 20 sources pay ROOT; each tx also pays a random co-recipient (noise)
    for i in range(20):
        txs.append({"txid": f"in{i}",
                    "inputs": [{"address": f"SRC{i}", "value_btc": 1.0 + i}],
                    "outputs": [{"address": ROOT, "value_btc": 0.9 + i},
                                {"address": f"NOISE{i}", "value_btc": 0.05}]})
    # ROOT pays two destinations
    txs.append({"txid": "out1", "inputs": [{"address": ROOT, "value_btc": 5.0}],
                "outputs": [{"address": "DST1", "value_btc": 3.0}, {"address": "DST2", "value_btc": 1.9}]})
    return txs


def test_focus_view_hides_indirect_noise_and_caps_sides():
    g = graph_builder.build_flow_graph(_txs())
    view = build_focus_view(g, ROOT, {}, depth=1, max_per_side=8)
    addrs = {n["address"] for n in view["nodes"]}
    assert ROOT in addrs
    assert not any(a.startswith("NOISE") for a in addrs)
    assert sum(1 for n in view["nodes"] if n["col"] < 0) == 8
    assert {"DST1", "DST2"} <= addrs
    assert view["hidden"] == view["total_nodes"] - len(view["nodes"])


def test_focus_view_prefers_high_risk_addresses():
    g = graph_builder.build_flow_graph(_txs())
    scores = {"SRC0": {"score": 80, "band": "high", "breakdown": []}}
    view = build_focus_view(g, ROOT, scores, depth=1, max_per_side=3)
    assert "SRC0" in {n["address"] for n in view["nodes"]}


def test_edges_only_connect_adjacent_columns():
    g = graph_builder.build_flow_graph(_txs())
    view = build_focus_view(g, ROOT, {}, depth=1, max_per_side=5)
    col = {n["address"]: n["col"] for n in view["nodes"]}
    assert all(col[v] - col[u] == 1 for u, v, _ in view["edges"])


def test_unknown_root_is_safe():
    g = graph_builder.build_flow_graph(_txs())
    assert build_focus_view(g, "NOPE", {})["nodes"] == []
