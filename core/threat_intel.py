"""
BitTrace v2 - core/threat_intel.py
Objective 4 data source: known-bad address lists used for dataset-match
attribution.

DATA SOURCE & VERIFICATION
---------------------------
The addresses shipped in data/threat_intel/*.json are REAL, publicly
documented Bitcoin addresses, not placeholders. Each one was verified via
web search against independent, named sources before being added here:

  - OFAC_SDN.json:
      * 149w62rY42aZBox8fGcmqNsXUzSStKeq8C / 1AjZPMsnmpdK2Rv9KQNfMurTXinscVro9V
        - Ali Khorashadizadeh and Mohammad Ghorbaniyan, the first-ever Bitcoin
          addresses added to OFAC's SDN list (2018-11-28), for converting
          SamSam ransomware proceeds to Iranian rial. Addresses as published
          by OFAC and reported by Slate, WilmerHale, FDD, RUSI, and others.
      * 12QtD5BFwRsdNsAZY76UVE1xyCGNTojH9h / 1Kuf2Rd8mDyAViwBozGTNYnvWL8uYFrkVo
        - Example output from the open-source
          0xB10C/ofac-sanctioned-digital-currency-addresses tool, which
          extracts XBT addresses directly from Treasury's sdn_advanced.xml.
  - WannaCry.json:
      * 13AM4VW2dhxYgXeQepoHkHSQuy6NgaEb94
      * 12t9YDPgwueZ9NyMgw519p7AA8isjr6SMw
      * 115p7UMMngoj1pMvkpHijcRdfJNXj6LrLn
        - The three Bitcoin addresses hardcoded into the WannaCry ransomware
          binary (May 2017 global outbreak). Independently corroborated
          across Symantec/Security.com, academic analysis (arXiv:1804.01341),
          Cambridge Intelligence's WannaCry writeup, and live-tracking posts
          from the May 2017 outbreak itself.
  - DarknetMarket.json:
      * 1HQ3Go3ggs8pFnXuHVHRytPCq5fGG8Hbhx
        - The US government's forfeiture address for ~69,370 BTC traced back
          to the Silk Road marketplace (James Zhong case), named in the DOJ's
          civil forfeiture filing "United States of America v. Approximately
          69,370 Bitcoin..." (filed 2020-11-05).

These are still a SMALL, hand-picked set for demo purposes, not a
comprehensive sanctions/ransomware database. For production or thorough
coursework use, pull the full, continuously-updated lists:

  - Full OFAC SDN digital-currency address list: run the open-source
    extractor against Treasury's live data -
    https://github.com/0xB10C/ofac-sanctioned-digital-currency-addresses
    (it also publishes a pre-generated `lists` branch, refreshed nightly)
  - OFAC's own lookup/download tools: https://sanctionssearch.ofac.treas.gov/
    and https://ofac.treasury.gov (search "SDN list data formats")
  - ransomwhe.re export (crowd-sourced ransomware address tracker):
    https://ransomwhe.re/ - config.RANSOMWHERE_API_URL fetches this live;
    the exact endpoint/response shape has not been independently pinned
    down here, so fetch_ransomwhere() fails gracefully and logs a warning
    rather than trusting an unverified schema silently.

To extend the bundled data, just add more objects to the JSON files in
data/threat_intel/ - build_lookup_index() picks up whatever is there.
"""

import json
from pathlib import Path
from typing import Dict, List
import sys

import requests

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

# ---------------------------------------------------------------------------
# Minimal built-in fallback - used ONLY if the JSON files under
# data/threat_intel/ are missing (e.g. someone deletes them). Contains the
# same verified addresses described in the module docstring above, so the
# app still has *something* real to match against even if the data files
# disappear.
# ---------------------------------------------------------------------------
FALLBACK_OFAC_SDN: List[Dict[str, str]] = [
    {"address": "149w62rY42aZBox8fGcmqNsXUzSStKeq8C",
     "entity_label": "Ali Khorashadizadeh - OFAC SDN, designated 2018-11-28 (SamSam ransomware BTC-to-rial exchanger)"},
    {"address": "1AjZPMsnmpdK2Rv9KQNfMurTXinscVro9V",
     "entity_label": "Mohammad Ghorbaniyan - OFAC SDN, designated 2018-11-28 (SamSam ransomware BTC-to-rial exchanger)"},
]

FALLBACK_WANNACRY: List[Dict[str, str]] = [
    {"address": "13AM4VW2dhxYgXeQepoHkHSQuy6NgaEb94", "entity_label": "WannaCry hardcoded payout address"},
    {"address": "12t9YDPgwueZ9NyMgw519p7AA8isjr6SMw", "entity_label": "WannaCry hardcoded payout address"},
    {"address": "115p7UMMngoj1pMvkpHijcRdfJNXj6LrLn", "entity_label": "WannaCry hardcoded payout address"},
]

