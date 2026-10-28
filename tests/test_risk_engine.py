from core import risk_engine
import config


def test_clean_address_scores_low():
    result = risk_engine.score_address("1CLEAN", entity_attributions=[], patterns_involved=[], betweenness=0.0)
    assert result["score"] == 0
    assert result["band"] == "low"


def test_sanctioned_match_scores_high():
    result = risk_engine.score_address(
        "1DIRTY",
        entity_attributions=[{"entity_type": "sanctioned", "method": "dataset_match"}],
        patterns_involved=["peel_chain"],
        betweenness=0.2,
    )
    assert result["score"] >= config.RISK_BAND_HIGH
    assert result["band"] == "high"
    signals = {b["signal"] for b in result["breakdown"]}
    assert "sanctioned_match" in signals
    assert "peel_chain" in signals
    assert "high_betweenness" in signals


def test_score_never_exceeds_max():
    result = risk_engine.score_address(
        "1MAXED",
        entity_attributions=[
            {"entity_type": "sanctioned", "method": "dataset_match"},
            {"entity_type": "ransomware", "method": "dataset_match"},
            {"entity_type": "darknet_market", "method": "dataset_match"},
        ],
        patterns_involved=["peel_chain", "coinjoin", "fan_out", "fan_in", "circular_flow"],
        betweenness=0.9,
    )
    assert result["score"] <= config.RISK_SCORE_MAX


def test_score_never_negative():
    result = risk_engine.score_address(
        "1EXCHANGE",
        entity_attributions=[{"entity_type": "exchange", "method": "behavioral_heuristic"}],
        patterns_involved=[],
        betweenness=0.0,
    )
    assert result["score"] >= 0


def test_breakdown_is_explainable():
    result = risk_engine.score_address(
        "1X",
        entity_attributions=[{"entity_type": "ransomware", "method": "dataset_match"}],
        patterns_involved=[],
        betweenness=0.0,
    )
    assert "reason" in result["breakdown"][0]
    assert result["breakdown"][0]["points"] == config.RISK_WEIGHTS["ransomware_match"]
    # breakdown always adds up to the final score
    assert sum(b["points"] for b in result["breakdown"]) == result["score"]


def test_confirmed_threat_is_always_high():
    result = risk_engine.score_address(
        "1WANNA",
        entity_attributions=[{"entity_type": "ransomware", "method": "dataset_match"}],
        patterns_involved=[],
        betweenness=0.0,
    )
    assert result["score"] >= config.RISK_DATASET_MATCH_FLOOR
    assert result["band"] == "high"
    assert "confirmed_threat_floor" in {b["signal"] for b in result["breakdown"]}


def test_exchange_discount_never_offsets_confirmed_threat():
    result = risk_engine.score_address(
        "1WANNA",
        entity_attributions=[
            {"entity_type": "ransomware", "method": "dataset_match"},
            {"entity_type": "exchange", "method": "behavioral_heuristic"},
        ],
        patterns_involved=["fan_in"],
        betweenness=0.0,
    )
    assert "exchange_heuristic" not in {b["signal"] for b in result["breakdown"]}
    assert result["band"] == "high"
