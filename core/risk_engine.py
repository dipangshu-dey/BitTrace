"""
BitTrace v2 - core/risk_engine.py
Objective 3: explainable 0-100 risk scoring that combines the outputs of
Objectives 1, 2 and 4 into a single, human-readable score per address.

Explainability is the point: every score comes with an itemised list of
exactly which signals fired and how many points each contributed, so an
investigator (or a viva examiner) can see *why* an address scored the way
it did, not just the final number.
"""

from pathlib import Path
from typing import List
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
import config


def score_address(address: str, *, threat_matches: list = None, entity_attributions: list = None,
                   patterns_involved: list = None, betweenness: float = 0.0) -> dict:
    """
    threat_matches:        list of dataset-match dicts from entity_attribution
    entity_attributions:   full attribute_address() output for this address
    patterns_involved:     list of pattern_type strings this address appears in
                            (e.g. ['peel_chain', 'coinjoin'])
    betweenness:           this address's betweenness centrality (0-1)
    """
    threat_matches = threat_matches or []
    entity_attributions = entity_attributions or []
    patterns_involved = patterns_involved or []

    breakdown = []
    score = 0

    # --- dataset-confirmed threats (highest weight) ---
    entity_types_hit = {a["entity_type"] for a in entity_attributions if a.get("method") == "dataset_match"}
    if "sanctioned" in entity_types_hit:
        pts = config.RISK_WEIGHTS["sanctioned_match"]
        score += pts
        breakdown.append({"signal": "sanctioned_match", "points": pts,
                           "reason": "Address matches a sanctions (OFAC-style) list."})
    if "ransomware" in entity_types_hit:
        pts = config.RISK_WEIGHTS["ransomware_match"]
        score += pts
        breakdown.append({"signal": "ransomware_match", "points": pts,
                           "reason": "Address matches a known ransomware payout list."})
    if "darknet_market" in entity_types_hit:
        pts = config.RISK_WEIGHTS["darknet_match"]
        score += pts
        breakdown.append({"signal": "darknet_match", "points": pts,
                           "reason": "Address matches a known darknet market list."})

    # --- behavioral pattern involvement ---
    pattern_weight_map = {
        "peel_chain": "peel_chain",
        "coinjoin": "coinjoin",
        "fan_out": "fan_out",
        "fan_in": "fan_in",
        "circular_flow": "circular_flow",
    }
    for pattern in set(patterns_involved):
        weight_key = pattern_weight_map.get(pattern)
        if weight_key:
            pts = config.RISK_WEIGHTS[weight_key]
            score += pts
            breakdown.append({"signal": weight_key, "points": pts,
                               "reason": f"Address is involved in a detected {pattern.replace('_', ' ')}."})

    # --- graph centrality ---
    if betweenness and betweenness > 0.1:
        pts = config.RISK_WEIGHTS["high_betweenness"]
        score += pts
        breakdown.append({"signal": "high_betweenness", "points": pts,
                           "reason": f"High betweenness centrality ({betweenness:.3f}) - "
                                     f"address is a pass-through hub for many flows."})

    confirmed_threat = bool(entity_types_hit & {"sanctioned", "ransomware", "darknet_market"})

    # --- discount for legitimate-looking exchange behavior ---
    # Never applied to an address that is on a confirmed threat list: looking
    # like an exchange must not offset a documented sanctions/ransomware hit.
    if not confirmed_threat and any(
            a["entity_type"] == "exchange" and a.get("method") == "behavioral_heuristic"
            for a in entity_attributions):
        pts = config.RISK_WEIGHTS["exchange_heuristic"]
        score += pts
        breakdown.append({"signal": "exchange_heuristic", "points": pts,
                           "reason": "Behavior matches an exchange hot wallet "
                                     "(collects from many, pays out to many) - slight risk discount."})

    # --- floor for confirmed threats ---
    # A documented match is not a "maybe": lift the score to the floor and
    # record the lift as its own line so the breakdown still sums to the score.
    if confirmed_threat and score < config.RISK_DATASET_MATCH_FLOOR:
        lift = config.RISK_DATASET_MATCH_FLOOR - score
        score += lift
        breakdown.append({"signal": "confirmed_threat_floor", "points": lift,
                           "reason": f"Address is on a confirmed threat list; score raised to the "
                                     f"minimum of {config.RISK_DATASET_MATCH_FLOOR}."})

    score = max(0, min(config.RISK_SCORE_MAX, score))

    if score >= config.RISK_BAND_HIGH:
        band = "high"
    elif score >= config.RISK_BAND_MEDIUM:
        band = "medium"
    else:
        band = "low"

    return {
        "address": address,
        "score": score,
        "band": band,
        "breakdown": breakdown,
    }


def score_all(addresses: List[str], *, threat_index: dict, entity_map: dict,
              pattern_membership: dict, analytics: dict) -> dict:
    """
    Convenience batch scorer.
      entity_map:          {address: attribute_address() output}
      pattern_membership:  {address: [pattern_type, ...]}
      analytics:            full_analytics() output from graph_analytics
    """
    return {
        addr: score_address(
            addr,
            threat_matches=[a for a in entity_map.get(addr, []) if a.get("method") == "dataset_match"],
            entity_attributions=entity_map.get(addr, []),
            patterns_involved=pattern_membership.get(addr, []),
            betweenness=analytics.get(addr, {}).get("betweenness", 0.0),
        )
        for addr in addresses
    }


if __name__ == "__main__":
    # A dirty address: ransomware dataset hit + peel chain + coinjoin + high betweenness
    dirty = score_address(
        "1DIRTY0000000000000000000000000",
        entity_attributions=[{"entity_type": "ransomware", "method": "dataset_match"}],
        patterns_involved=["peel_chain", "coinjoin"],
        betweenness=0.35,
    )
    print("Dirty address score:", dirty["score"], dirty["band"])
    for b in dirty["breakdown"]:
        print(f"  +{b['points']:>3}  {b['signal']:<20} {b['reason']}")
    assert dirty["band"] == "high"

    # A clean-looking exchange address: only the exchange discount applies
    clean = score_address(
        "1CLEAN0000000000000000000000000",
        entity_attributions=[{"entity_type": "exchange", "method": "behavioral_heuristic"}],
        patterns_involved=[],
        betweenness=0.02,
    )
    print("Clean/exchange address score:", clean["score"], clean["band"])
    assert clean["band"] == "low"

    print("PASS: risk engine produces explainable, correctly-banded scores.")
