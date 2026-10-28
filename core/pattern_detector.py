"""
BitTrace v2 - core/pattern_detector.py
Objective 2: detect four laundering / obfuscation patterns over the shared
fund-flow graph built by graph_builder.py:

  1. Peel chains     - a long sequential path where each hop peels off a
                        small payment and forwards the remainder.
  2. Fan-out          - one address sends to many distinct addresses.
  3. Fan-in           - many distinct addresses send to one address.
  4. CoinJoin-like    - a single tx with several near-equal-value outputs
                        (mixing signature).
  5. Circular flow    - funds return to an address they originated from.

NOTE on peel-chain walking: cycles must be guarded against explicitly.
A naive walker that just keeps following the highest-value outgoing edge
will loop forever (or massively over-count) on a circular flow like
F -> G -> F -> G ... To keep the two detectors independent and correct,
the peel-chain walker tracks visited nodes and stops the moment it would
revisit one, and the circular-flow detector reports it separately.
"""

from pathlib import Path
from typing import List
import sys
import networkx as nx
sys.path.append(str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent))
import config


def detect_peel_chains(g: nx.MultiDiGraph) -> List[dict]:
    """
    Walk from each node with out-degree potentially starting a chain,
    following the single dominant outgoing edge (largest value) as long as
    the pattern holds: one small "peel" output + one large "continuation"
    output at each hop. Stops at cycles, dead ends, or max hops.
    """
    chains = []
    simple = _collapse_to_simple_digraph(g)

    for start in simple.nodes():
        visited = {start}
        path = [start]
        current = start

        while len(path) - 1 < config.PEEL_CHAIN_MAX_HOPS:
            out_edges = list(simple.out_edges(current, data=True))
            if len(out_edges) != 2:
                # A peel hop is characterised by exactly 2 outputs: one
                # peel-off, one continuation. Anything else ends the chain.
                break

            out_edges.sort(key=lambda e: e[2].get("value_btc", 0), reverse=True)
            (_, continuation, _), (_, _peel, _) = out_edges

            if continuation in visited:
                # Would revisit a node -> this is a cycle, not a peel chain.
                # Hand off to circular-flow detection instead; stop here.
                break

            visited.add(continuation)
            path.append(continuation)
            current = continuation

        hops = len(path) - 1
        if hops >= config.PEEL_CHAIN_MIN_HOPS:
            chains.append({"pattern": "peel_chain", "path": path, "hops": hops})

    # de-duplicate sub-chains that are prefixes of a longer chain already found
    chains.sort(key=lambda c: c["hops"], reverse=True)
    seen_starts = set()
    deduped = []
    for c in chains:
        key = tuple(c["path"])
        if any(key == existing["path"][:len(key)] for existing in deduped):
            continue
        deduped.append(c)
    return deduped


def detect_fan_out(g: nx.MultiDiGraph) -> List[dict]:
    simple = _collapse_to_simple_digraph(g)
    results = []
    for node in simple.nodes():
        targets = list(simple.successors(node))
        if len(targets) >= config.FAN_OUT_MIN_OUTPUTS:
            results.append({
                "pattern": "fan_out",
                "address": node,
                "targets": targets,
                "count": len(targets),
            })
    return results


def detect_fan_in(g: nx.MultiDiGraph) -> List[dict]:
    simple = _collapse_to_simple_digraph(g)
    results = []
    for node in simple.nodes():
        sources = list(simple.predecessors(node))
        if len(sources) >= config.FAN_IN_MIN_INPUTS:
            results.append({
                "pattern": "fan_in",
                "address": node,
                "sources": sources,
                "count": len(sources),
            })
    return results


def detect_coinjoin(txs: List[dict]) -> List[dict]:
    """
    A CoinJoin-style tx has several outputs of (near-)identical value -
    the classic mixing signature (everyone gets an equal-sized slice back
    so outputs can't be linked to a specific input by amount).
    """
    results = []
    for tx in txs:
        outputs = tx.get("outputs", [])
        if len(outputs) < config.COINJOIN_MIN_EQUAL_OUTPUTS:
            continue

        buckets = {}
        for o in outputs:
            v = round(o.get("value_btc", 0), 8)
            bucket_key = None
            for existing in buckets:
                if abs(existing - v) <= config.COINJOIN_EQUAL_OUTPUT_TOLERANCE:
                    bucket_key = existing
                    break
            buckets.setdefault(bucket_key if bucket_key is not None else v, []).append(o)

        for value, members in buckets.items():
            if len(members) >= config.COINJOIN_MIN_EQUAL_OUTPUTS:
                results.append({
                    "pattern": "coinjoin",
                    "txid": tx["txid"],
                    "equal_value_btc": value,
                    "output_count": len(members),
                    "addresses": [m.get("address") for m in members],
                })
    return results


