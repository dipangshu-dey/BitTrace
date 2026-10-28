"""
BitTrace - Graph Explorer

Interactive view of the fund-flow graph built by the investigation pipeline.
Everything shown here comes from the investigation stored in
st.session_state["last_result"] (the same source the original page used):

  result["graph"]        networkx.MultiDiGraph, address -> address.
                         Edge attrs: txid, value_btc, block_time, is_change
  result["risk_scores"]  {address: {"score", "band", "breakdown": [...]}}
  result["entity_map"]   {address: [{"entity_type", "method", "confidence", "detail"}]}
  result["analytics"]    {address: {"pagerank", "betweenness", ..., "community"}}
  result["clusters"]     [{"root", "size", "members"}]
  result["patterns"]     {pattern_type: [ {...}, ... ]}

Graph selection / trimming logic is reused from core.graph_view
(build_focus_view, short, _positions).

Investigation selector
  * The investigation open in this session (st.session_state["last_result"]) is used exactly as before.
  * Any other saved investigation is rebuilt READ-ONLY from the database. The schema does not link
    transactions to an investigation, so the graph is reconstructed from the shared transaction tables
    and only shown if it passes a check against the investigation's own saved risk scores
    (see reconstruct_saved_investigation). The page never writes to the database.
"""

from __future__ import annotations

import hashlib
import html
import math
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import networkx as nx
import pandas as pd
import streamlit as st

import config
from db import database
from ui_theme import ACCENT, apply_theme, metric_cards
from core.dashboard_data import investigation_label, investigation_status
from core.graph_view import BAND_COLOR, BAND_LABEL, X_STEP, build_focus_view, short
from core.graph_view import _positions as flow_positions

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
UNSCORED = "unscored"
BAND_COLORS = {**BAND_COLOR, UNSCORED: "#6B7686"}
BAND_LABELS = {**BAND_LABEL, UNSCORED: "No risk data"}
BAND_ORDER = ("high", "medium", "low", UNSCORED)
BAND_RANK = {"high": 2, "medium": 1, "low": 0, UNSCORED: -1}

LAYOUTS = ["Flow (left to right)", "Force-directed", "Radial"]
MIN_BANDS = {"All addresses": None, "Medium risk and above": "medium", "High risk only": "high"}
DEFAULTS = {
    "gx_hops": 1,
    "gx_per_side": 12,
    "gx_layout": LAYOUTS[0],
    "gx_minband": "All addresses",
    "gx_labels": False,
}

EDGE_COLOR = "rgba(150,165,185,0.55)"
EDGE_DIM = "rgba(150,165,185,0.22)"

_PAGE_CSS = """
<style>
.block-container { max-width: 1500px; }
.gx-intro { color: #8B98A9; margin: -0.4rem 0 1rem 0; font-size: 0.95rem; }
.gx-chip { display: inline-block; padding: 0.08rem 0.55rem; border-radius: 3px; font-size: 0.8rem;
           font-weight: 600; border: 1px solid; margin-right: 0.4rem; }
.gx-muted { color: #8B98A9; font-size: 0.85rem; }
.gx-panel-title { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em;
                  color: #8B98A9; margin: 0.6rem 0 0.2rem 0; }
</style>
"""


# --------------------------------------------------------------------------
# Pure helpers (no Streamlit calls - unit-testable)
# --------------------------------------------------------------------------
def fmt_time(ts):
    """Epoch seconds -> 'YYYY-MM-DD HH:MM UTC'. Other values are shown as given; empty -> None."""
    if ts in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OverflowError, OSError):
        return str(ts)


