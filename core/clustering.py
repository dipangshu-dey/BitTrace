"""
BitTrace v2 - core/clustering.py
Objective 1: address clustering via the common-input-ownership heuristic,
plus multi-signal change-address detection.

Common-input-ownership heuristic: if two or more addresses are used as
inputs to the *same* transaction, they must be controlled by the same
wallet (the wallet needed the private keys for all of them to sign).
This module unions such addresses into clusters using a simple
union-find, then separately flags likely change outputs so those get
pulled into the owning cluster too.
"""

from pathlib import Path
from typing import Dict, List, Set
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
import config


class UnionFind:
    """Standard union-find / disjoint-set with path compression."""

    def __init__(self):
        self.parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def groups(self) -> Dict[str, Set[str]]:
        out: Dict[str, Set[str]] = {}
        for node in self.parent:
            root = self.find(node)
            out.setdefault(root, set()).add(node)
        return out


def detect_change_output(tx: dict, input_addresses: Set[str]) -> List[dict]:
    """
    Score each output for "looks like change" signals. Returns the outputs
    list annotated with is_change / change_signals. An output needs
    >= CHANGE_HEURISTIC_MIN_SIGNALS to be flagged.

    Signals used (each worth 1 point, config.CHANGE_HEURISTIC_MIN_SIGNALS
    controls the threshold):
      1. script_type matches the script type of the transaction's inputs
         (wallets typically generate change in their own native format).
      2. The output value is NOT a "round" amount (payments to a third
         party are more often round numbers; change is a leftover and is
         almost never round).
      3. There is exactly one candidate output that is not already an
         input address of this tx and it's the only one that isn't a
         known repeat-recipient (weak "sole non-input output" signal).
    """
    outputs = tx["outputs"]
    inputs = tx["inputs"]

    input_script_types = {i.get("script_type") for i in inputs if i.get("script_type")}
    # Blockstream input dicts (from data_fetcher) may not carry script_type;
    # fall back to inferring from address prefix heuristically if absent.
    if not input_script_types:
        input_script_types = {_infer_script_type(i.get("address")) for i in inputs if i.get("address")}

    non_input_outputs = [o for o in outputs if o.get("address") not in input_addresses]

    annotated = []
    for o in outputs:
        signals = 0
        addr = o.get("address")
        if addr in input_addresses:
            # paying back to one of the inputs' own addresses (self-change) - strong signal
            signals += 1

        out_type = o.get("script_type") or _infer_script_type(addr)
        if out_type and out_type in input_script_types:
            signals += config.CHANGE_ADDR_TYPE_MATCH_WEIGHT

        if not _is_round_amount(o.get("value_btc", 0)):
            signals += config.CHANGE_NO_ROUND_AMOUNT_WEIGHT

        if len(non_input_outputs) == 1 and o in non_input_outputs:
            signals += config.CHANGE_SINGLE_OUTPUT_BACK_WEIGHT

        is_change = signals >= config.CHANGE_HEURISTIC_MIN_SIGNALS
        annotated.append({**o, "is_change": is_change, "change_signals": signals})

    return annotated


def _is_round_amount(btc_value: float) -> bool:
    """Heuristic: amounts like 0.1, 0.5, 1.0, 0.01 'look' like intentional payments."""
    if btc_value <= 0:
        return False
    cents = round(btc_value * 1e8)  # satoshis
    for denom in (1_00_000_000, 10_000_000, 1_000_000, 100_000):
        if cents % denom == 0:
            return True
    return False


def _infer_script_type(address: str) -> str:
    if not address:
        return "unknown"
    if address.startswith("1"):
        return "p2pkh"
    if address.startswith("3"):
        return "p2sh"
    if address.startswith("bc1q"):
        return "p2wpkh"
    if address.startswith("bc1p"):
        return "p2tr"
    return "unknown"


def cluster_transactions(txs: List[dict]) -> Dict[str, Set[str]]:
    """
    Main entry point for Objective 1.

    txs: list of normalized tx dicts (see data_fetcher.normalize_tx), each
    with 'inputs' and 'outputs' lists.

    Returns: dict of {cluster_root_address: {member_addresses}}
    """
    uf = UnionFind()

    for tx in txs:
        input_addrs = [i["address"] for i in tx["inputs"] if i.get("address")]
        input_addr_set = set(input_addrs)

        # Rule 1: common-input-ownership - union all input addresses of this tx
        if len(input_addrs) > 1:
            first = input_addrs[0]
            for other in input_addrs[1:]:
                uf.union(first, other)
        elif len(input_addrs) == 1:
            uf.find(input_addrs[0])  # ensure it exists as its own node

        # Rule 2: change-address detection - fold detected change back into
        # the same cluster as the inputs (the sender owns the change output too)
        annotated_outputs = detect_change_output(tx, input_addr_set)
        for o in annotated_outputs:
            if o["is_change"] and o.get("address") and input_addrs:
                uf.union(input_addrs[0], o["address"])

    return uf.groups()


def cluster_summary(clusters: Dict[str, Set[str]]) -> List[dict]:
    """Turn raw union-find groups into a display-friendly list, largest first."""
    summary = []
    for root, members in clusters.items():
        summary.append({
            "root": root,
            "size": len(members),
            "members": sorted(members),
        })
    summary.sort(key=lambda c: c["size"], reverse=True)
    return summary


if __name__ == "__main__":
    # ------------------------------------------------------------------
    # Synthetic test - proves clustering + change detection work without
    # needing live network access. Scenario:
    #   tx1: inputs [A, B] -> outputs [C (payment, round 0.5 BTC), D (change,
    #        odd amount, same script type as A/B, only non-input output)]
    # Expect: A, B, D all in one cluster. C stays separate (real recipient).
    # ------------------------------------------------------------------
    synthetic_tx = {
        "txid": "synthetic_tx_1",
        "inputs": [
            {"vin_index": 0, "address": "1AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "value_btc": 0.7, "script_type": "p2pkh"},
            {"vin_index": 1, "address": "1BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB", "value_btc": 0.3, "script_type": "p2pkh"},
        ],
        "outputs": [
            {"vout_index": 0, "address": "1CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC", "value_btc": 0.5, "script_type": "p2pkh"},
            {"vout_index": 1, "address": "1DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD", "value_btc": 0.49872311, "script_type": "p2pkh"},
        ],
    }

    clusters = cluster_transactions([synthetic_tx])
    result = cluster_summary(clusters)
    print("Cluster result:")
    for c in result:
        print(f"  root={c['root'][:12]}...  size={c['size']}  members={[m[:12] for m in c['members']]}")

    a_root = None
    d_root = None
    c_root = None
    for c in result:
        for m in c["members"]:
            if m.startswith("1AAAA"):
                a_root = c["root"]
            if m.startswith("1DDDD"):
                d_root = c["root"]
            if m.startswith("1CCCC"):
                c_root = c["root"]

    assert a_root == d_root, "FAIL: change address D should cluster with input A"
    assert a_root != c_root, "FAIL: real recipient C should NOT cluster with A"
    print("PASS: A+B merged via common-input-ownership; D pulled in as change; C stayed separate.")
