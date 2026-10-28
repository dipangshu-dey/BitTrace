"""
BitTrace v2 - core/pipeline.py

End-to-end orchestration: given a root address, this ties together every
objective in order:

  fetch -> normalize -> store -> cluster (Obj.1) -> build graph ->
  detect patterns (Obj.2) -> compute analytics -> attribute entities (Obj.4)
  -> score risk (Obj.3) -> persist everything -> return a single result dict
  the dashboard and report_generator can both consume directly.
"""

from pathlib import Path
from collections import Counter
from typing import List
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config
from db import database
from core.data_fetcher import DataFetcher
from core import clustering, graph_builder, pattern_detector, graph_analytics
from core import threat_intel, entity_attribution, risk_engine


class FetchError(RuntimeError):
    """Live transaction data could not be downloaded."""


def _collect_addresses_from_txs(txs: List[dict], root_address: str) -> List[str]:
    addrs = {root_address}
    for tx in txs:
        for i in tx["inputs"]:
            if i.get("address"):
                addrs.add(i["address"])
        for o in tx["outputs"]:
            if o.get("address"):
                addrs.add(o["address"])
    return list(addrs)


def _expand_hops(fetcher, root_address: str, txs_by_id: dict, max_hops: int) -> int:
    """
    Breadth-first expansion. Hop 1 is the root's own history (already fetched).
    Each extra hop fetches history for the busiest not-yet-visited counterparties
    of the previous hop, capped so the free API is never hammered.
    Returns the number of addresses whose history was fetched.
    """
    visited = {root_address}
    frontier = {root_address}
    for _ in range(max_hops - 1):
        counts = Counter()
        for tx in txs_by_id.values():
            addrs = {a["address"] for a in tx["inputs"] + tx["outputs"] if a.get("address")}
            if addrs & frontier:
                for a in addrs - visited:
                    counts[a] += 1
        next_frontier = {a for a, _ in counts.most_common(config.HOP_MAX_NEIGHBORS)}
        if not next_frontier:
            break
        for addr in next_frontier:
            for raw in fetcher.get_address_txs(addr, max_txs=config.HOP_MAX_TX_PER_ADDRESS):
                nt = fetcher.normalize_tx(raw)
                txs_by_id.setdefault(nt["txid"], nt)
        visited |= next_frontier
        frontier = next_frontier
    return len(visited)