def _num(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def short_txid(t: str) -> str:
    return t if len(t) <= 18 else f"{t[:10]}...{t[-6:]}"


def edge_info(g, u, v) -> dict:
    """Everything the graph knows about the u -> v relationship (all parallel edges merged)."""
    data = g.get_edge_data(u, v) or {}
    txids = list(dict.fromkeys(d.get("txid") for d in data.values() if d.get("txid")))
    times = [d.get("block_time") for d in data.values() if d.get("block_time") not in (None, "")]
    return {
        "txids": txids,
        "tx_count": len(txids),
        "links": len(data),
        "btc": sum(_num(d.get("value_btc")) for d in data.values()),
        "times": times,
    }


def node_info(g, addr) -> dict:
    """Incoming / outgoing relationships of one address across the WHOLE graph."""
    preds, succs = list(dict.fromkeys(g.predecessors(addr))), list(dict.fromkeys(g.successors(addr)))
    in_edges = list(g.in_edges(addr, data=True))
    out_edges = list(g.out_edges(addr, data=True))
    txids = list(dict.fromkeys(d.get("txid") for _, _, d in in_edges + out_edges if d.get("txid")))
    times = [d.get("block_time") for _, _, d in in_edges + out_edges if d.get("block_time") not in (None, "")]
    return {
        "in_counterparties": preds, "out_counterparties": succs,
        "in_links": len(in_edges), "out_links": len(out_edges),
        "btc_in": sum(_num(d.get("value_btc")) for _, _, d in in_edges),
        "btc_out": sum(_num(d.get("value_btc")) for _, _, d in out_edges),
        "txids": txids, "times": times,
    }


def overview(g, risk_scores, analytics) -> dict:
    """Whole-graph statistics, all computed from the graph / pipeline output."""
    txids = {d.get("txid") for _, _, d in g.edges(data=True) if d.get("txid")}
    communities = {a.get("community") for a in (analytics or {}).values()
                   if isinstance(a, dict) and a.get("community") is not None}
    return {
        "nodes": g.number_of_nodes(),
        "edges": g.number_of_edges(),
        "pairs": len(set(g.edges())),
        "txs": len(txids),
        "high": sum(1 for n in g.nodes if (risk_scores.get(n) or {}).get("band") == "high"),
        "scored": sum(1 for n in g.nodes if n in risk_scores),
        "communities": len(communities) or None,
    }


def find_addresses(g, query: str, limit: int = 25) -> list:
    """Exact match first, then case-insensitive substring matches."""
    q = (query or "").strip()
    if not q:
        return []
    if q in g:
        return [q]
    ql = q.lower()
    return [n for n in g.nodes if isinstance(n, str) and ql in n.lower()][:limit]


def prepare_view(view: dict, risk_scores: dict, min_band: str = None) -> dict:
    """
    Copy of a build_focus_view() result where
      * addresses without a stored risk score are marked 'unscored' (graph_view would
        otherwise present them as 'low risk', which the data doesn't say), and
      * an optional minimum risk band hides the other neighbours (the centre stays).
    """
    nodes = []
    for n in view["nodes"]:
        n = dict(n)
        if n["address"] not in risk_scores:
            n["band"] = UNSCORED
        nodes.append(n)
    if min_band:
        need = BAND_RANK[min_band]
        nodes = [n for n in nodes if n["is_root"] or BAND_RANK.get(n["band"], -1) >= need]
    keep = {n["address"] for n in nodes}
    edges = [e for e in view["edges"] if e[0] in keep and e[1] in keep]
    total = view.get("total_nodes", len(nodes))
    return {"nodes": nodes, "edges": edges, "total_nodes": total, "hidden": total - len(nodes)}


def compute_positions(view: dict, layout: str) -> dict:
    nodes = view["nodes"]
    centre = next((n["address"] for n in nodes if n["is_root"]), None)
    if layout == LAYOUTS[0] or centre is None:
        return flow_positions(nodes)

    G = nx.Graph()
    G.add_nodes_from(n["address"] for n in nodes)
    G.add_edges_from((u, v) for u, v, _ in view["edges"])
    if layout == "Radial":
        others = [n["address"] for n in sorted(nodes, key=lambda n: (n["col"], -n["value"])) if not n["is_root"]]
        raw = nx.shell_layout(G, nlist=[[centre], others]) if others else {centre: (0.0, 0.0)}
        return {a: (float(x) * 6.5, float(y) * 3.6) for a, (x, y) in raw.items()}
    # Force-directed: centre pinned in the middle, fixed seed so the picture is stable between reruns.
    k = 2.4 / math.sqrt(max(G.number_of_nodes(), 1))
    raw = nx.spring_layout(G, k=k, seed=7, iterations=200, pos={centre: (0.0, 0.0)}, fixed=[centre])
    return {a: (float(x) * 6.5, float(y) * 3.6) for a, (x, y) in raw.items()}


def pattern_membership(patterns: dict, addr: str) -> dict:
    """{pattern_type: count} of detected patterns the address takes part in (same rules as the pipeline)."""
    out = {}
    for ptype, items in (patterns or {}).items():
        for it in items or []:
            if not isinstance(it, dict):
                continue
            if ptype in ("fan_out", "fan_in"):
                members = {it.get("address")}
            else:
                members = set(it.get("path") or []) | set(it.get("cycle") or []) | set(it.get("addresses") or [])
            if addr in members:
                out[ptype] = out.get(ptype, 0) + 1
    return out


def cluster_size(clusters, addr) -> int:
    for c in clusters or []:
        if isinstance(c, dict) and addr in (c.get("members") or []):
            return int(c.get("size") or len(c["members"]))
    return 0


def view_bounds(pos: dict, layout: str):
    xs = [p[0] for p in pos.values()] or [0.0]
    ys = [p[1] for p in pos.values()] or [0.0]
    if layout == LAYOUTS[0]:
        return (min(xs) - 2.4, max(xs) + 2.4), (min(ys) - 0.9, max(ys) + 2.0)
    return (min(xs) - 2.4, max(xs) + 2.4), (min(ys) - 1.0, max(ys) + 1.0)


# --------------------------------------------------------------------------
# Saved investigations (read-only)
# --------------------------------------------------------------------------
def _chunks(items, n=400):
    items = list(items)
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _stored_transactions(seed_addresses, allowed, root, max_hops):
    """
    Normalised transactions from the shared transaction tables that can belong to an investigation:
    those touching the seed address(es) whose every addressed input/output is inside `allowed`
    (the investigation's own saved address set). Read-only.
    """
    if max_hops <= 1:
        txids = set(database.get_txs_for_address(root))
    else:
        txids = set()
        with database.get_conn() as conn:
            for ch in _chunks(seed_addresses):
                q = ",".join("?" * len(ch))
                txids |= {r[0] for r in conn.execute(
                    f"SELECT txid FROM tx_inputs WHERE address IN ({q}) "
                    f"UNION SELECT txid FROM tx_outputs WHERE address IN ({q})", ch + ch)}
    ins, outs, times = {}, {}, {}
    with database.get_conn() as conn:
        for ch in _chunks(txids):
            q = ",".join("?" * len(ch))
            for r in conn.execute(f"SELECT txid, address, value_btc FROM tx_inputs WHERE txid IN ({q}) "
                                  f"ORDER BY txid, vin_index", ch):
                ins.setdefault(r["txid"], []).append({"address": r["address"], "value_btc": _num(r["value_btc"])})
            for r in conn.execute(f"SELECT txid, address, value_btc, is_change FROM tx_outputs WHERE txid IN ({q}) "
                                  f"ORDER BY txid, vout_index", ch):
                outs.setdefault(r["txid"], []).append({"address": r["address"], "value_btc": _num(r["value_btc"]),
                                                       "is_change": bool(r["is_change"])})
            for r in conn.execute(f"SELECT txid, block_time FROM transactions WHERE txid IN ({q})", ch):
                times[r["txid"]] = r["block_time"]
    txs = []
    for txid in sorted(txids):
        i_list, o_list = ins.get(txid, []), outs.get(txid, [])
        addrs = {a["address"] for a in i_list + o_list if a["address"]}
        if addrs and addrs <= allowed:
            txs.append({"txid": txid, "block_time": times.get(txid), "inputs": i_list, "outputs": o_list})
    return txs


def reconstruct_saved_investigation(inv_id):
    """
    Rebuild a graph result for a saved investigation from stored records only.
    Returns (result, None) on success or (None, problem_text).

    Stored per investigation: the scored address set (risk_scores), patterns, clusters, hops and,
    for investigations run after the investigation_transactions table existed, the exact transactions
    analysed (used as-is). Legacy investigations have no such record: their transactions are inferred
    from the shared tables. Either way the result is accepted only if the graph contains exactly the
    investigation's saved addresses. Otherwise nothing is drawn.
    """
    from core import graph_builder
    from core.report_generator import result_from_database

    base = result_from_database(inv_id)
    if base is None:
        return None, "This investigation no longer exists in the database."
    nodes = set(base["risk_scores"])
    if not nodes:
        return None, "This investigation has no saved results (the run stopped before finishing)."
    root = base["root_address"]
    hops = int((base.get("meta") or {}).get("max_hops") or 1)
    exact = database.has_transaction_links(inv_id)
    if exact:   # recorded by the pipeline: exactly this investigation's own transactions
        txs = database.get_investigation_transactions(inv_id)
        for t in txs:
            for a in t["inputs"] + t["outputs"]:
                a["value_btc"] = _num(a.get("value_btc"))
    else:       # legacy investigation: no record of its transactions, infer (see docstring)
        txs = _stored_transactions(sorted(nodes), nodes, root, hops)
    if not txs:
        return None, ("No stored transactions were found for this investigation's addresses, so its graph "
                      "cannot be rebuilt.")
    g = graph_builder.build_flow_graph(txs)
    missing = nodes - set(g.nodes) - {root}
    if missing:
        return None, (f"{len(missing)} of this investigation's {len(nodes)} saved addresses do not appear in the "
                      f"stored transactions, so its graph cannot be rebuilt faithfully. Nothing is drawn rather "
                      f"than showing an incomplete or different graph.")
    result = dict(base)
    result.update({"graph": g, "txs": txs, "analytics": {}, "stored_only": False,
                   "meta": {"max_hops": hops, "txs_analysed": len(txs), "reconstructed": True,
                            "exact_links": exact}})
    return result, None


@st.cache_data(show_spinner=False, max_entries=6)
def _load_saved(inv_id, db_signature):
    # db_signature only exists to invalidate the cache when the database file changes
    return reconstruct_saved_investigation(inv_id)


def db_signature():
    try:
        st_ = os.stat(config.DB_PATH)
        return (str(config.DB_PATH), st_.st_mtime_ns, st_.st_size)
    except OSError:
        return (str(config.DB_PATH), 0, 0)


def list_saved_investigations():
    """(summaries newest first, error text). A missing database file means 'no history yet'."""
    if not Path(config.DB_PATH).exists():
        return [], None
    try:
        return database.get_investigation_summaries(), None
    except Exception as exc:
        return [], str(exc)


# --------------------------------------------------------------------------
# Figure
# --------------------------------------------------------------------------
def build_figure(g, view, pos, layout, centre, root, selected, label_all, chart_key):
    import plotly.graph_objects as go

    nodes, edges = view["nodes"], view["edges"]
    max_val = max([n["value"] for n in nodes] + [1e-9])
    max_edge = max([v for _, _, v in edges] + [1e-9])
    top_labeled = {n["address"] for n in sorted(nodes, key=lambda n: n["value"], reverse=True)[:5]}
    fig = go.Figure()

    # ---- edges: arrows (direction + thickness = BTC) and hoverable midpoints ----
    mx, my, mhover, mcolor = [], [], [], []
    for u, v, val in edges:
        (x0, y0), (x1, y1) = pos[u], pos[v]
        hi = selected in (u, v)
        dim = selected is not None and not hi
        info = edge_info(g, u, v)
        width = 0.8 + 3.2 * math.sqrt(val / max_edge) + (1.0 if hi else 0.0)
        color = ACCENT if hi else (EDGE_DIM if dim else EDGE_COLOR)
        fig.add_annotation(x=x1, y=y1, ax=x0, ay=y0, xref="x", yref="y", axref="x", ayref="y",
                           showarrow=True, arrowhead=3, arrowsize=1.1, arrowwidth=width,
                           arrowcolor=color, standoff=13, startstandoff=13)
        tx_line = ""
        if info["txids"]:
            shown = ", ".join(short_txid(t) for t in info["txids"][:2])
            more = f" (+{len(info['txids']) - 2} more)" if len(info["txids"]) > 2 else ""
            tx_line = f"<br>Txid: {shown}{more}"
        when = fmt_time(max(info["times"], key=_num)) if info["times"] else None
        mx.append((x0 + x1) / 2)
        my.append((y0 + y1) / 2)
        mcolor.append(ACCENT if hi else "#8B98A9")
        mhover.append(f"<b>{short(u)} &#8594; {short(v)}</b><br>BTC on link: {val:.6f}"
                      f"<br>Transactions: {info['tx_count']}{tx_line}"
                      + (f"<br>Latest: {when}" if when else ""))
    if edges:
        fig.add_trace(go.Scatter(
            x=mx, y=my, mode="markers", name="Fund-flow link", showlegend=False,
            hovertext=mhover, hoverinfo="text",
            marker=dict(size=7, symbol="diamond", color=mcolor, line=dict(width=0)),
        ))

    # ---- nodes, one trace per risk band (legend entries toggle a band on/off) ----
    centre_name = "Investigated address" if centre == root else "Focus address"
    for band in BAND_ORDER:
        for is_centre in (True, False):
            sel = [n for n in nodes if n["band"] == band and n["is_root"] == is_centre]
            if not sel:
                continue
            labels, tpos, hover, size = [], [], [], []
            for n in sel:
                a = n["address"]
                important = band in ("high", "medium") or a in top_labeled or a == selected
                if is_centre:
                    labels.append(f"<b>{short(a)}</b>")
                    tpos.append("top center")
                else:
                    labels.append(short(a) if (label_all or important) else "")
                    left = (n["col"] < 0) if layout == LAYOUTS[0] else (pos[a][0] < pos[centre][0])
                    tpos.append("middle left" if left else "middle right")
                size.append(34 if is_centre else 12 + 20 * math.log1p(n["value"]) / math.log1p(max_val))
                role = (centre_name if is_centre
                        else "Sent funds toward the centre address" if n["col"] < 0
                        else "Received funds from the centre address")
                score_txt = ("No risk score stored" if band == UNSCORED
                             else f"Risk score: {n['score']} ({n['band']})")
                hover.append(
                    f"<b>{html.escape(a)}</b><br>{role}<br>BTC on shown links: {n['value']:.4f}"
                    f"<br>{score_txt}<br>Links in whole graph: {g.in_degree(a)} in / {g.out_degree(a)} out"
                    + (f"<br>Signals: {html.escape(', '.join(n['signals']))}" if n["signals"] else "")
                    + (f"<br>Attribution: {html.escape(', '.join(n['entities']))}" if n["entities"] else ""))
            fig.add_trace(go.Scatter(
                x=[pos[n["address"]][0] for n in sel], y=[pos[n["address"]][1] for n in sel],
                mode="markers+text", text=labels, textposition=tpos,
                textfont=dict(size=11, color="#C9D4E0"),
                name=(f"{centre_name} ({BAND_LABELS[band].lower()})" if is_centre else BAND_LABELS[band]),
                customdata=[n["address"] for n in sel],
                hovertext=hover, hoverinfo="text",
                marker=dict(size=size, color=BAND_COLORS[band], symbol="diamond" if is_centre else "circle",
                            line=dict(width=3 if is_centre else 1, color="#FFFFFF" if is_centre else "#0D1117")),
                selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=1)),
            ))

    # ---- ring around the selected address ----
    if selected in pos:
        sn = next((n for n in nodes if n["address"] == selected), None)
        ring = (34 if sn and sn["is_root"] else 14 + (20 * math.log1p(sn["value"]) / math.log1p(max_val) if sn else 8)) + 12
        fig.add_trace(go.Scatter(
            x=[pos[selected][0]], y=[pos[selected][1]], mode="markers", showlegend=False, hoverinfo="skip",
            marker=dict(size=ring, symbol="circle-open", color="#FFFFFF", line=dict(width=3, color="#FFFFFF")),
        ))

    # ---- column headers (flow layout only) ----
    xr, yr = view_bounds(pos, layout)
    if layout == LAYOUTS[0]:
        cols = sorted({n["col"] for n in nodes})
        top_y = max(p[1] for p in pos.values()) + 1.4
        for c in cols:
            if c == 0:
                text = f"{centre_name}<br>{short(centre)}"
            elif c < 0:
                text = "Funds came from" + (f" (hop {abs(c)})" if len(cols) > 3 else "")
            else:
                text = "Funds went to" + (f" (hop {c})" if len(cols) > 3 else "")
            fig.add_annotation(x=c * X_STEP, y=top_y, text=text.upper(), showarrow=False,
                               font=dict(size=11, color="#8B98A9"))
        tallest = max(sum(1 for n in nodes if n["col"] == c) for c in cols)
        height = max(580, 36 * tallest + 200)
    else:
        height = 660

    fig.update_layout(
        height=height, margin=dict(l=6, r=6, t=40, b=6),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#C9D4E0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, bgcolor="rgba(0,0,0,0)", font=dict(size=12)),
        hoverlabel=dict(bgcolor="#151B23", font_color="#E6EDF3", align="left"),
        xaxis=dict(visible=False, range=list(xr)), yaxis=dict(visible=False, range=list(yr)),
        dragmode="pan", clickmode="event+select", hovermode="closest",
        uirevision=chart_key,  # same key = keep the user's zoom; new key (Fit / new settings) = refit
    )
    return fig


