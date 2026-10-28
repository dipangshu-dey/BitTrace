"""Deterministic synthetic investigation data for the BitTrace demo.

The transactions in this module are intentionally fictional. They exercise the
same four project objectives and pattern detectors as a real investigation,
without pretending that the synthetic txids or flows occurred on Bitcoin.
"""

from typing import List

# This is a real, publicly documented WannaCry address already shipped in the
# project's threat-intel dataset. Its appearance below is inside fictional
# transactions solely so the attribution objective can be demonstrated.
WANNACRY_ADDRESS = "13AM4VW2dhxYgXeQepoHkHSQuy6NgaEb94"


def build_demo_transactions(root_address: str = "DEMO_ROOT") -> List[dict]:
    txs = []

    # 1) Common-input ownership + change-address detection.
    txs.append({
        "txid": "demo_cluster_001",
        "inputs": [
            {"vin_index": 0, "address": root_address, "value_btc": 2.0, "script_type": "p2pkh"},
            {"vin_index": 1, "address": "DEMO_SECOND_INPUT", "value_btc": 1.0, "script_type": "p2pkh"},
        ],
        "outputs": [
            {"vout_index": 0, "address": "DEMO_PAYMENT_01", "value_btc": 0.50, "script_type": "p2pkh"},
            {"vout_index": 1, "address": "DEMO_CHANGE_01", "value_btc": 2.49873111, "script_type": "p2pkh"},
        ],
    })

    # 2) Three-hop peel chain.
    peel = ["DEMO_PEEL_0", "DEMO_PEEL_1", "DEMO_PEEL_2", "DEMO_PEEL_3"]
    amounts = [1.80, 1.55, 1.30, 1.05]
    for i in range(3):
        txs.append({
            "txid": f"demo_peel_{i+1:03d}",
            "inputs": [{"vin_index": 0, "address": peel[i], "value_btc": amounts[i], "script_type": "p2pkh"}],
            "outputs": [
                {"vout_index": 0, "address": peel[i + 1], "value_btc": amounts[i] - 0.20, "script_type": "p2pkh"},
                {"vout_index": 1, "address": f"DEMO_PEEL_PAYMENT_{i+1}", "value_btc": 0.20, "script_type": "p2pkh"},
            ],
        })

    # 3) Fan-out hub.
    fanout_targets = [f"DEMO_FANOUT_{i}" for i in range(1, 7)]
    txs.append({
        "txid": "demo_fanout_001",
        "inputs": [{"vin_index": 0, "address": "DEMO_FANOUT_HUB", "value_btc": 3.0, "script_type": "p2pkh"}],
        "outputs": [
            {"vout_index": i, "address": addr, "value_btc": 0.45, "script_type": "p2pkh"}
            for i, addr in enumerate(fanout_targets)
        ],
    })

    # 4) Fan-in hub.
    fanin_sources = [f"DEMO_FANIN_{i}" for i in range(1, 7)]
    txs.append({
        "txid": "demo_fanin_001",
        "inputs": [
            {"vin_index": i, "address": addr, "value_btc": 0.50, "script_type": "p2pkh"}
            for i, addr in enumerate(fanin_sources)
        ],
        "outputs": [
            {"vout_index": 0, "address": "DEMO_FANIN_HUB", "value_btc": 2.95, "script_type": "p2pkh"}
        ],
    })

    # 5) CoinJoin-style equal outputs: synthetic pattern, not a real CoinJoin.
    txs.append({
        "txid": "demo_coinjoin_001",
        "inputs": [
            {"vin_index": 0, "address": "DEMO_CJ_IN_1", "value_btc": 1.1, "script_type": "p2wpkh"},
            {"vin_index": 1, "address": "DEMO_CJ_IN_2", "value_btc": 1.1, "script_type": "p2wpkh"},
            {"vin_index": 2, "address": "DEMO_CJ_IN_3", "value_btc": 1.1, "script_type": "p2wpkh"},
        ],
        "outputs": [
            {"vout_index": i, "address": f"DEMO_CJ_OUT_{i+1}", "value_btc": 1.0, "script_type": "p2wpkh"}
            for i in range(3)
        ],
    })

    # 6) Circular flow.
    txs.extend([
        {"txid": "demo_cycle_001", "inputs": [{"vin_index": 0, "address": "DEMO_CYCLE_A", "value_btc": 0.8}],
         "outputs": [{"vout_index": 0, "address": "DEMO_CYCLE_B", "value_btc": 0.79}]},
        {"txid": "demo_cycle_002", "inputs": [{"vin_index": 0, "address": "DEMO_CYCLE_B", "value_btc": 0.79}],
         "outputs": [{"vout_index": 0, "address": "DEMO_CYCLE_C", "value_btc": 0.78}]},
        {"txid": "demo_cycle_003", "inputs": [{"vin_index": 0, "address": "DEMO_CYCLE_C", "value_btc": 0.78}],
         "outputs": [{"vout_index": 0, "address": "DEMO_CYCLE_A", "value_btc": 0.77}]},
    ])

    # 7) Synthetic flow to a known threat-intel address. The tx is fictional;
    # the address is real and is used only to demonstrate dataset attribution.
    txs.append({
        "txid": "demo_threat_001",
        "inputs": [{"vin_index": 0, "address": "DEMO_THREAT_SOURCE", "value_btc": 0.60, "script_type": "p2pkh"}],
        "outputs": [{"vout_index": 0, "address": WANNACRY_ADDRESS, "value_btc": 0.59, "script_type": "p2pkh"}],
    })

    # 8) Exchange-like behaviour: many deposits and a payout transaction.
    exchange_sources = [f"DEMO_EXCHANGE_IN_{i}" for i in range(1, 7)]
    for i, src in enumerate(exchange_sources, 1):
        txs.append({
            "txid": f"demo_exchange_in_{i:03d}",
            "inputs": [{"vin_index": 0, "address": src, "value_btc": 0.4, "script_type": "p2pkh"}],
            "outputs": [{"vout_index": 0, "address": "DEMO_EXCHANGE_HUB", "value_btc": 0.39, "script_type": "p2pkh"}],
        })
    txs.append({
        "txid": "demo_exchange_out_001",
        "inputs": [{"vin_index": 0, "address": "DEMO_EXCHANGE_HUB", "value_btc": 2.30, "script_type": "p2pkh"}],
        "outputs": [
            {"vout_index": 0, "address": "DEMO_EXCHANGE_OUT_1", "value_btc": 1.10, "script_type": "p2pkh"},
            {"vout_index": 1, "address": "DEMO_EXCHANGE_OUT_2", "value_btc": 1.10, "script_type": "p2pkh"},
        ],
    })

    return txs