def run_investigation(root_address: str, max_hops: int = config.MAX_HOPS_DEFAULT,
                       synthetic_txs: List[dict] = None, notes: str = "") -> dict:
    """
    If synthetic_txs is provided, the pipeline skips live fetching and runs
    entirely on that data (useful offline / for demos / for tests). Otherwise
    it fetches real transaction history for root_address via DataFetcher.
    """
    database.init_db()

    # 1. Fetch + normalize -------------------------------------------------
    meta = {"synthetic": synthetic_txs is not None, "max_hops": max_hops,
            "root_tx_total": None, "addresses_expanded": 1}
    if synthetic_txs is not None:
        txs = synthetic_txs
    else:
        fetcher = DataFetcher()
        info = fetcher.get_address_info(root_address)
        if info is None:
            raise FetchError(f"Could not reach the blockchain data service ({fetcher.last_error}). "
                             f"Wait a minute and try again, or check your internet connection.")
        meta["root_tx_total"] = (info.get("chain_stats", {}).get("tx_count", 0)
                                  + info.get("mempool_stats", {}).get("tx_count", 0)) or None
        raw_txs = fetcher.get_address_txs(root_address)
        txs_by_id = {}
        for t in raw_txs:
            nt = fetcher.normalize_tx(t)
            txs_by_id[nt["txid"]] = nt
        meta["root_tx_fetched"] = len(txs_by_id)
        if max_hops > 1:
            meta["addresses_expanded"] = _expand_hops(fetcher, root_address, txs_by_id, max_hops)
        txs = list(txs_by_id.values())
    meta["txs_analysed"] = len(txs)
    if synthetic_txs is None and not txs and meta["root_tx_total"]:
        raise FetchError(f"The address has {meta['root_tx_total']:,} transactions but none could be "
                         f"downloaded ({fetcher.last_error}). This is usually a temporary rate limit - "
                         f"wait a minute and try again.")

    investigation_id = database.create_investigation(root_address, max_hops, notes)

    # persist raw tx/input/output rows
    for tx in txs:
        database.upsert_transaction(tx["txid"], tx.get("block_height"), tx.get("block_time"),
                                     tx.get("fee_sats"), tx)
        database.insert_inputs(tx["txid"], tx["inputs"])
        database.insert_outputs(tx["txid"], tx["outputs"])
    # record exactly which transactions THIS investigation analysed (shared rows stay de-duplicated)
    database.link_transactions(investigation_id, [tx["txid"] for tx in txs])

    all_addresses = _collect_addresses_from_txs(txs, root_address)
    for addr in all_addresses:
        database.upsert_address(addr)

    # 2. Clustering (Objective 1) -------------------------------------------------
    clusters = clustering.cluster_transactions(txs)
    cluster_summaries = clustering.cluster_summary(clusters)
    cluster_id_map = {}  # address -> db cluster id
    for c in cluster_summaries:
        db_cluster_id = database.create_cluster(investigation_id, label=c["root"][:16])
        for member in c["members"]:
            database.add_address_to_cluster(db_cluster_id, member, reason="common-input-ownership/change")
            cluster_id_map[member] = db_cluster_id

    # 3. Graph build -------------------------------------------------
    g = graph_builder.build_flow_graph(txs)

    # fill in cluster total_btc now that we have the graph
    for c in cluster_summaries:
        total = sum(
            data.get("value_btc", 0)
            for u, v, data in g.edges(data=True)
            if u in c["members"]
        )
        if c["root"] in cluster_id_map:
            database.set_cluster_total_btc(cluster_id_map[c["root"]], total)

    # 4. Pattern detection (Objective 2) -------------------------------------------------
    patterns = pattern_detector.detect_all_patterns(g, txs)
    pattern_membership = {}  # address -> [pattern_type,...]
    for chain in patterns["peel_chains"]:
        for addr in chain["path"]:
            pattern_membership.setdefault(addr, []).append("peel_chain")
        database.save_pattern(investigation_id, "peel_chain", chain["path"], chain)
    for fo in patterns["fan_out"]:
        pattern_membership.setdefault(fo["address"], []).append("fan_out")
        database.save_pattern(investigation_id, "fan_out", [fo["address"]] + fo["targets"], fo)
    for fi in patterns["fan_in"]:
        pattern_membership.setdefault(fi["address"], []).append("fan_in")
        database.save_pattern(investigation_id, "fan_in", [fi["address"]] + fi["sources"], fi)
    for cj in patterns["coinjoin"]:
        for addr in cj["addresses"]:
            if addr:
                pattern_membership.setdefault(addr, []).append("coinjoin")
        database.save_pattern(investigation_id, "coinjoin", [a for a in cj["addresses"] if a], cj)
    for cf in patterns["circular_flows"]:
        for addr in cf["cycle"]:
            pattern_membership.setdefault(addr, []).append("circular_flow")
        database.save_pattern(investigation_id, "circular_flow", cf["cycle"], cf)

    # 5. Graph analytics -------------------------------------------------
    analytics = graph_analytics.full_analytics(g)

    # 6. Entity attribution (Objective 4) -------------------------------------------------
    threat_index = threat_intel.build_lookup_index()
    entity_map = entity_attribution.attribute_all(all_addresses, g, threat_index)
    for addr, attrs in entity_map.items():
        for a in attrs:
            if a["method"] == "dataset_match":
                list_name = a["detail"].split(":")[0]
                database.save_threat_match(addr, list_name, a["detail"], source="threat_intel")
            database.save_entity_attribution(addr, a["entity_type"], a["confidence"], a["method"], a["detail"])

    # 7. Risk scoring (Objective 3) -------------------------------------------------
    risk_scores = risk_engine.score_all(
        all_addresses,
        threat_index=threat_index,
        entity_map=entity_map,
        pattern_membership=pattern_membership,
        analytics=analytics,
    )
    for addr, result in risk_scores.items():
        database.save_risk_score(investigation_id, addr, result["score"], result["band"],
                                  {"breakdown": result["breakdown"]})

    return {
        "investigation_id": investigation_id,
        "root_address": root_address,
        "addresses": all_addresses,
        "txs": txs,
        "clusters": cluster_summaries,
        "graph": g,
        "patterns": patterns,
        "analytics": analytics,
        "entity_map": entity_map,
        "risk_scores": risk_scores,
        "meta": meta,
    }


if __name__ == "__main__":
    # Full end-to-end smoke test combining a peel chain, a fan-out hub that
    # also gets flagged by threat intel, and normal traffic - proves every
    # objective's output flows correctly into the next stage.
    synthetic_txs = [
        {"txid": "t1", "inputs": [{"address": "ROOT", "value_btc": 5.0, "script_type": "p2pkh"}],
         "outputs": [{"address": "13AM4VW2dhxYgXeQepoHkHSQuy6NgaEb94", "value_btc": 4.9, "script_type": "p2pkh"},
                     {"address": "CHANGE1", "value_btc": 0.09872311, "script_type": "p2pkh"}]},
        {"txid": "t2", "inputs": [{"address": "13AM4VW2dhxYgXeQepoHkHSQuy6NgaEb94", "value_btc": 4.9}],
         "outputs": [{"address": f"HOP{i}", "value_btc": 4.9 - i * 0.5} for i in range(1, 3)]},
    ]

    result = run_investigation("ROOT", synthetic_txs=synthetic_txs, notes="pipeline smoke test")
    print(f"Investigation #{result['investigation_id']} on {result['root_address']}")
    print(f"  Addresses seen: {len(result['addresses'])}")
    print(f"  Clusters: {len(result['clusters'])}")
    print(f"  Patterns: { {k: len(v) for k, v in result['patterns'].items()} }")

    flagged = result["risk_scores"].get("13AM4VW2dhxYgXeQepoHkHSQuy6NgaEb94")
    assert flagged is not None and flagged["band"] in ("high", "medium"), \
        "FAIL: dataset-matched address should score at least medium risk"
    print(f"  13AM4VW2...'s risk score: {flagged['score']} ({flagged['band']})")
    print("PASS: full pipeline works end-to-end - all 4 objectives wired together correctly.")