def render_chart(fig, chart_key):
    """Draw the figure; returns the selection event (or None if this Streamlit build can't give one)."""
    cfg = {"scrollZoom": True, "displaylogo": False, "responsive": True,
           "modeBarButtonsToRemove": ["lasso2d", "select2d"],
           "toImageButtonOptions": {"filename": "bittrace_graph", "format": "png", "scale": 2}}
    try:
        return st.plotly_chart(fig, key=chart_key, on_select="rerun", selection_mode="points",
                               width="stretch", config=cfg)
    except TypeError:   # older Streamlit: no click-selection support
        try:
            st.plotly_chart(fig, width="stretch", config=cfg)
        except TypeError:
            st.plotly_chart(fig, use_container_width=True)
        return None


def clicked_address(event, g):
    try:
        points = (event.get("selection") or {}).get("points") or []
    except Exception:
        return None
    for p in points:
        cd = p.get("customdata")
        if isinstance(cd, (list, tuple)):
            cd = cd[0] if cd else None
        if isinstance(cd, str) and cd in g:
            return cd
    return None


# --------------------------------------------------------------------------
# State callbacks
# --------------------------------------------------------------------------
def cb_fit():
    st.session_state["gx_fit"] = st.session_state.get("gx_fit", 0) + 1


def cb_reset():
    for k, v in DEFAULTS.items():
        st.session_state[k] = v
    st.session_state["gx_search"] = ""
    st.session_state["gx_last_search"] = ""
    st.session_state["gx_selected"] = None
    st.session_state["gx_focus"] = None
    st.session_state.pop("gx_match_pick", None)
    cb_fit()


