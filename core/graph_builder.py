"""
BitTrace v2 - core/graph_builder.py

Builds a single shared directed multigraph of fund flow (address -> address,
edge weight = BTC moved, edge attrs = txid/time) that pattern_detector.py,
graph_analytics.py and report_generator.py all read from. Building it once
and sharing it avoids re-deriving the same structure three separate times.
"""

from typing import List
import networkx as nx


def build_flow_graph(txs: List[dict]) -> nx.MultiDiGraph:
    """
    txs: list of normalized tx dicts (data_fetcher.normalize_tx shape).

    For each tx we connect every input address to every output address
    (a reasonable simplification for a same-tx fan pattern - true UTXO-level
    tracing would need coin-selection info that isn't reliably knowable).
    """
    g = nx.MultiDiGraph()

    for tx in txs:
        inputs = [i for i in tx["inputs"] if i.get("address")]
        outputs = [o for o in tx["outputs"] if o.get("address")]

        for i in inputs:
            g.add_node(i["address"])
        for o in outputs:
            g.add_node(o["address"])

        total_in = sum(i["value_btc"] for i in inputs) or 1e-12
        for i in inputs:
            for o in outputs:
                if i["address"] == o["address"]:
                    continue
                # Attribute a share of this output proportional to the
                # input's share of total inflow (simple, transparent split).
                share = (i["value_btc"] / total_in) * o["value_btc"]
                g.add_edge(
                    i["address"], o["address"],
                    txid=tx["txid"],
                    value_btc=share,
                    block_time=tx.get("block_time"),
                    is_change=o.get("is_change", False),
                )

    return g


def graph_stats(g: nx.MultiDiGraph) -> dict:
    return {
        "nodes": g.number_of_nodes(),
        "edges": g.number_of_edges(),
        "is_dag": nx.is_directed_acyclic_graph(nx.DiGraph(g)),
    }


if __name__ == "__main__":
    sample_txs = [
        {
            "txid": "tx1",
            "inputs": [{"address": "A", "value_btc": 1.0}],
            "outputs": [{"address": "B", "value_btc": 0.9}, {"address": "C", "value_btc": 0.1}],
        },
        {
            "txid": "tx2",
            "inputs": [{"address": "B", "value_btc": 0.9}],
            "outputs": [{"address": "D", "value_btc": 0.89}],
        },
    ]
    g = build_flow_graph(sample_txs)
    print("Graph stats:", graph_stats(g))
    assert g.has_edge("A", "B")
    assert g.has_edge("B", "D")
    print("PASS: graph builder confirmed working.")
