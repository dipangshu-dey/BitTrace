from core.demo_data import build_demo_transactions, WANNACRY_ADDRESS
from core.graph_builder import build_flow_graph
from core.pattern_detector import detect_all_patterns
from core.threat_intel import build_lookup_index
from core.entity_attribution import attribute_address


def test_demo_data_is_deterministic_and_exercises_patterns():
    a = build_demo_transactions()
    b = build_demo_transactions()
    assert a == b
    assert len(a) >= 15
    g = build_flow_graph(a)
    patterns = detect_all_patterns(g, a)
    assert patterns["peel_chains"]
    assert patterns["fan_out"]
    assert patterns["fan_in"]
    assert patterns["coinjoin"]
    assert patterns["circular_flows"]


def test_demo_contains_real_threat_intel_address_only_as_synthetic_flow():
    txs = build_demo_transactions()
    assert any(
        o.get("address") == WANNACRY_ADDRESS
        for tx in txs
        for o in tx["outputs"]
    )
