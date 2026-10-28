"""
BitTrace v2 - core/data_fetcher.py

Thin wrapper around the Blockstream Esplora REST API. Deliberately has no
API key requirement (Blockstream's public API is free). Fails gracefully -
if the sandbox/environment has no internet access, every function returns
None or [] rather than raising, so the rest of the pipeline can still be
exercised with synthetic data.
"""

import time
from pathlib import Path
from typing import Optional
import sys

import requests

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config


class DataFetcher:
    def __init__(self, base_url: str = config.BLOCKSTREAM_API_BASE, fallbacks=None):
        self.base_urls = [base_url.rstrip("/")] + [
            u.rstrip("/") for u in (config.API_FALLBACK_BASES if fallbacks is None else fallbacks)]
        self.base_url = self.base_urls[0]
        self.session = requests.Session()
        self.last_error = None
        self._errors = {}

    # -- internal ----------------------------------------------------------
    def _get(self, path: str) -> Optional[dict or list]:
        """GET with retries; honours HTTP 429 (rate limit); falls back to a mirror."""
        self._errors = {}
        for base in self.base_urls:
            url = f"{base}{path}"
            for attempt in range(1, config.API_MAX_RETRIES + 1):
                try:
                    resp = self.session.get(url, timeout=config.API_TIMEOUT_SECONDS)
                    if resp.status_code == 200:
                        self.last_error = None
                        return resp.json()
                    self._note(base, f"HTTP {resp.status_code}")
                    if resp.status_code in (400, 404):      # bad address / not found: retrying won't help
                        break
                    if resp.status_code == 429:
                        try:
                            wait = min(float(resp.headers.get("Retry-After", 0)), 15)
                        except ValueError:
                            wait = 0
                        time.sleep(wait or config.API_RETRY_BACKOFF_SECONDS * attempt * 2)
                        continue
                except (requests.RequestException, ValueError) as e:
                    self._note(base, type(e).__name__)
                time.sleep(config.API_RETRY_BACKOFF_SECONDS * attempt)
        print(f"[data_fetcher] WARNING: could not fetch {path} ({self.last_error}).")
        return None

    def _note(self, base: str, what: str) -> None:
        self._errors[base.split("//")[-1].split("/")[0]] = what
        self.last_error = "; ".join(f"{host}: {err}" for host, err in self._errors.items())
        if "SSL" in what:
            self.last_error += (" - the secure (HTTPS) connection was refused. Antivirus web-shield, "
                                "VPN, proxy or a restricted Wi-Fi network is the usual cause.")

    # -- public API ----------------------------------------------------------
    def get_address_info(self, address: str) -> Optional[dict]:
        """Summary stats: balance, tx count, etc."""
        return self._get(f"/address/{address}")

    def get_address_txs(self, address: str, max_txs: int = config.MAX_TX_PER_ADDRESS) -> list:
        """
        Up to max_txs transactions touching this address, newest first.
        Esplora returns 25 confirmed tx per page, so we follow
        /txs/chain/{last_seen_txid} until we have enough or history ends.
        """
        txs = self._get(f"/address/{address}/txs")
        if txs is None:
            return []
        collected = list(txs)
        while len(collected) < max_txs:
            confirmed = [t for t in collected if t.get("status", {}).get("confirmed")]
            if not confirmed or len(txs) < config.TX_PAGE_SIZE:
                break
            time.sleep(config.API_PAGE_DELAY_SECONDS)
            txs = self._get(f"/address/{address}/txs/chain/{confirmed[-1]['txid']}")
            if not txs:
                break
            collected.extend(txs)
        return collected[:max_txs]

    def get_tx(self, txid: str) -> Optional[dict]:
        return self._get(f"/tx/{txid}")

    def get_tx_hex(self, txid: str) -> Optional[str]:
        url = f"{self.base_url}/tx/{txid}/hex"
        try:
            resp = self.session.get(url, timeout=config.API_TIMEOUT_SECONDS)
            return resp.text if resp.status_code == 200 else None
        except requests.RequestException:
            return None

    # -- normalisation ----------------------------------------------------------
    @staticmethod
    def normalize_tx(raw_tx: dict) -> dict:
        """
        Convert Blockstream's raw tx JSON into the flat shape the rest of
        BitTrace expects (satoshis -> BTC, consistent key names).
        """
        inputs = []
        for idx, vin in enumerate(raw_tx.get("vin", [])):
            prevout = vin.get("prevout") or {}
            inputs.append({
                "vin_index": idx,
                "prev_txid": vin.get("txid"),
                "prev_vout": vin.get("vout"),
                "address": prevout.get("scriptpubkey_address"),
                "value_btc": (prevout.get("value") or 0) / 1e8,
            })

        outputs = []
        for idx, vout in enumerate(raw_tx.get("vout", [])):
            outputs.append({
                "vout_index": idx,
                "address": vout.get("scriptpubkey_address"),
                "value_btc": (vout.get("value") or 0) / 1e8,
                "script_type": vout.get("scriptpubkey_type"),
            })

        status = raw_tx.get("status", {})
        return {
            "txid": raw_tx.get("txid"),
            "block_height": status.get("block_height"),
            "block_time": status.get("block_time"),
            "fee_sats": raw_tx.get("fee"),
            "inputs": inputs,
            "outputs": outputs,
        }


def check_connection() -> None:
    """Run:  python -m core.data_fetcher   - prints exactly which server works from this PC."""
    f = DataFetcher()
    for base in f.base_urls:
        one = DataFetcher(base_url=base, fallbacks=[])
        tip = one._get("/blocks/tip/height")
        print(f"{base:32s} ->", f"OK (block height {tip})" if tip else f"FAILED ({one.last_error})")


if __name__ == "__main__":
    check_connection()
    raise SystemExit(0)
    # Quick manual smoke test. Expected to fail gracefully in sandboxes that
    # block outbound internet access to blockstream.info - that's fine, it
    # proves the error handling works. On a normal machine this prints real data.
    fetcher = DataFetcher()
    test_address = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"  # Genesis block coinbase address
    info = fetcher.get_address_info(test_address)
    if info:
        print("Address info OK:", info)
    else:
        print("No network access in this environment (expected in sandbox) - "
              "data_fetcher failed gracefully as designed.")