def cb_focus(addr):
    st.session_state["gx_focus"] = addr
    st.session_state["gx_selected"] = addr


def cb_unfocus():
    st.session_state["gx_focus"] = None


def cb_clear_selection():
    st.session_state["gx_selected"] = None


def cb_pick():
    st.session_state["gx_selected"] = st.session_state.get("gx_pick")


def cb_match_pick():
    st.session_state["gx_selected"] = st.session_state.get("gx_match_pick")


# --------------------------------------------------------------------------
# Details panel
# --------------------------------------------------------------------------
def _chip(text, color):
    c, t = html.escape(color), html.escape(text)
    return f'<span class="gx-chip" style="color:{c};border-color:{c}">{t}</span>'


def render_details(g, addr, role, root, risk_scores, entity_map, analytics, clusters, patterns):
    info = node_info(g, addr)
    st.markdown('<div class="gx-panel-title">Full address</div>', unsafe_allow_html=True)
    try:
        st.code(addr, language=None, wrap_lines=True)
    except TypeError:
        st.code(addr, language=None)
    st.markdown(_chip(role, ACCENT) if role else "", unsafe_allow_html=True)

    rs = risk_scores.get(addr)
    st.markdown('<div class="gx-panel-title">Risk assessment</div>', unsafe_allow_html=True)
    if rs:
        band = rs.get("band", "low")
        st.markdown(_chip(f"{BAND_LABELS.get(band, band)} - score {rs.get('score', 0)}",
                          BAND_COLORS.get(band, "#6B7686")), unsafe_allow_html=True)
        breakdown = rs.get("breakdown") or []
        if breakdown:
            for b in breakdown:
                st.markdown(f"- **+{b.get('points', 0)}** `{b.get('signal', '?')}` - {b.get('reason', '')}")
        else:
            st.caption("No risk signals fired for this address.")
    else:
        st.caption("No risk score is stored for this address, so nothing is claimed about its risk.")

    ents = entity_map.get(addr) or []
    if ents:
        st.markdown('<div class="gx-panel-title">Attribution</div>', unsafe_allow_html=True)
        for a in ents:
            conf = a.get("confidence")
            conf_txt = f", confidence {float(conf):.0%}" if isinstance(conf, (int, float)) else ""
            st.markdown(f"- **{str(a.get('entity_type', 'unknown')).replace('_', ' ')}** "
                        f"({str(a.get('method', '')).replace('_', ' ')}{conf_txt}) - {a.get('detail', '')}")

    st.markdown('<div class="gx-panel-title">Relationships (whole graph)</div>', unsafe_allow_html=True)
    metric_cards([
        ("Incoming", len(info["in_counterparties"]), f"{info['in_links']} links"),
        ("Outgoing", len(info["out_counterparties"]), f"{info['out_links']} links"),
        ("Transactions", len(info["txids"]), "touching this address"),
    ])
    st.caption(f"BTC on links: {info['btc_in']:.6f} in, {info['btc_out']:.6f} out "
               f"(each transaction's value is split across input/output pairs).")
    if info["times"]:
        first, last = fmt_time(min(info["times"], key=_num)), fmt_time(max(info["times"], key=_num))
        st.caption(f"Activity in analysed transactions: {first} to {last}")

    extra = []
    comm = (analytics.get(addr) or {}).get("community") if isinstance(analytics, dict) else None
    if comm is not None:
        extra.append(f"Community {comm} (graph analytics)")
    cs = cluster_size(clusters, addr)
    if cs > 1:
        extra.append(f"In an address cluster of {cs} (common-input / change heuristic)")
    pm = pattern_membership(patterns, addr)
    if pm:
        extra.append("Detected patterns: " + ", ".join(f"{k.replace('_', ' ')} x{v}" for k, v in pm.items()))
    for line in extra:
        st.markdown(f"- {line}")

    if info["in_counterparties"] or info["out_counterparties"]:
        rows = []
        for direction, cps in (("Incoming from", info["in_counterparties"]), ("Outgoing to", info["out_counterparties"])):
            for cp in cps:
                e = edge_info(g, cp, addr) if direction == "Incoming from" else edge_info(g, addr, cp)
                rows.append({"Direction": direction, "Address": cp, "BTC": round(e["btc"], 6),
                             "Transactions": e["tx_count"]})
        rows.sort(key=lambda r: r["BTC"], reverse=True)
        with st.expander(f"Counterparties ({len(rows)})"):
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    if info["txids"]:
        with st.expander(f"Related transaction IDs ({len(info['txids'])})"):
            st.code("\n".join(info["txids"][:100]), language=None)
            if len(info["txids"]) > 100:
                st.caption(f"First 100 of {len(info['txids'])} shown.")


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="Graph Explorer - BitTrace", layout="wide")
    apply_theme()
    st.markdown(_PAGE_CSS, unsafe_allow_html=True)
    st.title("Graph Explorer")
    st.markdown(
        '<div class="gx-intro">Visualises how funds moved between Bitcoin addresses. Each node is an address, '
        'each arrow is a fund-flow relationship derived from the transactions BitTrace analysed. '
        'Click an address for its full details.</div>', unsafe_allow_html=True)

    # ---- choose the investigation ----------------------------------------
    live = st.session_state.get("last_result")
    summaries, db_error = list_saved_investigations()
    origin, created_at = "session", None
    if db_error:
        st.warning(f"Saved investigations could not be read ({db_error}). Showing the investigation open in "
                   f"this session, if there is one.")
        result = live
    elif not summaries:
        st.info("No investigations are saved yet. Run one on the **Investigate** page and it will appear here.")
        try:
            st.page_link("pages/1_Investigate.py", label="Go to Investigate")
        except Exception:
            pass
        st.stop()
    else:
        by_id = {s_["id"]: s_ for s_ in summaries}
        done = [s_["id"] for s_ in summaries if investigation_status(s_) == "Completed"]
        latest_id = max(done) if done else None

        def _fmt(choice):
            if choice == "latest":
                return (f"Latest investigation (#{latest_id})" if latest_id is not None
                        else "Latest investigation (none completed yet)")
            row = by_id[choice]
            return investigation_label(row) + ("" if investigation_status(row) == "Completed" else "  (incomplete)")

        choice = st.selectbox("Investigation", ["latest"] + [s_["id"] for s_ in summaries],
                              key="gxsel_investigation", format_func=_fmt,
                              help="Pick any saved investigation. Each one shows its own graph and statistics.")
        inv_id = latest_id if choice == "latest" else choice
        if inv_id is None:
            st.warning("None of the saved investigations finished, so there is no graph to show yet.")
            st.stop()
        row = by_id[inv_id]
        created_at = row.get("created_at")
        if investigation_status(row) != "Completed":
            st.warning(f"Investigation #{inv_id} stopped before finishing, so no results were saved for it.")
            st.stop()
        if live and live.get("investigation_id") == inv_id:
            result = live                         # open in this session: complete, exact data
        else:
            origin = "saved"
            with st.spinner(f"Loading investigation #{inv_id}..."):
                result, problem = _load_saved(inv_id, db_signature())
            if problem:
                st.warning(f"Investigation #{inv_id} (`{row['root_address']}`): {problem}")
                st.stop()

    if not result:
        st.info("Run an investigation on the **Investigate** page first, then come back here.")
        try:
            st.page_link("pages/1_Investigate.py", label="Go to Investigate")
        except Exception:
            pass
        st.stop()

    g = result.get("graph")
    root = result.get("root_address")
    if not isinstance(g, nx.Graph):
        st.error("This investigation has no usable graph data. Run the investigation again on the "
                 "**Investigate** page.")
        st.stop()
    risk_scores = result.get("risk_scores") or {}
    entity_map = result.get("entity_map") or {}
    analytics = result.get("analytics") or {}
    clusters = result.get("clusters") or []
    patterns = result.get("patterns") or {}
    meta = result.get("meta") or {}

    when = f"  |  {str(created_at)[:16]} UTC" if created_at else ""
    st.caption(f"Viewing investigation #{result.get('investigation_id', '?')}  |  investigated address: "
               f"`{root}`{when}")
    if origin == "saved" and meta.get("exact_links"):
        st.info("Loaded from the transactions recorded for this investigation (no other investigation's "
                "transactions are included). Graph analytics (communities) were not saved and are not shown.")
    elif origin == "saved":
        extra = (" This run traced more than one hop, so transactions saved by other investigations that "
                 "connect these same addresses may add extra links." if meta.get("max_hops", 1) > 1 else "")
        st.info("Rebuilt from saved records. This investigation was saved before BitTrace recorded which "
                "transactions each run analysed, so the links come from the shared transaction store; the set "
                "of addresses was checked and matches this investigation's saved risk scores exactly." + extra +
                " Graph analytics (communities) were not saved and are not shown.")

    # a different investigation = a clean slate for this page's own state
    sig = (result.get("investigation_id"), root)
    if st.session_state.get("gx_sig") != sig:
        for k in [k for k in st.session_state.keys() if str(k).startswith("gx_")]:
            del st.session_state[k]
        st.session_state["gx_sig"] = sig
    for k, v in DEFAULTS.items():
        st.session_state.setdefault(k, v)
    for k, v in (("gx_selected", None), ("gx_focus", None), ("gx_fit", 0),
                 ("gx_last_search", ""), ("gx_last_chart_sel", None)):
        st.session_state.setdefault(k, v)

    # ---- empty-data states ---------------------------------------------
    stats = overview(g, risk_scores, analytics)
    if stats["nodes"] == 0:
        st.warning("This investigation produced no graph data: no addresses were found in the transactions "
                   "BitTrace analysed.")
        st.stop()

    centre = st.session_state["gx_focus"] or root
    centre_note = None
    if centre not in g:
        centre = root
    if centre not in g:
        centre = max(g.nodes, key=lambda n: g.degree(n))
        centre_note = ("The investigated address does not appear in the transaction graph, so the graph is "
                       "centred on its busiest address instead.")
    selected = st.session_state["gx_selected"]
    if selected is not None and selected not in g:
        selected = st.session_state["gx_selected"] = None

    # ---- statistic cards ---------------------------------------------------
    cards_slot = st.container()

    if stats["edges"] == 0:
        with cards_slot:
            metric_cards([("Addresses (nodes)", f"{stats['nodes']:,}"), ("Relationships (edges)", "0")])
        st.warning("This investigation has addresses but no fund-flow relationships between them, so there is "
                   "no graph to draw.")
        st.stop()

    # ---- controls -----------------------------------------------------------
    with st.container(border=True):
        c1, c2, c3, c4, c5 = st.columns([2.4, 0.9, 1.4, 1.5, 1.6], vertical_alignment="bottom")
        query = c1.text_input("Search address in this graph", key="gx_search",
                              placeholder="Paste a full or partial Bitcoin address").strip()
        hops = c2.selectbox("Hops", [1, 2], key="gx_hops",
                            help="1 = addresses that transacted directly with the centre address.")
        per_side = c3.slider("Addresses per side", 5, 40, key="gx_per_side",
                             help="Keeps the highest-risk / highest-value addresses on each side and hides the rest.")
        layout = c4.selectbox("Layout", LAYOUTS, key="gx_layout",
                              help="Flow separates senders / receivers. Force-directed and Radial spread nodes out.")
        min_band_label = c5.selectbox("Show", list(MIN_BANDS), key="gx_minband",
                                      help="Hide lower-risk neighbours. The centre address is always shown.")

        b1, b2, b3, b4, b5 = st.columns([1.2, 0.9, 1.1, 1.7, 1.7], vertical_alignment="center")
        label_all = b1.checkbox("Label every address", key="gx_labels")
        b2.button("Fit graph", on_click=cb_fit, width="stretch",
                  help="Re-fit the whole graph to the window (undo zoom and pan).")
        b3.button("Reset filters", on_click=cb_reset, width="stretch",
                  help="Restore default settings, clear search, selection and re-centre.")
        b4.button("Centre on selected", on_click=cb_focus, args=(selected,), width="stretch",
                  disabled=selected is None or selected == centre,
                  help="Rebuild the graph around the selected address.")
        b5.button("Back to investigated address", on_click=cb_unfocus, width="stretch",
                  disabled=centre == root)

    feedback = st.container()

    # ---- search ------------------------------------------------------------
    matches = find_addresses(g, query)
    if query:
        if not matches:
            safe_q = query.replace("`", "'")[:60]
            feedback.warning(f"No address in this graph matches \"{safe_q}\". Check the text, or try fewer "
                             f"characters. Only addresses from the analysed transactions are searchable.")
        else:
            if query != st.session_state["gx_last_search"]:
                st.session_state["gx_last_search"] = query
                st.session_state["gx_selected"] = selected = matches[0]
            if len(matches) > 1:
                st.session_state["gx_match_pick"] = selected if selected in matches else matches[0]
                feedback.selectbox(f"{len(matches)} addresses match - pick one", matches, key="gx_match_pick",
                                   format_func=short, on_change=cb_match_pick)
    else:
        st.session_state["gx_last_search"] = ""

    # ---- build the view --------------------------------------------------------
    try:
        raw_view = build_focus_view(g, centre, risk_scores, entity_map, depth=hops, max_per_side=per_side)
        view = prepare_view(raw_view, risk_scores, MIN_BANDS[min_band_label])
    except Exception as exc:
        st.error(f"The graph could not be prepared from this investigation's data: {exc}")
        with st.expander("Technical details"):
            st.code(traceback.format_exc())
        st.stop()

    in_view = {n["address"] for n in view["nodes"]}
    with cards_slot:
        metric_cards([
            ("Addresses (nodes)", f"{stats['nodes']:,}", "in whole graph"),
            ("Relationships (edges)", f"{stats['edges']:,}", f"{stats['pairs']:,} distinct address pairs"),
            ("Transactions", f"{stats['txs']:,}", "with fund-flow links"),
            ("In current view", f"{len(view['nodes'])} / {stats['nodes']}", f"{len(view['edges'])} links shown"),
            ("High-risk addresses", f"{stats['high']:,}", f"{stats['scored']:,} addresses scored",
             BAND_COLORS["high"] if stats["high"] else None),
            ("Communities", f"{stats['communities']:,}" if stats["communities"] else "n/a",
             "from graph analytics" if stats["communities"] else "not available"),
            ("Selected address", short(selected) if selected else "None",
             (BAND_LABELS[risk_scores[selected]["band"]] if selected in risk_scores and risk_scores[selected].get("band") in BAND_LABELS
              else "no risk data") if selected else "click a node",
             BAND_COLORS.get((risk_scores.get(selected) or {}).get("band"), None) if selected else None),
        ])

    if centre_note:
        st.info(centre_note)
    if selected and selected not in in_view and query and selected in matches:
        feedback.info("That address is in the graph but not drawn with the current Hops / Addresses per side / "
                      "Show settings. Use **Centre on selected** to rebuild the graph around it.")

    # ---- graph + details ---------------------------------------------------------
    fig_sig = (centre, hops, per_side, layout, min_band_label, st.session_state["gx_fit"])
    chart_key = "gx_chart_" + hashlib.md5(repr(fig_sig).encode()).hexdigest()[:10]

    if len(view["nodes"]) <= 1:
        if len(raw_view["nodes"]) > 1:
            st.warning("The current risk filter hides every neighbour of this address. Choose "
                       "**All addresses** under *Show*.")
        else:
            st.warning("No direct fund flow was found around this address in the transactions analysed.")
    else:
        left, right = st.columns([2.25, 1], gap="medium")
        with left:
            try:
                pos = compute_positions(view, layout)
                fig = build_figure(g, view, pos, layout, centre, root, selected, label_all, chart_key)
                event = render_chart(fig, chart_key)
            except Exception as exc:
                event = None
                st.error(f"The interactive graph could not be drawn ({exc}). The tables below still show "
                         f"the same data.")
                with st.expander("Technical details"):
                    st.code(traceback.format_exc())
            st.caption(
                f"Showing {len(view['nodes'])} of {view['total_nodes']} addresses. Hidden addresses are indirect "
                f"(they share transactions with the centre address but are not directly connected to it), or fall "
                f"outside the per-side limit / risk filter. Scroll to zoom, drag to pan, click an address to select it.")

        # a new click on the graph selects that address (re-run once so highlights refresh)
        clicked = clicked_address(event, g) if event is not None else None
        if clicked is None:
            st.session_state["gx_last_chart_sel"] = None
        elif clicked != st.session_state["gx_last_chart_sel"]:
            st.session_state["gx_last_chart_sel"] = clicked
            if clicked != selected:
                st.session_state["gx_selected"] = clicked
                st.rerun()

        with right:
            st.subheader("Address details")
            ordered = [n["address"] for n in sorted(view["nodes"], key=lambda n: (n["is_root"], n["score"], n["value"]),
                                                     reverse=True)]
            options = [None] + list(dict.fromkeys(([selected] if selected else []) + ordered))
            st.session_state["gx_pick"] = selected
            st.selectbox("Inspect address", options, key="gx_pick", on_change=cb_pick,
                         format_func=lambda a: "No address selected" if a is None else
                         (short(a) + ("  (centre)" if a == centre else "")))
            if selected is None:
                st.caption("Click a node in the graph, or pick an address above, to see its full address, "
                           "risk findings, related transactions and counterparties.")
            else:
                if selected == root:
                    role = "Investigated address"
                elif selected == centre:
                    role = "Focus address"
                else:
                    node = next((n for n in view["nodes"] if n["address"] == selected), None)
                    role = ("Not drawn in the current view" if node is None
                            else "Sent funds toward the centre address" if node["col"] < 0
                            else "Received funds from the centre address")
                render_details(g, selected, role, root, risk_scores, entity_map, analytics, clusters, patterns)
                st.button("Clear selection", on_click=cb_clear_selection, key="gx_clear_btn")

    if meta.get("root_tx_total") and meta.get("root_tx_fetched") and meta["root_tx_fetched"] < meta["root_tx_total"]:
        st.info(f"This address has {meta['root_tx_total']:,} transactions on-chain. BitTrace analysed the "
                f"most recent {meta['root_tx_fetched']:,}, so the graph is a sample, not the full history.")

    with st.expander("How to read this graph"):
        st.markdown(
            "- **Nodes are addresses.** Colour is the risk band (red high, amber medium, green low, grey = no risk "
            "data stored); size is how much BTC moved on the links shown. The diamond is the centre address.\n"
            "- **Arrows are fund flow** from sender to receiver. Thicker arrows carry more BTC. The small diamond "
            "on each arrow shows its transaction IDs, BTC and transaction count on hover.\n"
            "- **Flow layout:** senders on the left, receivers on the right. Force-directed and Radial spread "
            "addresses out instead.\n"
            "- **Click an address** (or search above) to see its full text, risk signals and transactions. "
            "*Centre on selected* rebuilds the graph around it.\n"
            "- Click a name in the legend to hide or show a risk band. Use the toolbar on the graph or "
            "**Fit graph** to reset the zoom.\n"
            "- BTC amounts on links split each transaction across its input/output pairs, so they are "
            "estimates, not exact per-address transfers.")

    # ---- tables (same data as the graph, plus the original patterns listing) -----------
    tab_addr, tab_edges, tab_pat = st.tabs(["Addresses shown", "Relationships shown", "Detected patterns"])
    with tab_addr:
        rows = []
        for n in sorted(view["nodes"], key=lambda n: (n["score"], n["value"]), reverse=True):
            rows.append({
                "Address": n["address"],
                "Role": ("Investigated" if n["address"] == root else "Focus") if n["is_root"]
                        else ("Sent to centre" if n["col"] < 0 else "Received from centre"),
                "BTC on links": round(n["value"], 6),
                "Risk score": n["score"] if n["band"] != UNSCORED else None,
                "Band": BAND_LABELS[n["band"]],
                "Signals": ", ".join(n["signals"]) or "-",
                "Attribution": ", ".join(n["entities"]) or "-",
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        else:
            st.caption("No addresses to list.")
    with tab_edges:
        rows = []
        for u, v, val in sorted(view["edges"], key=lambda e: e[2], reverse=True):
            e = edge_info(g, u, v)
            more = f" (+{e['tx_count'] - 3} more)" if e["tx_count"] > 3 else ""
            rows.append({"From": u, "To": v, "BTC": round(val, 6), "Transactions": e["tx_count"],
                         "Txids": ", ".join(short_txid(t) for t in e["txids"][:3]) + more if e["txids"] else "-"})
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        else:
            st.caption("No relationships to list.")
    with tab_pat:
        if not patterns:
            st.caption("No pattern results are available for this investigation.")
        for pattern_type, items in patterns.items():
            items = items or []
            st.write(f"**{pattern_type.replace('_', ' ').title()}** ({len(items)})")
            for it in items[:10]:
                members = it.get("path") or it.get("cycle") or it.get("addresses") or []
                hub = it.get("address") or ", ".join(short(a) for a in members[:4] if a)
                size = it.get("count") or len(members)
                st.markdown(f"- `{hub}` involving {size} addresses")
            if items:
                with st.expander(f"Raw data: {pattern_type}"):
                    st.json(items[:10])


if __name__ == "__main__":
    main()