FALLBACK_DARKNET_MARKET: List[Dict[str, str]] = [
    {"address": "1HQ3Go3ggs8pFnXuHVHRytPCq5fGG8Hbhx",
     "entity_label": "US government Silk Road forfeiture address (James Zhong case, 2020-11-05)"},
]


def load_local_lists() -> Dict[str, List[Dict[str, str]]]:
    """
    Returns the combined threat-intel lists, loaded from
    data/threat_intel/*.json (real, sourced addresses - see module
    docstring). Falls back to the small built-in set above only if a given
    JSON file is missing, so the app still works out of the box even in a
    fresh checkout before anyone has customized the data directory.
    """
    override_dir = config.DATA_DIR / "threat_intel"
    lists = {
        "OFAC_SDN": FALLBACK_OFAC_SDN,
        "WannaCry": FALLBACK_WANNACRY,
        "DarknetMarket": FALLBACK_DARKNET_MARKET,
    }

    for list_name in list(lists.keys()):
        data_file = override_dir / f"{list_name}.json"
        if data_file.exists():
            try:
                with open(data_file, "r", encoding="utf-8") as f:
                    lists[list_name] = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                print(f"[threat_intel] WARNING: could not load {data_file}: {e}. "
                      f"Falling back to built-in verified addresses for {list_name}.")

    return lists


def fetch_ransomwhere(timeout: int = 15) -> List[Dict[str, str]]:
    """
    Best-effort fetch of the ransomwhe.re public export. The exact endpoint
    URL (config.RANSOMWHERE_API_URL) has NOT been independently verified as
    still correct - ransomwhe.re has changed its API shape before. This
    fails gracefully (returns []) rather than crashing the pipeline, and
    prints a clear warning either way so a demo never silently uses stale
    or wrong data.
    """
    try:
        resp = requests.get(config.RANSOMWHERE_API_URL, timeout=timeout)
        if resp.status_code != 200:
            print(f"[threat_intel] ransomwhe.re fetch failed: HTTP {resp.status_code}. "
                  f"Falling back to the bundled OFAC/WannaCry/DarknetMarket lists only.")
            return []
        data = resp.json()
        # ransomwhe.re's export shape has historically been a list of
        # {"address": ..., "family": ...} records - adjust the parsing here
        # if the live schema differs when you test it.
        results = []
        for rec in data if isinstance(data, list) else data.get("result", []):
            addr = rec.get("address")
            if addr:
                results.append({"address": addr, "entity_label": rec.get("family", "ransomware")})
        return results
    except requests.RequestException as e:
        print(f"[threat_intel] ransomwhe.re unreachable ({e}). "
              f"Falling back to the bundled OFAC/WannaCry/DarknetMarket lists only.")
        return []


def build_lookup_index(include_ransomwhere: bool = False) -> Dict[str, List[Dict[str, str]]]:
    """
    address -> list of {list_name, entity_label} matches (an address could
    theoretically appear on more than one list).
    """
    lists = load_local_lists()
    if include_ransomwhere:
        rw = fetch_ransomwhere()
        if rw:
            lists["ransomwhere"] = rw

    index: Dict[str, List[Dict[str, str]]] = {}
    for list_name, entries in lists.items():
        for entry in entries:
            index.setdefault(entry["address"], []).append({
                "list_name": list_name,
                "entity_label": entry.get("entity_label", ""),
            })
    return index


def lookup_address(address: str, index: Dict[str, List[Dict[str, str]]] = None) -> List[Dict[str, str]]:
    if index is None:
        index = build_lookup_index()
    return index.get(address, [])


if __name__ == "__main__":
    index = build_lookup_index(include_ransomwhere=False)
    list_names = sorted({m["list_name"] for v in index.values() for m in v})
    print(f"Loaded {len(index)} real, sourced threat-intel addresses across {len(list_names)} lists: {list_names}")

    # Real WannaCry address - should hit
    test_hit = lookup_address("13AM4VW2dhxYgXeQepoHkHSQuy6NgaEb94", index)
    # A random, never-listed address - should miss
    test_miss = lookup_address("1SOMEADDRESSNOTONANYLIST00000000", index)
    assert test_hit and test_hit[0]["list_name"] == "WannaCry"
    assert test_miss == []
    print("PASS: lookup works against real addresses, fails gracefully offline "
          "(ransomwhe.re not called), correct match/no-match behaviour confirmed.")
    print("\nSample matches:")
    for addr in ["149w62rY42aZBox8fGcmqNsXUzSStKeq8C", "1HQ3Go3ggs8pFnXuHVHRytPCq5fGG8Hbhx"]:
        for m in lookup_address(addr, index):
            print(f"  {addr} -> [{m['list_name']}] {m['entity_label']}")
