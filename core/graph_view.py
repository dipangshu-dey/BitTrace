"""
BitTrace v2 - core/graph_view.py

Turns the full fund-flow graph (which can hold hundreds of addresses) into a
small, explainable picture: the investigated address in the centre, addresses
that sent it funds on the left, addresses it sent funds to on the right.

  build_focus_view()  - pure logic, no plotting (unit-tested)
  make_figure()       - Plotly figure for the dashboard
"""

import math
from typing import Dict, List

import networkx as nx

BAND_COLOR = {"high": "#d62728", "medium": "#ff9f1c", "low": "#2ca02c"}
BAND_LABEL = {"high": "High risk", "medium": "Medium risk", "low": "Low risk"}
X_STEP = 2.0


def short(addr: str) -> str:
    return addr if len(addr) <= 12 else f"{addr[:6]}...{addr[-4:]}"


def _edge_value(g, u, v) -> float:
    return sum((d.get("value_btc") or 0) for d in (g.get_edge_data(u, v) or {}).values())


def build_focus_view(g: nx.MultiDiGraph, root: str, risk_scores: dict, entity_map: dict = None,
                     depth: int = 1, max_per_side: int = 12) -> dict:
    """
    Column 0 = root, negative columns = upstream (funds came from), positive
    columns = downstream (funds went to). Within each column the highest-risk,
    highest-value addresses are kept and the rest are hidden.
    """
    entity_map = entity_map or {}
    if root not in g:
        return {"nodes": [], "edges": [], "total_nodes": g.number_of_nodes(), "hidden": g.number_of_nodes()}

    up = nx.single_source_shortest_path_length(g.reverse(copy=False), root, cutoff=depth)
    down = nx.single_source_shortest_path_length(g, root, cutoff=depth)
    up.pop(root, None)
    down.pop(root, None)

    def rank(n):
        return (risk_scores.get(n, {}).get("score", 0), g.degree(n, weight="value_btc"))

    col_of = {root: 0}
    for d in range(1, depth + 1):
        for side, dist in ((-1, up), (1, down)):
            cands = []
            for n, dn in dist.items():
                if dn != d or n in col_of:
                    continue
                other = down if side == -1 else up
                if other.get(n, 99) < dn:                  # closer on the other side: placed there
                    continue
                nbrs = g.successors(n) if side == -1 else g.predecessors(n)
                parent_ok = any(col_of.get(m) == side * (d - 1) for m in nbrs)
                if parent_ok:
                    cands.append(n)
            cands.sort(key=rank, reverse=True)
            for n in cands[:max_per_side]:
                col_of[n] = side * d

    edges = []
    for u, v in g.edges():
        if u in col_of and v in col_of and col_of[v] - col_of[u] == 1 and (col_of[u] >= 0 or col_of[v] <= 0):
            edges.append((u, v))
    edges = sorted(set(edges))
    edge_vals = {(u, v): _edge_value(g, u, v) for u, v in edges}

    nodes = []
    for n, col in col_of.items():
        rs = risk_scores.get(n, {})
        breakdown = rs.get("breakdown", [])
        ents = [f"{a['entity_type']} ({a['method'].replace('_', ' ')})" for a in entity_map.get(n, [])]
        touching = [edge_vals[e] for e in edges if n in e]
        nodes.append({
            "address": n, "col": col, "is_root": n == root,
            "value": sum(touching),
            "score": rs.get("score", 0), "band": rs.get("band", "low"),
            "signals": [b["signal"] for b in breakdown][:4],
            "entities": ents,
        })
    return {"nodes": nodes, "edges": [(u, v, edge_vals[(u, v)]) for u, v in edges],
            "total_nodes": g.number_of_nodes(), "hidden": g.number_of_nodes() - len(nodes)}


def _positions(nodes: List[dict]) -> Dict[str, tuple]:
    by_col: Dict[int, List[dict]] = {}
    for n in nodes:
        by_col.setdefault(n["col"], []).append(n)
    pos = {}
    for col, items in by_col.items():
        items.sort(key=lambda n: (n["is_root"], n["value"]), reverse=True)
        k = len(items)
        for i, n in enumerate(items):
            pos[n["address"]] = (col * X_STEP, (k - 1) / 2 - i)
    return pos


