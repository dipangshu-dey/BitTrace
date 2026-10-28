"""
BitTrace v2 - Central configuration.
All tunables live here so modules never hardcode paths, thresholds, or
external endpoints.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"
DB_PATH = DATA_DIR / "bittrace.db"
SCHEMA_PATH = BASE_DIR / "db" / "schema.sql"

DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Blockchain data source
# ---------------------------------------------------------------------------
BLOCKSTREAM_API_BASE = "https://blockstream.info/api"
API_FALLBACK_BASES = ["https://mempool.space/api"]   # same Esplora API, used if the primary fails
API_TIMEOUT_SECONDS = 15
API_MAX_RETRIES = 4
API_RETRY_BACKOFF_SECONDS = 1.5

# Safety limits so a single investigation can't hammer the API forever
MAX_TX_PER_ADDRESS = 100          # root address: paginated, 25 tx per API page
TX_PAGE_SIZE = 25                 # Esplora returns 25 confirmed tx per page
HOP_MAX_NEIGHBORS = 6             # per extra hop: expand only the busiest N counterparties
HOP_MAX_TX_PER_ADDRESS = 25       # per expanded neighbour (one API page)
API_PAGE_DELAY_SECONDS = 0.25     # be polite to the free API
MAX_HOPS_DEFAULT = 3

# ---------------------------------------------------------------------------
# Clustering (Objective 1)
# ---------------------------------------------------------------------------
# Change-address heuristics: a candidate output is flagged "change" if it
# accumulates enough of these signals.
CHANGE_HEURISTIC_MIN_SIGNALS = 2
CHANGE_ADDR_TYPE_MATCH_WEIGHT = 1     # same script-type as an input
CHANGE_NO_ROUND_AMOUNT_WEIGHT = 1     # not a "round" payment amount
CHANGE_SINGLE_OUTPUT_BACK_WEIGHT = 1  # only output not seen paid elsewhere first time

# ---------------------------------------------------------------------------
# Pattern detection (Objective 2)
# ---------------------------------------------------------------------------
PEEL_CHAIN_MIN_HOPS = 3
PEEL_CHAIN_MAX_HOPS = 200          # safety cap; also cycle-guarded
FAN_OUT_MIN_OUTPUTS = 5
FAN_IN_MIN_INPUTS = 5
COINJOIN_MIN_EQUAL_OUTPUTS = 3
COINJOIN_EQUAL_OUTPUT_TOLERANCE = 0.00000001  # BTC, float tolerance

# ---------------------------------------------------------------------------
# Risk engine (Objective 3)
# ---------------------------------------------------------------------------
RISK_WEIGHTS = {
    "sanctioned_match": 45,
    "ransomware_match": 35,
    "darknet_match": 25,
    "peel_chain": 10,
    "coinjoin": 8,
    "fan_out": 6,
    "fan_in": 6,
    "circular_flow": 10,
    "high_betweenness": 8,
    "exchange_heuristic": -5,   # exchanges are lower-risk pass-through, slight discount
}
RISK_SCORE_MAX = 100
RISK_DATASET_MATCH_FLOOR = 70      # a confirmed threat-list match is never below this
RISK_BAND_HIGH = 60
RISK_BAND_MEDIUM = 35

# ---------------------------------------------------------------------------
# Entity attribution (Objective 4)
# ---------------------------------------------------------------------------
# NOTE: threat_intel.py ships with a small set of REAL, sourced addresses
# (verified OFAC/WannaCry/Silk Road cases) - see core/threat_intel.py for
# sources and instructions on extending the list with the full OFAC SDN feed.
RANSOMWHERE_API_URL = "https://api.ransomwhe.re/export"  # unverified, best-effort
EXCHANGE_MIN_OUTGOING_TX = 1
EXCHANGE_MIN_DISTINCT_COUNTERPARTIES = 5

# ---------------------------------------------------------------------------
# AI Assistant (Ollama + RAG)
# ---------------------------------------------------------------------------
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
RAG_TOP_K = 8                 # facts retrieved per question, on top of the always-included overview facts
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))   # Ollama's default window is small and silently truncates the prompt
OLLAMA_TIMEOUT_S = int(os.environ.get("OLLAMA_TIMEOUT_S", "300"))  # first call loads the model into memory

# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
APP_TITLE = "BitTrace v2 - Bitcoin Forensics & Threat Attribution"
