"""
BitTrace v2 - core/dashboard_data.py

Pure data-preparation helpers for the Timeline, History and Statistics pages.
Nothing here imports Streamlit or Plotly, so every function is unit-tested
without a browser. The pages stay thin: they call these helpers and draw the
result.

Nothing in this module invents data. A missing timestamp stays missing, a
missing count stays missing, and an empty input gives an empty (but valid)
output.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional
import sys

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

BANDS = ("high", "medium", "low")  # display order: most severe first
BAND_LABEL = {"high": "High risk", "medium": "Medium risk", "low": "Low risk"}
PATTERN_LABEL = {
    "peel_chain": "Peel chain",
    "fan_out": "Fan-out",
    "fan_in": "Fan-in",
    "coinjoin": "CoinJoin-like",
    "circular_flow": "Circular flow",
}
PATTERN_ORDER = ("fan_in", "fan_out", "coinjoin", "peel_chain", "circular_flow")


# ---------------------------------------------------------------------------
# small formatting helpers
# ---------------------------------------------------------------------------
def short_id(value: Optional[str], head: int = 8, tail: int = 6) -> str:
    """'a1b2c3d4...f9e8d7' - readable without stretching a table column."""
    if not value:
        return "-"
    value = str(value)
    return value if len(value) <= head + tail + 3 else f"{value[:head]}...{value[-tail:]}"


def band_for_score(score: float) -> str:
    """Same thresholds as the risk engine (config.RISK_BAND_*)."""
    if score >= config.RISK_BAND_HIGH:
        return "high"
    if score >= config.RISK_BAND_MEDIUM:
        return "medium"
    return "low"


def band_ranges_text() -> str:
    hi, med = config.RISK_BAND_HIGH, config.RISK_BAND_MEDIUM
    return f"Low 0-{med - 1} | Medium {med}-{hi - 1} | High {hi}-{config.RISK_SCORE_MAX}"


def parse_block_time(value) -> Optional[datetime]:
    """Return a timezone-aware UTC datetime, or None if there is no real time.

    Accepts the Unix timestamps the blockchain API returns, numeric strings and
    ISO-8601 strings. Anything else (None, '', garbage) gives None - a missing
    time is never replaced by a guess.
    """
    if value is None or value == "":
        return None
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        text = str(value).strip()
        if text.replace(".", "", 1).isdigit():
            return datetime.fromtimestamp(float(text), tz=timezone.utc)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------
RELATIONS = ("Outgoing", "Incoming", "Related")
# Deliberately NOT the green/amber/red risk colours, so relation and risk never look alike.
RELATION_COLOR = {"Outgoing": "#4DA3FF", "Incoming": "#B388FF", "Related": "#8B98A9"}
RELATION_SYMBOL = {"Outgoing": "triangle-up", "Incoming": "triangle-down", "Related": "circle"}
RELATION_HELP = {
    "Outgoing": "the investigated address is a sender (it spent funds)",
    "Incoming": "the investigated address only receives funds",
    "Related": "does not involve the investigated address; fetched for a neighbouring address while tracing hops",
}


def classify_tx(tx: dict, root: str) -> str:
    """How a transaction relates to the investigated address.

    Outgoing - the investigated address is one of the senders (it spent funds;
               change returned to the same address still counts as outgoing).
    Incoming - the investigated address only receives funds.
    Related  - the investigated address is not in the transaction at all. Such
               transactions are fetched for neighbouring addresses when more
               than one hop is traced.
    """
    sends = any((i or {}).get("address") == root for i in tx.get("inputs") or [])
    receives = any((o or {}).get("address") == root for o in tx.get("outputs") or [])
    if sends:
        return "Outgoing"
    if receives:
        return "Incoming"
    return "Related"


def timeline_frame(result: dict) -> pd.DataFrame:
    """One row per analysed transaction, in the order the pipeline returned them.

    Columns: order, txid, short_txid, time (UTC, NaT when unknown), has_time,
    relation, n_inputs, n_outputs, value_btc (sum of output values).
    """
    root = result.get("root_address")
    rows = []
    for order, tx in enumerate(result.get("txs") or [], start=1):
        outputs = tx.get("outputs") or []
        when = parse_block_time(tx.get("block_time"))
        rows.append({
            "order": order,
            "txid": tx.get("txid") or "",
            "short_txid": short_id(tx.get("txid")),
            "time": pd.Timestamp(when) if when else pd.NaT,
            "has_time": when is not None,
            "relation": classify_tx(tx, root),
            "n_inputs": len(tx.get("inputs") or []),
            "n_outputs": len(outputs),
            "value_btc": float(sum((o or {}).get("value_btc") or 0 for o in outputs)),
        })
    columns = ["order", "txid", "short_txid", "time", "has_time", "relation",
               "n_inputs", "n_outputs", "value_btc"]
    return pd.DataFrame(rows, columns=columns)


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
def risk_summary(row: dict) -> str:
    """Plain-text risk summary for one investigation summary row."""
    if not row.get("n_scored"):
        return "No results saved"
    parts = []
    if row.get("n_high"):
        parts.append(f"{row['n_high']} high")
    if row.get("n_medium"):
        parts.append(f"{row['n_medium']} medium")
    if not parts:
        return "No high or medium risk addresses"
    return ", ".join(parts)


def investigation_status(row: dict) -> str:
    """'Completed' when scores were saved, otherwise 'Incomplete'.

    An investigation row is created at the start of a run; scores are saved at
    the very end. A row with no scores is a run that stopped before finishing.
    """
    return "Completed" if row.get("n_scored") else "Incomplete"


def top_band(row: dict) -> str:
    """Highest risk band present, as a text label (not colour alone)."""
    if row.get("n_high"):
        return BAND_LABEL["high"]
    if row.get("n_medium"):
        return BAND_LABEL["medium"]
    if row.get("n_low"):
        return BAND_LABEL["low"]
    return "-"


def history_frame(summaries: Iterable[dict]) -> pd.DataFrame:
    rows = []
    for r in summaries:
        rows.append({
            "ID": r["id"],
            "Investigated address": r["root_address"],
            "Date (UTC)": r.get("created_at") or "-",
            "Hops": r.get("max_hops"),
            "Status": investigation_status(r),
            "Addresses scored": int(r.get("n_scored") or 0),
            "Highest band": top_band(r),
            "Max score": None if r.get("max_score") is None else float(r["max_score"]),
            "High": int(r.get("n_high") or 0),
            "Medium": int(r.get("n_medium") or 0),
            "Low": int(r.get("n_low") or 0),
            "Clusters": int(r.get("n_clusters") or 0),
            "Patterns": int(r.get("n_patterns") or 0),
            "Stored txs (address)": int(r.get("stored_root_txs") or 0),
            "Notes": (r.get("notes") or "").strip() or "-",
        })
    return pd.DataFrame(rows)


def investigation_label(row: dict) -> str:
    """Selectbox label that tells repeated runs of one address apart."""
    return (f"#{row['id']} | {short_id(row['root_address'], 8, 6)} | "
            f"{(row.get('created_at') or '-')[:16]} | {risk_summary(row)}")


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def latest_run_ids(summaries: Iterable[dict]) -> List[int]:
    """ID of the newest *completed* run for each investigated address."""
    newest: Dict[str, dict] = {}
    for r in summaries:
        if not r.get("n_scored"):
            continue
        cur = newest.get(r["root_address"])
        if cur is None or (r.get("created_at") or "", r["id"]) > (cur.get("created_at") or "", cur["id"]):
            newest[r["root_address"]] = r
    return sorted(r["id"] for r in newest.values())


def select_ids(summaries: List[dict], scope: str, single_id: Optional[int] = None) -> List[int]:
    """Investigation IDs included for a Statistics scope.

    scope: 'all' | 'latest' | 'single'
    """
    if scope == "single":
        return [single_id] if single_id is not None else []
    if scope == "latest":
        return latest_run_ids(summaries)
    return [r["id"] for r in summaries]


def band_counts(score_rows: Iterable[dict], ids: Iterable[int]) -> Dict[str, int]:
    wanted = set(ids)
    counts = {b: 0 for b in BANDS}
    for r in score_rows:
        if r["investigation_id"] in wanted and r["band"] in counts:
            counts[r["band"]] += 1
    return counts


def pattern_counts(pattern_rows: Iterable[dict], ids: Iterable[int]) -> Dict[str, int]:
    """Counts for every known pattern type (zero when none), plus any unknown type found."""
    wanted = set(ids)
    counts = {p: 0 for p in PATTERN_ORDER}
    for r in pattern_rows:
        if r["investigation_id"] in wanted:
            counts[r["pattern_type"]] = counts.get(r["pattern_type"], 0) + int(r["n"])
    return counts


def score_histogram(score_rows: Iterable[dict], ids: Iterable[int], bin_size: int = 5) -> pd.DataFrame:
    """Counts of risk scores in fixed-width bins covering 0..RISK_SCORE_MAX.

    Every bin is present (zero counts included). With the default bin size of 5
    both band thresholds (35 and 60) fall on bin edges, so each bin belongs to
    exactly one band. The last bin includes the maximum score.
    """
    wanted = set(ids)
    top = int(config.RISK_SCORE_MAX)
    edges = list(range(0, top + 1, bin_size))
    counts = [0] * (len(edges) - 1)
    for r in score_rows:
        if r["investigation_id"] not in wanted:
            continue
        s = min(max(float(r["score"]), 0.0), float(top))
        idx = min(int(s // bin_size), len(counts) - 1)
        counts[idx] += 1
    rows = []
    for i, c in enumerate(counts):
        lo, hi = edges[i], edges[i + 1]
        last = i == len(counts) - 1
        rows.append({
            "bin_start": lo,
            "bin_end": hi,
            "label": f"{lo}-{hi}" if last else f"{lo}-{hi - 1}",
            "count": c,
            "band": band_for_score(lo),
        })
    return pd.DataFrame(rows)