def make_figure(view: dict, show_all_labels: bool = False):
    import plotly.graph_objects as go

    nodes, edges = view["nodes"], view["edges"]
    pos = _positions(nodes)
    max_val = max([n["value"] for n in nodes] + [1e-9])
    max_edge = max([v for _, _, v in edges] + [1e-9])
    top_labeled = {n["address"] for n in sorted(nodes, key=lambda n: n["value"], reverse=True)[:5]}

    fig = go.Figure()

    for band in ("high", "medium", "low"):
        for is_root in (True, False):
            sel = [n for n in nodes if n["band"] == band and n["is_root"] == is_root]
            if not sel:
                continue
            if is_root:
                name = f"Investigated address ({BAND_LABEL[band].lower()})"
                size = [34] * len(sel)
            else:
                name = BAND_LABEL[band]
                size = [12 + 20 * math.log1p(n["value"]) / math.log1p(max_val) for n in sel]
            labels, tpos, hover = [], [], []
            for n in sel:
                label = "" if n["is_root"] else (short(n["address"]) if (show_all_labels or n["band"] != "low"
                                                or n["address"] in top_labeled) else "")
                labels.append(label)
                tpos.append("top center" if n["is_root"] else ("middle left" if n["col"] < 0 else "middle right"))
                role = ("Investigated address" if n["is_root"]
                        else "Sent funds toward the investigated address" if n["col"] < 0
                        else "Received funds from the investigated address")
                hover.append(
                    f"<b>{n['address']}</b><br>{role}<br>BTC on shown links: {n['value']:.4f}"
                    f"<br>Risk score: {n['score']} ({n['band']})"
                    + (f"<br>Signals: {', '.join(n['signals'])}" if n["signals"] else "")
                    + (f"<br>Attribution: {', '.join(n['entities'])}" if n["entities"] else ""))
            fig.add_trace(go.Scatter(
                x=[pos[n["address"]][0] for n in sel], y=[pos[n["address"]][1] for n in sel],
                mode="markers+text", name=name, text=labels, textposition=tpos,
                textfont=dict(size=11, color="#C9D4E0"),
                hovertext=hover, hoverinfo="text",
                marker=dict(size=size, color=BAND_COLOR[band], symbol="diamond" if is_root else "circle",
                            line=dict(width=3 if is_root else 1, color="#FFFFFF" if is_root else "#0D1117")),
            ))

    for u, v, val in edges:
        (x0, y0), (x1, y1) = pos[u], pos[v]
        fig.add_annotation(x=x1, y=y1, ax=x0, ay=y0, xref="x", yref="y", axref="x", ayref="y",
                           showarrow=True, arrowhead=3, arrowsize=1.1,
                           arrowwidth=0.8 + 3.2 * math.sqrt(val / max_edge),
                           arrowcolor="rgba(150,165,185,0.55)", standoff=12, startstandoff=12)

    root_addr = next((n["address"] for n in nodes if n["is_root"]), "")
    cols = sorted({n["col"] for n in nodes})
    top_y = max([p[1] for p in pos.values()] + [0]) + 1.4
    for c in cols:
        text = (f"Investigated address<br>{short(root_addr)}" if c == 0
                else "Funds came from" + (f" (hop {abs(c)})" if len(cols) > 3 else "") if c < 0
                else "Funds went to" + (f" (hop {c})" if len(cols) > 3 else ""))
        fig.add_annotation(x=c * X_STEP, y=top_y, text=text.upper().replace("<BR>", "<br>"), showarrow=False,
                           font=dict(size=11, color="#8B98A9"))

    tallest = max([sum(1 for n in nodes if n["col"] == c) for c in cols] + [1])
    fig.update_layout(
        height=max(480, 34 * tallest + 170),
        margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#C9D4E0"),
        legend=dict(orientation="h", y=-0.02, x=0),
        hoverlabel=dict(bgcolor="#151B23", font_color="#E6EDF3"),
        xaxis=dict(visible=False, range=[min(cols) * X_STEP - 2.4, max(cols) * X_STEP + 2.4]),
        yaxis=dict(visible=False, range=[-(tallest / 2) - 0.8, top_y + 0.6]),
    )
    return fig