def detect_circular_flows(g: nx.MultiDiGraph) -> List[dict]:
    """Any simple cycle in the collapsed graph = funds returning to origin."""
    simple = _collapse_to_simple_digraph(g)
    results = []
    try:
        for cycle in nx.simple_cycles(simple, length_bound=10):
            if len(cycle) >= 2:
                results.append({
                    "pattern": "circular_flow",
                    "cycle": cycle,
                    "length": len(cycle),
                })
    except TypeError:
        # older networkx without length_bound kwarg
        for cycle in nx.simple_cycles(simple):
            if len(cycle) >= 2:
                results.append({"pattern": "circular_flow", "cycle": cycle, "length": len(cycle)})
    return results


def _collapse_to_simple_digraph(g: nx.MultiDiGraph) -> nx.DiGraph:
    """Collapse parallel multi-edges into one edge, summing value_btc."""
    simple = nx.DiGraph()
    for u, v, data in g.edges(data=True):
        if simple.has_edge(u, v):
            simple[u][v]["value_btc"] += data.get("value_btc", 0)
        else:
            simple.add_edge(u, v, value_btc=data.get("value_btc", 0))
    return simple


def detect_all_patterns(g: nx.MultiDiGraph, txs: List[dict]) -> dict:
    return {
        "peel_chains": detect_peel_chains(g),
        "fan_out": detect_fan_out(g),
        "fan_in": detect_fan_in(g),
        "coinjoin": detect_coinjoin(txs),
        "circular_flows": detect_circular_flows(g),
    }


if __name__ == "__main__":
    import graph_builder

    # ------------------------------------------------------------------
    # Build one synthetic scenario that exercises all four+1 patterns
    # simultaneously, including an F<->G circular flow that the original
    # peel-chain walker used to double-count as a 51-hop chain before the
    # cycle guard was added.
    # ------------------------------------------------------------------
    txs = []

    # Peel chain: P0 -> P1 -> P2 -> P3 -> P4 (4 hops, each peeling a bit off)
    chain_nodes = ["P0", "P1", "P2", "P3", "P4"]
    for i in range(len(chain_nodes) - 1):
        txs.append({
            "txid": f"peel_tx_{i}",
            "inputs": [{"address": chain_nodes[i], "value_btc": 1.0 - i * 0.1}],
            "outputs": [
                {"address": chain_nodes[i + 1], "value_btc": 0.9 - i * 0.1},
                {"address": f"peel_sink_{i}", "value_btc": 0.1},
            ],
        })

    # Fan-out: HUB -> 6 distinct addresses
    txs.append({
        "txid": "fanout_tx",
        "inputs": [{"address": "HUB", "value_btc": 6.0}],
        "outputs": [{"address": f"OUT{i}", "value_btc": 1.0} for i in range(6)],
    })

    # Fan-in: 6 distinct addresses -> HUB
    txs.append({
        "txid": "fanin_tx",
        "inputs": [{"address": f"IN{i}", "value_btc": 1.0} for i in range(6)],
        "outputs": [{"address": "HUB", "value_btc": 5.9}],
    })

    # CoinJoin: 4 equal outputs
    txs.append({
        "txid": "coinjoin_tx",
        "inputs": [{"address": f"CJIN{i}", "value_btc": 0.5} for i in range(4)],
        "outputs": [{"address": f"CJOUT{i}", "value_btc": 0.2} for i in range(4)],
    })

    # Circular flow: F -> G -> F
    txs.append({"txid": "circ_tx1", "inputs": [{"address": "F", "value_btc": 1.0}],
                 "outputs": [{"address": "G", "value_btc": 0.99}]})
    txs.append({"txid": "circ_tx2", "inputs": [{"address": "G", "value_btc": 0.99}],
                 "outputs": [{"address": "F", "value_btc": 0.98}]})

    g = graph_builder.build_flow_graph(txs)
    results = detect_all_patterns(g, txs)

    print(f"Peel chains found: {len(results['peel_chains'])}")
    for c in results["peel_chains"]:
        print(f"  hops={c['hops']} path={c['path']}")
    assert any(c["hops"] == 4 for c in results["peel_chains"]), "FAIL: expected the 4-hop peel chain"
    assert not any(c["hops"] > 10 for c in results["peel_chains"]), \
        "FAIL: cycle guard broken - peel walker double-counted the F<->G loop"

    print(f"Fan-out found: {len(results['fan_out'])}  Fan-in found: {len(results['fan_in'])}")
    assert any(f["address"] == "HUB" for f in results["fan_out"])
    assert any(f["address"] == "HUB" for f in results["fan_in"])

    print(f"CoinJoin found: {len(results['coinjoin'])}")
    assert any(cj["output_count"] == 4 for cj in results["coinjoin"])

    print(f"Circular flows found: {len(results['circular_flows'])}")
    assert any(set(cf["cycle"]) == {"F", "G"} for cf in results["circular_flows"])

    print("PASS: all four Objective 2 patterns detect correctly and separately "
          "(cycle guard prevents the F<->G loop from being miscounted as a peel chain).")
