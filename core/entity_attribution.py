"""
BitTrace v2 - core/entity_attribution.py
Objective 4: attribute addresses to entity types using two independent
methods that get combined:

  1. Dataset match  - direct hit against threat_intel.py's known-bad lists.
  2. Behavioral heuristic - infer entity type from *shape* of activity even
     with no dataset hit, e.g. an address that both collects funds from
     many sources AND pays out to many counterparties looks like an
     exchange hot wallet, not a personal wallet.
"""

from pathlib import Path
from typing import List
import sys
import networkx as nx

sys.path.append(str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent))
import config
import threat_intel


def attribute_by_dataset(address: str, threat_index: dict = None) -> List[dict]:
    matches = threat_intel.lookup_address(address, threat_index)
    return [
        {
            "entity_type": _list_to_entity_type(m["list_name"]),
            "confidence": 0.95,
            "method": "dataset_match",
            "detail": f"{m['list_name']}: {m['entity_label']}",
        }
        for m in matches
    ]


def _list_to_entity_type(list_name: str) -> str:
    mapping = {
        "OFAC_SDN": "sanctioned",
        "WannaCry": "ransomware",
        "DarknetMarket": "darknet_market",
        "ransomwhere": "ransomware",
    }
    return mapping.get(list_name, "flagged")


def attribute_by_behavior(address: str, g: nx.MultiDiGraph) -> List[dict]:
    """
    Exchange heuristic: an exchange hot wallet both *receives* from many
    distinct counterparties (customers depositing) AND *sends* to many
    distinct counterparties (customers withdrawing / exchange paying out).
    An address that only ever receives (e.g. a pure collection/ransom
    address) does NOT get flagged as an exchange - it needs outgoing
    activity too, since collecting-then-paying-out is the defining
    behavioral signature of an exchange, not just collecting.
    """
    results = []
    if address not in g:
        return results

    in_degree = g.in_degree(address)
    out_degree = g.out_degree(address)
    distinct_senders = len({u for u, _ in g.in_edges(address)})
    distinct_recipients = len({v for _, v in g.out_edges(address)})

    if (out_degree >= config.EXCHANGE_MIN_OUTGOING_TX and
            distinct_senders >= config.EXCHANGE_MIN_DISTINCT_COUNTERPARTIES and
            distinct_recipients >= 1):
        confidence = min(0.9, 0.4 + 0.05 * min(distinct_senders, 10))
        results.append({
            "entity_type": "exchange",
            "confidence": round(confidence, 2),
            "method": "behavioral_heuristic",
            "detail": (f"{distinct_senders} distinct senders in, "
                       f"{distinct_recipients} distinct recipients out "
                       f"({in_degree} in-edges / {out_degree} out-edges total)"),
        })

    return results


def attribute_address(address: str, g: nx.MultiDiGraph, threat_index: dict = None) -> List[dict]:
    return attribute_by_dataset(address, threat_index) + attribute_by_behavior(address, g)


def attribute_all(addresses: List[str], g: nx.MultiDiGraph, threat_index: dict = None) -> dict:
    if threat_index is None:
        threat_index = threat_intel.build_lookup_index()
    return {addr: attribute_address(addr, g, threat_index) for addr in addresses}


if __name__ == "__main__":
    import graph_builder

    # Dataset-match test: use a real placeholder address from threat_intel
    threat_index = threat_intel.build_lookup_index()
    flagged_addr = "13AM4VW2dhxYgXeQepoHkHSQuy6NgaEb94"
    dataset_hits = attribute_by_dataset(flagged_addr, threat_index)
    assert dataset_hits and dataset_hits[0]["entity_type"] == "ransomware"
    print(f"Dataset-match test PASS: {flagged_addr[:12]}... -> {dataset_hits[0]}")

    # Behavioral test: HUB receives from many senders and pays out to
    # several recipients -> should trip the exchange heuristic. This
    # requires HUB to have *outgoing* edges too, not just incoming - the
    # first version of this test failed until the synthetic data below
    # was fixed to actually send funds out of HUB, matching the logic's
    # real requirement (collect AND pay out, not just collect).
    txs = []
    for i, src in enumerate(["S1", "S2", "S3", "S4", "S5", "S6"]):
        txs.append({"txid": f"in_{i}", "inputs": [{"address": src, "value_btc": 1.0}],
                     "outputs": [{"address": "HUB", "value_btc": 0.98}]})
    txs.append({"txid": "out_1", "inputs": [{"address": "HUB", "value_btc": 5.0}],
                 "outputs": [{"address": "W1", "value_btc": 2.4}, {"address": "W2", "value_btc": 2.4}]})

    g = graph_builder.build_flow_graph(txs)
    behavior_hits = attribute_by_behavior("HUB", g)
    assert behavior_hits and behavior_hits[0]["entity_type"] == "exchange", \
        "FAIL: HUB should trip the exchange heuristic (collects from 6, pays out to 2)"
    print(f"Behavioral test PASS: HUB -> {behavior_hits[0]}")

    print("PASS: Objective 4 confirmed working - both dataset-match and "
          "behavioral attribution fire correctly.")
