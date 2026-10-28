"""
BitTrace v2 - ai/investigation_context.py

Loads everything BitTrace has SAVED about ONE investigation, straight from the
database, so the AI Assistant can answer questions about exactly that
investigation and nothing else.

Why the database and not st.session_state["last_result"]:
  - session state only holds the most recent run and can be stale;
  - every record read here is filtered by the investigation id the user picked,
    so two investigations can never be mixed.

What is and is not stored (the schema decides this, not this module):
  - risk scores, clusters and patterns are stored per investigation  -> exact.
  - threat-list matches and entity attributions are stored per ADDRESS (shared
    by every investigation that contains the address). They are filtered to this
    investigation's addresses, and labelled as address-level records.
  - transactions are stored in shared tables that are NOT linked to an
    investigation, and the transaction graph / graph analytics are not stored.
    The "flow" figures below are therefore computed from the stored transactions
    that touch an address, and are labelled as such.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))

from db import database

CONTEXT_KIND = "stored_investigation_context"
FLOW_TOP_COUNTERPARTIES = 8
FLOW_FLAGGED_ADDRESSES = 5
_IN_CHUNK = 400


# ---------------------------------------------------------------------------
# Selector support
# ---------------------------------------------------------------------------
def short_address(addr: str, head: int = 8, tail: int = 6) -> str:
    addr = addr or ""
    return addr if len(addr) <= head + tail + 3 else f"{addr[:head]}...{addr[-tail:]}"


def list_investigation_options() -> List[dict]:
    """Saved investigations, newest first, each with a ready-to-show label.

    Keys: id, root_address, created_at, max_hops, complete (bool), label,
    fingerprint (changes when the saved results for that investigation change).
    """
    options = []
    for r in database.get_investigation_summaries():
        complete = bool(r.get("n_scored"))
        when = (r.get("created_at") or "")[:16]
        label = f"#{r['id']}  |  {short_address(r['root_address'])}  |  {when}"
        if not complete:
            label += "  |  no saved results"
        options.append({
            "id": int(r["id"]), "root_address": r["root_address"], "created_at": r.get("created_at"),
            "max_hops": r.get("max_hops"), "complete": complete, "label": label,
            "fingerprint": (r.get("n_scored"), r.get("n_clusters"), r.get("n_patterns"), r.get("created_at")),
        })
    return options


# ---------------------------------------------------------------------------
# Loading one investigation
# ---------------------------------------------------------------------------
def _loads(text, default):
    try:
        return json.loads(text) if text else default
    except (TypeError, ValueError):
        return default


def _chunks(items: list, n: int = _IN_CHUNK):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _address_flow(conn, address: str) -> dict:
    """Totals and top counterparties for one address from the stored transactions."""
    one = lambda sql, *p: conn.execute(sql, p).fetchone()
    tx_count = one("SELECT COUNT(*) AS n FROM (SELECT txid FROM tx_inputs WHERE address = ? "
                   "UNION SELECT txid FROM tx_outputs WHERE address = ?)", address, address)["n"]
    out = {"address": address, "stored_tx_count": int(tx_count)}
    if not tx_count:
        return out
    out["paid_to_address_btc"] = float(one("SELECT COALESCE(SUM(value_btc),0) AS v FROM tx_outputs WHERE address = ?", address)["v"])
    out["spent_from_address_btc"] = float(one("SELECT COALESCE(SUM(value_btc),0) AS v FROM tx_inputs WHERE address = ?", address)["v"])
    out["n_as_sender"] = int(one("SELECT COUNT(DISTINCT txid) AS n FROM tx_inputs WHERE address = ?", address)["n"])
    out["n_as_receiver"] = int(one("SELECT COUNT(DISTINCT txid) AS n FROM tx_outputs WHERE address = ?", address)["n"])
    times = one("SELECT MIN(t.block_time) AS a, MAX(t.block_time) AS b FROM transactions t WHERE t.block_time IS NOT NULL "
                "AND t.txid IN (SELECT txid FROM tx_inputs WHERE address = ? UNION SELECT txid FROM tx_outputs WHERE address = ?)",
                address, address)
    out["first_block_time"], out["last_block_time"] = times["a"], times["b"]
    out["top_recipients"] = [dict(r) for r in conn.execute(
        "SELECT o.address AS address, ROUND(SUM(o.value_btc), 8) AS btc, COUNT(DISTINCT o.txid) AS n_tx "
        "FROM tx_outputs o WHERE o.address IS NOT NULL AND o.address != ? "
        "AND o.txid IN (SELECT txid FROM tx_inputs WHERE address = ?) "
        "GROUP BY o.address ORDER BY SUM(o.value_btc) DESC LIMIT ?", (address, address, FLOW_TOP_COUNTERPARTIES))]
    out["top_senders"] = [dict(r) for r in conn.execute(
        "SELECT i.address AS address, ROUND(SUM(i.value_btc), 8) AS btc, COUNT(DISTINCT i.txid) AS n_tx "
        "FROM tx_inputs i WHERE i.address IS NOT NULL AND i.address != ? "
        "AND i.txid IN (SELECT txid FROM tx_outputs WHERE address = ?) "
        "GROUP BY i.address ORDER BY SUM(i.value_btc) DESC LIMIT ?", (address, address, FLOW_TOP_COUNTERPARTIES))]
    out["distinct_recipients"] = int(one(
        "SELECT COUNT(DISTINCT o.address) AS n FROM tx_outputs o WHERE o.address IS NOT NULL AND o.address != ? "
        "AND o.txid IN (SELECT txid FROM tx_inputs WHERE address = ?)", address, address)["n"])
    out["distinct_senders"] = int(one(
        "SELECT COUNT(DISTINCT i.address) AS n FROM tx_inputs i WHERE i.address IS NOT NULL AND i.address != ? "
        "AND i.txid IN (SELECT txid FROM tx_outputs WHERE address = ?)", address, address)["n"])
    return out


def load_investigation_context(investigation_id: int) -> Optional[dict]:
    """Everything saved for `investigation_id`, read fresh from the database.

    Returns None if that investigation does not exist (e.g. it was deleted).
    """
    inv = database.get_investigation(int(investigation_id))
    if not inv:
        return None
    iid = int(inv["id"])
    root = inv["root_address"]

    risk = []
    for row in database.get_risk_scores_for_investigation(iid):          # filtered by investigation_id
        breakdown = (_loads(row["explanation_json"], {}) or {}).get("breakdown", [])
        risk.append({"address": row["address"], "score": float(row["score"]), "band": row["band"],
                     "signals": breakdown})

    patterns = []
    for row in database.get_patterns_for_investigation(iid):             # filtered by investigation_id
        patterns.append({"type": row["pattern_type"], "addresses": _loads(row["addresses_json"], []),
                         "detail": _loads(row["detail_json"], {})})

    clusters = []
    for c in database.get_clusters_for_investigation(iid):               # filtered by investigation_id
        members = sorted(m["address"] for m in database.get_cluster_addresses(c["id"]))
        clusters.append({"label": c["label"] or "", "size": len(members), "members": members,
                         "total_btc": float(c["total_btc"] or 0)})

    # This investigation's address set. Address-level tables are filtered down to it.
    addr_set = {r["address"] for r in risk} | {root}
    for c in clusters:
        addr_set.update(c["members"])
    for p in patterns:
        addr_set.update(a for a in p["addresses"] if a)
    addr_list = sorted(addr_set)

    threat, entities, flows = [], [], []
    # A run that saved nothing has no investigation-specific results; address-level records
    # (threat lists, stored transactions) would only come from OTHER runs, so they are not loaded.
    with database.get_conn() as conn:
        for chunk in (_chunks(addr_list) if risk else []):
            q = ",".join("?" * len(chunk))
            threat += [dict(r) for r in conn.execute(
                f"SELECT address, list_name, entity_label, source FROM threat_matches WHERE address IN ({q})", chunk)]
            entities += [dict(r) for r in conn.execute(
                f"SELECT address, entity_type, confidence, method, detail FROM entity_attributions WHERE address IN ({q})", chunk)]

        if risk:
            flagged = [r["address"] for r in risk if r["address"] != root and r["band"] in ("high", "medium")]
            flows = [_address_flow(conn, a) for a in [root] + flagged[:FLOW_FLAGGED_ADDRESSES]]

    return {
        "kind": CONTEXT_KIND,
        "investigation_id": iid, "root_address": root, "created_at": inv["created_at"],
        "max_hops": inv["max_hops"], "notes": inv["notes"] or "",
        "complete": bool(risk),
        "risk": risk, "patterns": patterns, "clusters": clusters,
        "threat_matches": threat, "entities": entities, "flows": flows,
        "n_addresses": len(addr_set),
    }


# ---------------------------------------------------------------------------
# Context -> retrievable text documents
# ---------------------------------------------------------------------------
def _btc(v) -> str:
    return f"{float(v):,.8f}".rstrip("0").rstrip(".") + " BTC" if v is not None else "n/a"


def _band_counts(risk: List[dict]) -> Dict[str, int]:
    out = {"high": 0, "medium": 0, "low": 0}
    for r in risk:
        out[r["band"]] = out.get(r["band"], 0) + 1
    return out


def _pattern_counts(patterns: List[dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for p in patterns:
        out[p["type"]] = out.get(p["type"], 0) + 1
    return out


def _signals_text(signals: List[dict], with_reason: bool = False) -> str:
    if not signals:
        return "none recorded"
    parts = []
    for s in signals:
        t = f"{s.get('signal', '?')} ({s.get('points', '?')} pts)"
        if with_reason and s.get("reason"):
            t += f": {str(s['reason'])[:90]}"
        parts.append(t)
    return "; ".join(parts)


def _compact(obj, limit: int = 320) -> str:
    text = json.dumps(obj, default=str, separators=(",", ":"))
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


def build_context_documents(ctx: dict) -> List[dict]:
    """Flatten a loaded context into short text documents.

    Documents with pinned=True are ALWAYS given to the model (the overview a
    question like "summarise this investigation" needs); the rest are retrieved
    per question.
    """
    iid, root = ctx["investigation_id"], ctx["root_address"]
    risk, patterns, clusters = ctx["risk"], ctx["patterns"], ctx["clusters"]
    docs: List[dict] = []
    tag = f"[Investigation #{iid}]"

    bands = _band_counts(risk)
    pcounts = _pattern_counts(patterns)
    threat_addrs = sorted({t["address"] for t in ctx["threat_matches"]})
    status = ("saved results present" if ctx["complete"]
              else "NO saved results - this run did not finish, so there are no risk scores, clusters or patterns")
    docs.append({"id": "summary", "pinned": True, "text": (
        f"{tag} Investigated address: {root}. Created {ctx['created_at']} UTC, tracing up to {ctx['max_hops']} hop(s). "
        f"Status: {status}. Notes: {ctx['notes'] or 'none'}. "
        f"Addresses with a saved risk score: {len(risk)} (high {bands['high']}, medium {bands['medium']}, low {bands['low']}). "
        f"Clusters: {len(clusters)}. Suspicious patterns: {len(patterns)}"
        + (f" ({', '.join(f'{k}: {v}' for k, v in sorted(pcounts.items()))})" if pcounts else "")
        + f". Threat-list matches among this investigation's addresses: {len(ctx['threat_matches'])}"
        + (f" ({len(threat_addrs)} address(es))." if threat_addrs else ".")
    )})

    docs.append({"id": "limits", "pinned": True, "text": (
        f"{tag} Data limits: BitTrace did not save the transaction graph or graph analytics for this investigation, so "
        "they are not available. Transactions are stored in shared tables not linked to one investigation, so the "
        "transaction-flow figures below are computed from stored transactions that touch the named address and may include "
        "transactions fetched by other investigations. Threat-list matches and entity labels are address-level records."
    )})

    if risk:
        top = risk[:10]
        lines = [f"{r['address']}: score {r['score']:g} ({r['band']}); signals: {_signals_text(r['signals'], True)}" for r in top]
        docs.append({"id": "top_risk", "pinned": True,
                     "text": f"{tag} Highest-risk addresses (score is 0-100, from BitTrace's rule-based scoring): " + " | ".join(lines)})
    if ctx["threat_matches"]:
        shown = ctx["threat_matches"][:15]
        docs.append({"id": "threat_digest", "pinned": True, "text": (
            f"{tag} Threat-list matches: " + " | ".join(
                f"{t['address']} matched list '{t['list_name']}' ({t['entity_label'] or 'no label'}; source {t['source'] or 'n/a'})"
                for t in shown) + (f" | ...and {len(ctx['threat_matches']) - 15} more" if len(ctx["threat_matches"]) > 15 else ""))})
    else:
        docs.append({"id": "threat_digest", "pinned": True,
                     "text": f"{tag} Threat-list matches: none recorded for any address in this investigation."})
    if patterns:
        docs.append({"id": "pattern_digest", "pinned": True, "text": (
            f"{tag} Suspicious pattern counts: " + ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in sorted(pcounts.items())) + ".")})
    else:
        docs.append({"id": "pattern_digest", "pinned": True,
                     "text": f"{tag} Suspicious patterns: none were detected and saved for this investigation."})

    for f in ctx["flows"]:
        a = f["address"]
        role = "investigated (root) address" if a == root else "flagged address"
        if not f["stored_tx_count"]:
            docs.append({"id": f"flow:{a}", "pinned": a == root,
                         "text": f"{tag} Transaction flow for {role} {a}: no stored transactions touch this address."})
            continue
        head = (f"{tag} Transaction flow for {role} {a} (from stored transactions touching it): "
                f"{f['stored_tx_count']} transactions ({f['n_as_sender']} where it is an input/sender, {f['n_as_receiver']} where it "
                f"is an output/receiver); outputs paying it total {_btc(f['paid_to_address_btc'])}; inputs spent from it total "
                f"{_btc(f['spent_from_address_btc'])}; first/last block time {f['first_block_time'] or 'n/a'} / {f['last_block_time'] or 'n/a'}; "
                f"{f['distinct_recipients']} distinct other addresses received outputs of its spends; "
                f"{f['distinct_senders']} distinct other addresses funded transactions that paid it.")
        docs.append({"id": f"flow:{a}", "pinned": a == root, "text": head})
        if f["top_recipients"]:
            docs.append({"id": f"flow_out:{a}", "pinned": False, "text": (
                f"{tag} Top addresses that received Bitcoin in transactions where {a} was a sender: " + "; ".join(
                    f"{r['address']} {_btc(r['btc'])} over {r['n_tx']} tx" for r in f["top_recipients"]) + ".")})
        if f["top_senders"]:
            docs.append({"id": f"flow_in:{a}", "pinned": False, "text": (
                f"{tag} Top addresses that sent Bitcoin in transactions where {a} was a receiver: " + "; ".join(
                    f"{r['address']} {_btc(r['btc'])} over {r['n_tx']} tx" for r in f["top_senders"]) + ".")})

    for r in risk:
        docs.append({"id": f"risk:{r['address']}", "pinned": False, "text": (
            f"{tag} Address {r['address']} has risk score {r['score']:g} ({r['band']} risk). "
            f"Signals: {_signals_text(r['signals'], True)}.")})

    for i, c in enumerate(clusters):
        members = c["members"]
        shown = ", ".join(members[:20]) + (f", ...and {len(members) - 20} more" if len(members) > 20 else "")
        docs.append({"id": f"cluster:{i}", "pinned": False, "text": (
            f"{tag} Cluster '{c['label'] or i}' has {c['size']} addresses believed to be controlled by the same wallet "
            f"(total flow {_btc(c['total_btc'])}): {shown}.")})

    for i, p in enumerate(patterns):
        addrs = [a for a in p["addresses"] if a]
        shown = ", ".join(addrs[:6]) + (f", ...and {len(addrs) - 6} more" if len(addrs) > 6 else "")
        docs.append({"id": f"pattern:{i}", "pinned": False, "text": (
            f"{tag} Detected {p['type'].replace('_', ' ')} pattern involving {len(addrs)} address(es): {shown}. "
            f"Detail: {_compact(p['detail'])}")})

    for t in ctx["threat_matches"]:
        docs.append({"id": f"threat:{t['address']}:{t['list_name']}", "pinned": False, "text": (
            f"{tag} Threat-list match: address {t['address']} is on list '{t['list_name']}' "
            f"({t['entity_label'] or 'no label'}, source {t['source'] or 'n/a'}).")})

    for e in ctx["entities"]:
        docs.append({"id": f"entity:{e['address']}:{e['method']}", "pinned": False, "text": (
            f"{tag} Address {e['address']} is attributed as entity type '{e['entity_type']}' via {e['method']} "
            f"(confidence {e['confidence']}). {e['detail'] or ''}")})
    return docs
