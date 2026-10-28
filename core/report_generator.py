"""
BitTrace v2 - core/report_generator.py

Exports an investigation result (the dict returned by pipeline.run_investigation)
to four formats:
  - JSON  : full machine-readable dump
  - CSV   : flat risk-score table, easy to open in Excel
  - PNG   : rendered fund-flow graph, flagged/high-risk addresses in red
  - PDF   : multi-page investigation report (see build_pdf_report)
"""

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape
import sys

import matplotlib
matplotlib.use("Agg")  # no display needed - we only ever save to file
import matplotlib.pyplot as plt
import networkx as nx
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config
from core.dashboard_data import timeline_frame


def export_json(result: dict, out_path: Optional[Path] = None) -> Path:
    out_path = out_path or config.REPORTS_DIR / f"investigation_{result['investigation_id']}.json"

    serializable = {
        "investigation_id": result["investigation_id"],
        "root_address": result["root_address"],
        "addresses": result["addresses"],
        "clusters": result["clusters"],
        "patterns": {
            k: v if k != "peel_chains" else [{"path": c["path"], "hops": c["hops"]} for c in v]
            for k, v in result["patterns"].items()
        },
        "risk_scores": result["risk_scores"],
        "entity_map": result["entity_map"],
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, default=str)
    return out_path


def export_csv(result: dict, out_path: Optional[Path] = None) -> Path:
    out_path = out_path or config.REPORTS_DIR / f"investigation_{result['investigation_id']}_risk_scores.csv"

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["address", "score", "band", "top_signal", "entity_types"])
        for addr, rs in result["risk_scores"].items():
            top_signal = rs["breakdown"][0]["signal"] if rs["breakdown"] else ""
            entity_types = ",".join(sorted({e["entity_type"] for e in result["entity_map"].get(addr, [])}))
            writer.writerow([addr, rs["score"], rs["band"], top_signal, entity_types])
    return out_path


def export_graph_png(result: dict, out_path: Optional[Path] = None) -> Path:
    out_path = out_path or config.REPORTS_DIR / f"investigation_{result['investigation_id']}_graph.png"

    g = result["graph"]
    risk_scores = result["risk_scores"]

    node_colors = []
    for n in g.nodes():
        band = risk_scores.get(n, {}).get("band", "low")
        node_colors.append({"high": "#d62728", "medium": "#ff9f1c", "low": "#2ca02c"}.get(band, "#7f7f7f"))

    plt.figure(figsize=(10, 8))
    pos = nx.spring_layout(g, seed=42, k=0.6)
    simple = nx.DiGraph(g)
    nx.draw_networkx_nodes(simple, pos, node_color=node_colors, node_size=500)
    nx.draw_networkx_edges(simple, pos, arrows=True, alpha=0.4)
    nx.draw_networkx_labels(simple, pos, font_size=7)
    plt.title(f"BitTrace fund-flow graph - investigation #{result['investigation_id']}\n"
              f"(red = high risk, orange = medium, green = low)")
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    return out_path


# ---------------------------------------------------------------------------
# PDF investigation report
#
#   build_pdf_report(result)  -> bytes   (used by the dashboard's download button)
#   export_pdf(result, ...)   -> Path    (unchanged signature; writes those bytes to disk)
#   result_from_database(id)  -> dict    (rebuilds a report-ready dict from stored records,
#                                         for investigations that are no longer in memory)
#
# Every section reads the pipeline's result dict defensively (.get with
# defaults), so a missing optional field gives a short "not available" note
# instead of a failed report. Nothing is invented: counts, times, scores and
# bands are copied from the result, and sections without data say so.
# ---------------------------------------------------------------------------
PAGE_W, PAGE_H = A4
MARGIN = 40
CONTENT_W = PAGE_W - 2 * MARGIN
MAX_TX_ROWS = 200
MAX_LIST_ROWS = 20

NAVY = colors.HexColor("#1F2A37")
TEAL = colors.HexColor("#0D7586")
GREY = colors.HexColor("#5B6775")
RULE = colors.HexColor("#C9D1D9")
ATTRIBUTION_GREY = colors.HexColor("#7A8594")   # light enough to stay unobtrusive, dark enough to print
DEVELOPER_ATTRIBUTION = "BitTrace \u2014 Bitcoin Transaction Forensics  \u00b7  Developed by Dipangshu Dey"
BAND_FILL = {"high": colors.HexColor("#F8D7DA"), "medium": colors.HexColor("#FFE8C2"),
             "low": colors.HexColor("#DDF0DD")}
BAND_HEX = {"high": "#d62728", "medium": "#ff9f1c", "low": "#2ca02c"}
RELATION_HEX = {"Outgoing": "#4DA3FF", "Incoming": "#B388FF", "Related": "#8B98A9"}
BAND_NAME = {"high": "High risk", "medium": "Medium risk", "low": "Low risk"}
PATTERN_KEYS = [  # (result key, label)
    ("fan_in", "Fan-in"), ("fan_out", "Fan-out"), ("coinjoin", "CoinJoin-like"),
    ("peel_chains", "Peel chain"), ("circular_flows", "Circular flow"),
]


def _register_fonts() -> tuple:
    """DejaVu fonts ship with matplotlib, so they are always installed here and
    cover accented characters and symbols in investigator notes. Falls back to
    the built-in PDF fonts if they cannot be found."""
    try:
        import matplotlib
        fdir = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        for name, file in (("BT-Sans", "DejaVuSans.ttf"), ("BT-Sans-Bold", "DejaVuSans-Bold.ttf"),
                           ("BT-Mono", "DejaVuSansMono.ttf")):
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(fdir / file)))
        pdfmetrics.registerFontFamily("BT-Sans", normal="BT-Sans", bold="BT-Sans-Bold",
                                      italic="BT-Sans", boldItalic="BT-Sans-Bold")
        return "BT-Sans", "BT-Sans-Bold", "BT-Mono"
    except Exception:
        return "Helvetica", "Helvetica-Bold", "Courier"


def _styles() -> dict:
    sans, bold, mono = _register_fonts()
    S = {}
    S["title"] = ParagraphStyle("t", fontName=bold, fontSize=21, leading=26, textColor=NAVY, spaceAfter=2)
    S["subtitle"] = ParagraphStyle("st", fontName=sans, fontSize=10, leading=14, textColor=GREY, spaceAfter=8)
    S["h1"] = ParagraphStyle("h1", fontName=bold, fontSize=12.5, leading=16, textColor=TEAL,
                             spaceBefore=14, spaceAfter=5, keepWithNext=1)
    S["h2"] = ParagraphStyle("h2", fontName=bold, fontSize=9.5, leading=13, textColor=NAVY,
                             spaceBefore=8, spaceAfter=3, keepWithNext=1)
    S["body"] = ParagraphStyle("b", fontName=sans, fontSize=8.8, leading=12.2, textColor=NAVY, spaceAfter=4)
    S["bullet"] = ParagraphStyle("bl", parent=S["body"], leftIndent=11, bulletIndent=1, spaceAfter=2.5)
    S["note"] = ParagraphStyle("n", fontName=sans, fontSize=7.6, leading=10.5, textColor=GREY, spaceAfter=4)
    S["cell"] = ParagraphStyle("c", fontName=sans, fontSize=7.6, leading=9.6, textColor=NAVY)
    S["cell_b"] = ParagraphStyle("cb", parent=S["cell"], fontName=bold)
    S["cell_r"] = ParagraphStyle("cr", parent=S["cell"], alignment=TA_RIGHT)
    S["cell_h"] = ParagraphStyle("ch", parent=S["cell"], fontName=bold, textColor=colors.white)
    S["cell_hr"] = ParagraphStyle("chr", parent=S["cell_h"], alignment=TA_RIGHT)
    S["mono"] = ParagraphStyle("m", fontName=mono, fontSize=6.7, leading=8.6, textColor=NAVY, wordWrap="CJK")
    S["caption"] = ParagraphStyle("cap", fontName=sans, fontSize=7.6, leading=10, textColor=GREY,
                                  alignment=TA_CENTER, spaceAfter=6)
    S["fonts"] = (sans, bold, mono)
    return S


def _esc(value) -> str:
    return escape("" if value is None else str(value))


def _p(text, style) -> Paragraph:
    return Paragraph(_esc(text), style)


def _fmt_score(v) -> str:
    try:
        return f"{float(v):g}"
    except (TypeError, ValueError):
        return "n/a"


def _pct(part: int, total: int) -> str:
    if not total:
        return "0%"
    pct = 100.0 * part / total
    return "<0.1%" if 0 < pct < 0.1 else f"{pct:.1f}%"


def _fmt_btc(v) -> str:
    try:
        return f"{float(v):,.8f}"
    except (TypeError, ValueError):
        return "n/a"


def _short(addr, head=8, tail=6) -> str:
    addr = "" if addr is None else str(addr)
    return addr if len(addr) <= head + tail + 3 else f"{addr[:head]}...{addr[-tail:]}"


def _band_ranges() -> dict:
    hi, med = config.RISK_BAND_HIGH, config.RISK_BAND_MEDIUM
    return {"low": f"0-{med - 1}", "medium": f"{med}-{hi - 1}", "high": f"{hi}-{config.RISK_SCORE_MAX}"}


def _table(rows, widths, S, header_rows=1, zebra=True, extra=None) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=header_rows)
    style = [
        ("BACKGROUND", (0, 0), (-1, header_rows - 1), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
    if zebra and len(rows) > header_rows + 1:
        style.append(("ROWBACKGROUNDS", (0, header_rows), (-1, -1), [colors.white, colors.HexColor("#F4F6F8")]))
    t.setStyle(TableStyle(style + (extra or [])))
    return t


# ---------------------------------------------------------------- charts
def _png(fig, width_pt: float) -> Image:
    """Render a matplotlib Figure to an in-memory PNG sized to width_pt."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from PIL import Image as PILImage
    FigureCanvasAgg(fig)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=170, facecolor="white", bbox_inches="tight", pad_inches=0.08)
    with PILImage.open(io.BytesIO(buf.getvalue())) as im:
        ratio = im.height / im.width
    buf.seek(0)
    return Image(buf, width=width_pt, height=width_pt * ratio)


def _chart_bands(counts: dict, width_pt: float):
    from matplotlib.figure import Figure
    total = sum(counts.values())
    fig = Figure(figsize=(7.0, 1.9))
    ax = fig.add_subplot(111)
    order = ["high", "medium", "low"]
    ranges = _band_ranges()
    labels = [f"{BAND_NAME[b]} ({ranges[b]})" for b in order]
    vals = [counts.get(b, 0) for b in order]
    ax.barh(labels, vals, color=[BAND_HEX[b] for b in order], height=0.55)
    ax.invert_yaxis()
    top = max(vals) if max(vals) else 1
    ax.set_xlim(0, top * 1.28)
    for i, v in enumerate(vals):
        ax.text(v + top * 0.015, i, f"{v:,}  ({_pct(v, total)})", va="center", fontsize=8.5, color="#1F2A37")
    ax.set_xlabel("Addresses", fontsize=8)
    ax.tick_params(labelsize=8.5)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.xaxis.set_major_locator(__import__("matplotlib.ticker", fromlist=["MaxNLocator"]).MaxNLocator(integer=True))
    return _png(fig, width_pt)


def _chart_patterns(patterns: dict, width_pt: float):
    from matplotlib.figure import Figure
    items = [(label, len(patterns.get(key) or [])) for key, label in PATTERN_KEYS]
    fig = Figure(figsize=(7.0, 2.1))
    ax = fig.add_subplot(111)
    palette = ["#3B9EBF", "#7B6FD0", "#D98E04", "#2E8B57", "#B5486B"]
    ax.barh([i[0] for i in items], [i[1] for i in items], color=palette, height=0.55)
    ax.invert_yaxis()
    top = max([i[1] for i in items] + [1])
    ax.set_xlim(0, top * 1.2)
    for i, (_, v) in enumerate(items):
        ax.text(v + top * 0.015, i, f"{v:,}", va="center", fontsize=8.5, color="#1F2A37")
    ax.set_xlabel("Detected instances", fontsize=8)
    ax.tick_params(labelsize=8.5)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    return _png(fig, width_pt)


def _chart_focus_graph(result: dict, width_pt: float):
    """Focus view of the investigated address (senders left, recipients right)."""
    from matplotlib.figure import Figure
    from matplotlib.patches import FancyArrowPatch
    from matplotlib.lines import Line2D
    from core.graph_view import build_focus_view
    g = result.get("graph")
    root = result.get("root_address")
    if g is None or root is None or root not in g:
        return None, None
    view = build_focus_view(g, root, result.get("risk_scores") or {}, result.get("entity_map") or {},
                            depth=1, max_per_side=12)
    nodes = view.get("nodes") or []
    if len(nodes) <= 1:
        return None, view
    bycol = {}
    for n in nodes:
        bycol.setdefault(n["col"], []).append(n)
    pos = {}
    for c, ns in bycol.items():
        for i, n in enumerate(ns):
            pos[n["address"]] = (c * 2.2, (len(ns) - 1) / 2 - i)
    rows = max(len(v) for v in bycol.values())
    fig = Figure(figsize=(7.0, min(6.4, 1.6 + 0.42 * rows)))
    ax = fig.add_subplot(111)
    for u, v, _val in view.get("edges") or []:
        if u in pos and v in pos:
            ax.add_patch(FancyArrowPatch(pos[u], pos[v], arrowstyle="-|>", mutation_scale=10,
                                         lw=1.2, color="#8B98A9", shrinkA=8, shrinkB=8))
    for n in nodes:
        x, y = pos[n["address"]]
        ax.scatter([x], [y], s=210 if n["is_root"] else 110, c=BAND_HEX.get(n["band"], "#8B98A9"),
                   marker="D" if n["is_root"] else "o", edgecolors="#1F2A37", linewidths=0.8, zorder=3)
        ax.text(x, y - 0.33, _short(n["address"], 6, 4), ha="center", va="top", fontsize=6.3, color="#1F2A37")
    ytop = max(p[1] for p in pos.values()) + 0.85
    for x, t in ((-2.2, "funds came FROM"), (0, "investigated address"), (2.2, "funds went TO")):
        ax.text(x, ytop, t, ha="center", fontsize=7.6, color="#5B6775", weight="bold")
    ax.set_xlim(-3.4, 3.4)
    ax.set_ylim(min(p[1] for p in pos.values()) - 0.9, ytop + 0.4)
    ax.axis("off")
    handles = [Line2D([0], [0], marker="o", color="w", markerfacecolor=BAND_HEX[b], markeredgecolor="#1F2A37",
                      markersize=7, label=BAND_NAME[b]) for b in ("high", "medium", "low")]
    handles.append(Line2D([0], [0], marker="D", color="w", markerfacecolor="white", markeredgecolor="#1F2A37",
                          markersize=7, label="Investigated address"))
    ax.legend(handles=handles, loc="lower center", ncol=4, fontsize=7, frameon=False,
              bbox_to_anchor=(0.5, -0.08))
    return _png(fig, width_pt), view


def _chart_timeline(df, width_pt: float):
    from matplotlib.figure import Figure
    import matplotlib.dates as mdates
    d = df[df["has_time"]].sort_values("time")
    if len(d) < 1:
        return None
    fig = Figure(figsize=(7.0, 2.6))
    ax = fig.add_subplot(111)
    markers = {"Outgoing": "^", "Incoming": "v", "Related": "o"}
    for rel in ("Outgoing", "Incoming", "Related"):
        sub = d[d["relation"] == rel]
        if len(sub):
            ax.scatter(sub["time"], sub["value_btc"], s=26, c=RELATION_HEX[rel], marker=markers[rel],
                       label=f"{rel} ({len(sub)})", edgecolors="#1F2A37", linewidths=0.4)
    ax.set_ylabel("Total output value (BTC)", fontsize=8)
    ax.set_xlabel("Block time (UTC)", fontsize=8)
    ax.tick_params(labelsize=7.5)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    fig.autofmt_xdate(rotation=20)
    ax.legend(fontsize=7.5, frameon=False, loc="best")
    ax.grid(alpha=0.25)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    return _png(fig, width_pt)


# ---------------------------------------------------------------- data access
def _stored_investigation(result: dict) -> dict:
    """created_at / notes / max_hops for this investigation from the database,
    or {} if unavailable. A report must still build without a database."""
    try:
        from db import database
        row = database.get_investigation(result.get("investigation_id"))
        return dict(row) if row else {}
    except Exception:
        return {}


def _band_counts(result: dict) -> dict:
    counts = {"high": 0, "medium": 0, "low": 0}
    for rs in (result.get("risk_scores") or {}).values():
        b = rs.get("band")
        if b in counts:
            counts[b] += 1
    return counts


def _ranked(result: dict) -> list:
    rows = [(a, rs) for a, rs in (result.get("risk_scores") or {}).items()]
    rows.sort(key=lambda kv: (-(kv[1].get("score") or 0), kv[0]))
    return rows


def _signals_text(rs: dict) -> str:
    parts = []
    for b in rs.get("breakdown") or []:
        pts = b.get("points", 0)
        parts.append(f"{b.get('signal', '?')} ({pts:+g})" if isinstance(pts, (int, float)) else str(b.get("signal", "?")))
    return ", ".join(parts) if parts else "none"


def _threat_matches(result: dict) -> dict:
    """{list name: [addresses]} from dataset-match attributions."""
    out = {}
    for addr, attrs in (result.get("entity_map") or {}).items():
        for a in attrs or []:
            if a.get("method") == "dataset_match":
                name = str(a.get("detail", "")).split(":")[0].strip() or "threat list"
                out.setdefault(name, [])
                if addr not in out[name]:
                    out[name].append(addr)
    return out


def _pattern_counts(result: dict) -> dict:
    p = result.get("patterns") or {}
    return {key: len(p.get(key) or []) for key, _ in PATTERN_KEYS}


# ---------------------------------------------------------------- sections
def _sec_title(result, S, info):
    el = [_p("BitTrace Investigation Report", S["title"]),
          _p(f"Investigation #{result.get('investigation_id', '?')}  |  Bitcoin forensics and threat attribution", S["subtitle"])]
    meta = result.get("meta") or {}
    if result.get("stored_only"):
        source = "Not recorded with stored investigations"
    elif meta.get("synthetic") is True:
        source = "Synthetic demo data (not real blockchain data)"
    elif meta.get("synthetic") is False:
        source = "Live blockchain data"
    else:
        source = "Not recorded"
    notes = (info.get("notes") or result.get("notes") or "").strip()
    rows = [
        ["Investigation ID", f"#{result.get('investigation_id', '?')}"],
        ["Investigation date (UTC)", info.get("created_at") or result.get("created_at") or "Not available"],
        ["Report generated (UTC)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")],
        ["Investigated address", None],
        ["Hops traced", str(info.get("max_hops") or meta.get("max_hops") or "Not recorded")],
        ["Data source", source],
        ["Investigator notes", notes or "None recorded"],
    ]
    wrapped = []
    for k, v in rows:
        if k == "Investigated address":
            wrapped.append([_p(k, S["cell_b"]), Paragraph(_esc(result.get("root_address") or "Not available"), S["mono"])])
        else:
            wrapped.append([_p(k, S["cell_b"]), _p(v, S["cell"])])
    t = Table(wrapped, colWidths=[120, CONTENT_W - 120])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F4F6F8")),
                           ("LEFTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 3),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return el + [t]


def _sec_summary(result, S):
    meta = result.get("meta") or {}
    counts = _band_counts(result)
    n_scored = sum(counts.values())
    patterns_total = sum(_pattern_counts(result).values())
    el = [_p("1. Summary of findings", S["h1"])]

    def cell(v):
        return _p(v, S["cell"])
    metrics = [
        ["Transactions analysed", f"{len(result['txs']):,}" if result.get("txs") else "Not stored with this investigation"],
        ["Addresses analysed", f"{len(result.get('addresses') or result.get('risk_scores') or []):,}"],
        ["Addresses scored", f"{n_scored:,}"],
        ["Clusters identified", f"{len(result.get('clusters') or []):,}"],
        ["Patterns detected (instances)", f"{patterns_total:,}"],
        ["High / Medium / Low risk", f"{counts['high']:,} / {counts['medium']:,} / {counts['low']:,}"],
    ]
    if meta.get("root_tx_total"):
        metrics.append(["Investigated address on-chain transactions",
                        f"{meta['root_tx_total']:,} (analysed: {meta.get('root_tx_fetched', 0):,} most recent)"])
    t = Table([[_p(a, S["cell_b"]), cell(b)] for a, b in metrics], colWidths=[210, CONTENT_W - 210])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, RULE), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F4F6F8")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5), ("LEFTPADDING", (0, 0), (-1, -1), 5)]))
    el.append(t)
    el.append(Spacer(1, 6))
    el.append(_p("Key findings", S["h2"]))
    for line in _key_findings(result):
        el.append(Paragraph(_esc(line), S["bullet"], bulletText="\u2022"))
    return el


def _key_findings(result: dict) -> list:
    meta = result.get("meta") or {}
    counts = _band_counts(result)
    n = sum(counts.values())
    ranges = _band_ranges()
    out = []
    if n:
        out.append(f"{counts['high']} of {n:,} scored addresses are High risk ({ranges['high']}), "
                   f"{counts['medium']} Medium ({ranges['medium']}) and {counts['low']:,} Low ({ranges['low']}).")
    else:
        out.append("No risk scores are available for this investigation.")
    root = result.get("root_address")
    rs = (result.get("risk_scores") or {}).get(root)
    if rs:
        out.append(f"The investigated address scored {_fmt_score(rs.get('score'))} ({BAND_NAME.get(rs.get('band'), rs.get('band'))}). "
                   f"Signals: {_signals_text(rs)}.")
    tm = _threat_matches(result)
    if tm:
        text = "; ".join(f"{len(a)} address(es) on the {name} list" for name, a in sorted(tm.items()))
        out.append(f"Threat-list matches: {text}. A match means the address appears on a published list; "
                   f"it does not show who controls it now.")
    elif result.get("entity_map") is not None and n:
        out.append("No analysed address matched the bundled threat-intelligence lists.")
    pc = _pattern_counts(result)
    if sum(pc.values()):
        labels = dict(PATTERN_KEYS)
        out.append("Detected patterns (instances): " + ", ".join(
            f"{v:,} {labels[k].lower()}" for k, v in pc.items() if v) + ".")
    elif result.get("patterns") is not None:
        out.append("No fan-in, fan-out, CoinJoin-like, peel-chain or circular-flow patterns were detected.")
    if meta.get("root_tx_total") and meta.get("root_tx_fetched", 0) < meta["root_tx_total"]:
        out.append(f"Sample only: the investigated address has {meta['root_tx_total']:,} on-chain transactions; "
                   f"the most recent {meta.get('root_tx_fetched', 0):,} were analysed, so older activity is not covered.")
    if result.get("stored_only"):
        out.append("This report was rebuilt from stored investigation records. Transaction-level data and the "
                   "fund-flow graph are not stored per investigation, so those sections are omitted.")
    return out


def _sec_risk(result, S, width):
    counts = _band_counts(result)
    n = sum(counts.values())
    el = [_p("2. Risk assessment", S["h1"])]
    if not n:
        return el + [_p("No risk scores are available for this investigation.", S["body"])]
    el.append(_chart_bands(counts, width * 0.92))
    el.append(_p(f"Figure 1: addresses by risk band. Bands: {', '.join(f'{BAND_NAME[b]} {r}' for b, r in _band_ranges().items())}.", S["caption"]))

    # High-risk addresses
    ranked = _ranked(result)
    high = [(a, rs) for a, rs in ranked if rs.get("band") == "high"]
    el.append(_p("High-risk addresses", S["h2"]))
    if not high:
        el.append(_p("No address scored in the High band.", S["body"]))
    else:
        rows = [[_p("Address", S["cell_h"]), _p("Score", S["cell_hr"]), _p("Why (signals and points)", S["cell_h"]),
                 _p("Entity attribution", S["cell_h"])]]
        extra = []
        for i, (a, rs) in enumerate(high[:MAX_LIST_ROWS], start=1):
            attrs = (result.get("entity_map") or {}).get(a) or []
            attr = "; ".join(f"{x.get('entity_type', '?')} ({x.get('method', '?').replace('_', ' ')})" for x in attrs) or "none"
            reasons = "; ".join(f"{b.get('signal')}: {b.get('reason', '')}".strip(": ") for b in (rs.get("breakdown") or [])[:4]) or "-"
            rows.append([Paragraph(_esc(a), S["mono"]), _p(_fmt_score(rs.get("score")), S["cell_r"]), _p(reasons, S["cell"]), _p(attr, S["cell"])])
            extra.append(("BACKGROUND", (1, i), (1, i), BAND_FILL["high"]))
        el.append(_table(rows, [150, 38, CONTENT_W - 150 - 38 - 105, 105], S, extra=extra))
        if len(high) > MAX_LIST_ROWS:
            el.append(_p(f"Showing the {MAX_LIST_ROWS} highest-scoring of {len(high)} High-risk addresses.", S["note"]))

    # Top ranked
    el.append(_p("Highest-scoring addresses (all bands)", S["h2"]))
    rows = [[_p("#", S["cell_h"]), _p("Address", S["cell_h"]), _p("Score", S["cell_hr"]),
             _p("Band", S["cell_h"]), _p("Signals", S["cell_h"])]]
    extra = []
    for i, (a, rs) in enumerate(ranked[:15], start=1):
        band = rs.get("band", "low")
        rows.append([_p(i, S["cell"]), Paragraph(_esc(a), S["mono"]), _p(_fmt_score(rs.get("score")), S["cell_r"]),
                     _p(BAND_NAME.get(band, str(band)), S["cell_b"]), _p(_signals_text(rs), S["cell"])])
        extra.append(("BACKGROUND", (3, i), (3, i), BAND_FILL.get(band, colors.white)))
    el.append(_table(rows, [20, 150, 36, 62, CONTENT_W - 268], S, extra=extra))
    return el


def _sec_graph(result, S, width):
    el = [_p("3. Graph analysis and detected patterns", S["h1"])]
    g = result.get("graph")
    analytics = result.get("analytics") or {}
    if g is not None:
        el.append(_p(f"Fund-flow graph: {g.number_of_nodes():,} addresses and {g.number_of_edges():,} directed links "
                     f"between them (an input address to an output address within a transaction).", S["body"]))
        try:
            img, view = _chart_focus_graph(result, width * 0.92)
        except Exception as e:  # a drawing problem must not lose the whole report
            img, view = None, None
            el.append(_p(f"The graph picture could not be drawn ({type(e).__name__}).", S["note"]))
        if img is not None:
            el = [KeepTogether(el + [img, _p(f"Figure 2: focus view of the investigated address, showing {len(view['nodes'])} of "
                         f"{view['total_nodes']:,} addresses in the graph: its direct senders (left) and recipients "
                         f"(right). Colour shows risk band and is repeated in the legend labels.", S["caption"])])]
    else:
        el.append(_p("The fund-flow graph is not stored with this investigation, so no graph picture or graph "
                     "metrics are shown.", S["body"]))

    if analytics:
        ranked = sorted(analytics.items(), key=lambda kv: -(kv[1].get("betweenness") or 0))[:8]
        if any((v.get("betweenness") or 0) > 0 for _, v in ranked):
            el.append(_p("Most central addresses (betweenness centrality)", S["h2"]))
            rows = [[_p("Address", S["cell_h"]), _p("Betweenness", S["cell_hr"]), _p("PageRank", S["cell_hr"]),
                     _p("Degree centrality", S["cell_hr"])]]
            for a, v in ranked:
                rows.append([Paragraph(_esc(a), S["mono"]), _p(f"{v.get('betweenness') or 0:.4f}", S["cell_r"]),
                             _p(f"{v.get('pagerank') or 0:.4f}", S["cell_r"]), _p(f"{v.get('degree_centrality') or 0:.4f}", S["cell_r"])])
            el.append(_table(rows, [CONTENT_W - 3 * 80, 80, 80, 80], S))
            el.append(_p("Betweenness measures how often an address lies on paths between other addresses; high "
                         "values suggest a pass-through hub.", S["note"]))

    patterns = result.get("patterns")
    el.append(_p("Detected transaction patterns", S["h2"]))
    if patterns is None:
        el.append(_p("Pattern data is not available.", S["body"]))
        return el
    pc = _pattern_counts(result)
    if sum(pc.values()):
        el.append(_chart_patterns(patterns, width * 0.92))
        el.append(_p("Figure 3: number of detected instances per pattern type.", S["caption"]))
    else:
        el.append(_p("No fan-in, fan-out, CoinJoin-like, peel-chain or circular-flow patterns were detected.", S["body"]))
        return el
    rows = [[_p("Pattern", S["cell_h"]), _p("Detail", S["cell_h"]), _p("Address(es)", S["cell_h"])]]
    for key, label in PATTERN_KEYS:
        for item in (patterns.get(key) or [])[:5]:
            if key in ("fan_in", "fan_out"):
                n = item.get("count", len(item.get("sources") or item.get("targets") or []))
                detail, addr = f"{n} {'sources' if key == 'fan_in' else 'targets'}", item.get("address", "")
            elif key == "coinjoin":
                detail = f"{item.get('output_count', '?')} equal outputs of {_fmt_btc(item.get('equal_value_btc'))} BTC"
                addr = f"tx {item.get('txid', '')}"
            elif key == "peel_chains":
                path = item.get("path") or []
                detail, addr = f"{item.get('hops', len(path) - 1)} hops", f"{_short(path[0] if path else '')} to {_short(path[-1] if path else '')}"
            else:
                cyc = item.get("cycle") or []
                detail, addr = f"{item.get('length', len(cyc))} addresses in the loop", " > ".join(_short(c, 6, 4) for c in cyc[:4])
            rows.append([_p(label, S["cell_b"]), _p(detail, S["cell"]), Paragraph(_esc(addr), S["mono"])])
    el.append(_table(rows, [80, 150, CONTENT_W - 230], S))
    el.append(_p("Up to five examples per pattern type are listed. Patterns are heuristic indicators; they also occur "
                 "in legitimate activity.", S["note"]))
    return el


def _sec_clusters(result, S):
    clusters = result.get("clusters") or []
    el = [_p("4. Address clusters", S["h1"])]
    if not clusters:
        return el + [_p("No clusters are available for this investigation.", S["body"])]
    el.append(_p(f"{len(clusters):,} cluster(s): groups of addresses that are likely controlled by one wallet "
                 f"(common-input-ownership and change-address heuristics). The largest are shown.", S["body"]))
    rows = [[_p("#", S["cell_h"]), _p("Cluster", S["cell_h"]), _p("Addresses", S["cell_hr"]), _p("Example members", S["cell_h"])]]
    for i, c in enumerate(sorted(clusters, key=lambda c: -(c.get("size") or 0))[:10], start=1):
        members = c.get("members") or []
        rows.append([_p(i, S["cell"]), Paragraph(_esc(_short(c.get("root") or (members[0] if members else ""), 10, 6)), S["mono"]),
                     _p(c.get("size", len(members)), S["cell_r"]),
                     Paragraph(_esc(", ".join(_short(m, 6, 4) for m in members[:3]) + (" ..." if len(members) > 3 else "")), S["mono"])])
    el.append(_table(rows, [22, 120, 55, CONTENT_W - 197], S))
    return el


def _sec_transactions(result, S, width, df):
    el = [_p("5. Transaction details", S["h1"])]
    if df is None or df.empty:
        return el + [_p("Transaction-level data is not stored with this investigation. Run the investigation again "
                        "to include the analysed transactions in a report.", S["body"])]
    n_time = int(df["has_time"].sum())
    out_n, in_n, rel_n = (int((df["relation"] == r).sum()) for r in ("Outgoing", "Incoming", "Related"))
    el.append(_p(f"{len(df):,} transactions were analysed: {out_n:,} outgoing (the investigated address is a sender), "
                 f"{in_n:,} incoming (it only receives) and {rel_n:,} related (they involve neighbouring addresses "
                 f"reached while tracing hops).", S["body"]))
    if n_time:
        img = _chart_timeline(df, width * 0.92)
        if img is not None:
            el.append(img)
            el.append(_p(f"Figure 4: total output value of the {n_time:,} transactions that have a block time"
                         + (f" ({len(df) - n_time:,} without a block time are not plotted)." if n_time < len(df) else "."), S["caption"]))
    else:
        el.append(_p("None of these transactions has a block time (expected for demo data or unconfirmed transactions), "
                     "so no time chart is shown. The table lists them in the order the analysis processed them, which "
                     "is not blockchain chronology.", S["note"]))
    rows = [[_p("#", S["cell_h"]), _p("Transaction ID", S["cell_h"]), _p("Block time (UTC)", S["cell_h"]),
             _p("Relation", S["cell_h"]), _p("In", S["cell_hr"]), _p("Out", S["cell_hr"]), _p("Output total (BTC)", S["cell_hr"])]]
    for r in df.head(MAX_TX_ROWS).itertuples():
        when = r.time.strftime("%Y-%m-%d %H:%M") if r.has_time else "n/a"
        rows.append([_p(r.order, S["cell"]), Paragraph(_esc(r.txid), S["mono"]), _p(when, S["cell"]),
                     _p(r.relation, S["cell"]), _p(r.n_inputs, S["cell_r"]), _p(r.n_outputs, S["cell_r"]),
                     _p(_fmt_btc(r.value_btc), S["cell_r"])])
    el.append(_table(rows, [22, 176, 88, 50, 22, 24, CONTENT_W - 382], S))
    if len(df) > MAX_TX_ROWS:
        el.append(_p(f"Showing the first {MAX_TX_ROWS} of {len(df):,} transactions.", S["note"]))
    return el


def _sec_method(result, S):
    el = [_p("6. Method and limitations", S["h1"])]
    hi, med = config.RISK_BAND_HIGH, config.RISK_BAND_MEDIUM
    for line in (
        f"Risk scores run from 0 to {config.RISK_SCORE_MAX}: Low below {med}, Medium {med}-{hi - 1}, High {hi} and above. "
        f"An address on a confirmed threat list is raised to at least {config.RISK_DATASET_MATCH_FLOOR}. Every point has a "
        f"stated reason (see the signals above).",
        "Scores prioritise what to review first. They are not proof of criminal activity or of who controls an address.",
        "Clustering (common-input ownership and change detection) and pattern detection are heuristics and can be wrong; "
        "CoinJoin and mixing services deliberately break them.",
        "Threat-list matching only shows that an address appears on a bundled, published list. The bundled lists are small.",
        "Only the most recent transactions of the investigated address (and a limited number of its busiest neighbours) "
        "are fetched, so very active addresses are analysed as a sample.",
    ):
        el.append(Paragraph(_esc(line), S["bullet"], bulletText="\u2022"))
    return el


# ---------------------------------------------------------------- assembly
class _NumberedCanvas(canvas.Canvas):
    """Canvas that knows the total page count, for 'Page x of y' footers."""

    def __init__(self, *args, footer_text="", fonts=("Helvetica", "Helvetica-Bold", "Courier"), **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_pages = []
        self._footer_text = footer_text
        self._fonts = fonts

    def showPage(self):
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_pages)
        for state in self._saved_pages:
            self.__dict__.update(state)
            self._decorate(total)
            super().showPage()
        super().save()

    def _decorate(self, total: int):
        sans = self._fonts[0]
        # Footer sits entirely inside the 46 pt bottom margin, so it never
        # touches body content: rule at y=35, report/page line at y=25,
        # developer attribution line at y=14.
        self.setStrokeColor(RULE)
        self.setLineWidth(0.5)
        self.line(MARGIN, 35, PAGE_W - MARGIN, 35)
        self.setFont(sans, 7.5)
        self.setFillColor(GREY)
        self.drawString(MARGIN, 25, self._footer_text)
        self.drawRightString(PAGE_W - MARGIN, 25, f"Page {self._pageNumber} of {total}")
        self.setFont(sans, 6.5)
        self.setFillColor(ATTRIBUTION_GREY)
        self.drawCentredString(PAGE_W / 2, 14, DEVELOPER_ATTRIBUTION)


def build_pdf_report(result: dict, png_path: Optional[Path] = None) -> bytes:
    """Build the investigation report and return it as PDF bytes.

    `result` is the dict returned by pipeline.run_investigation(), or one
    rebuilt by result_from_database(). Optional parts may be missing; those
    sections then say so instead of failing. `png_path` is accepted for
    backward compatibility with the old export_pdf(); the report draws its own
    focus-view graph and does not need it.
    """
    S = _styles()
    info = _stored_investigation(result)
    try:
        df = timeline_frame(result) if result.get("txs") else None
    except Exception:
        df = None

    story = _sec_title(result, S, info)
    sections = [
        ("Summary of findings", lambda: _sec_summary(result, S)),
        ("Risk assessment", lambda: _sec_risk(result, S, CONTENT_W)),
        ("Graph analysis", lambda: _sec_graph(result, S, CONTENT_W)),
        ("Address clusters", lambda: _sec_clusters(result, S)),
        ("Transaction details", lambda: _sec_transactions(result, S, CONTENT_W, df)),
        ("Method and limitations", lambda: _sec_method(result, S)),
    ]
    for name, build in sections:
        try:
            story.extend(build())
        except Exception as e:  # one broken section must not lose the whole report
            story.append(_p(f"{name}", S["h1"]))
            story.append(_p(f"This section could not be generated ({type(e).__name__}: {e}).", S["note"]))

    buf = io.BytesIO()
    footer = f"BitTrace v2  |  Investigation #{result.get('investigation_id', '?')}"
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=40, bottomMargin=46,
                            title=f"BitTrace investigation report #{result.get('investigation_id', '?')}",
                            author="BitTrace v2", subject="Bitcoin forensics investigation report")
    fonts = S["fonts"]
    doc.build(story, canvasmaker=lambda *a, **k: _NumberedCanvas(*a, footer_text=footer, fonts=fonts, **k))
    return buf.getvalue()


def export_pdf(result: dict, out_path: Optional[Path] = None, png_path: Optional[Path] = None) -> Path:
    """Write the PDF report to disk (kept for export_all and existing callers)."""
    out_path = out_path or config.REPORTS_DIR / f"investigation_{result['investigation_id']}_report.pdf"
    Path(out_path).write_bytes(build_pdf_report(result, png_path))
    return Path(out_path)


def result_from_database(investigation_id: int) -> Optional[dict]:
    """Rebuild a report-ready dict from stored records only.

    Used for investigations that are no longer in memory (History page). The
    schema does not link transactions to an investigation and does not store
    the graph, so `txs` is empty and `graph` is absent; the report says so.
    Returns None if the investigation does not exist.
    """
    from db import database
    inv = database.get_investigation(investigation_id)
    if not inv:
        return None
    risk_scores = {}
    for row in database.get_risk_scores_for_investigation(investigation_id):
        try:
            breakdown = (json.loads(row["explanation_json"] or "{}") or {}).get("breakdown", [])
        except (TypeError, ValueError):
            breakdown = []
        risk_scores[row["address"]] = {"address": row["address"], "score": row["score"],
                                       "band": row["band"], "breakdown": breakdown}
    key_for = {"peel_chain": "peel_chains", "circular_flow": "circular_flows"}
    patterns = {k: [] for k, _ in PATTERN_KEYS}
    for row in database.get_patterns_for_investigation(investigation_id):
        try:
            detail = json.loads(row["detail_json"] or "{}") or {}
        except (TypeError, ValueError):
            detail = {}
        patterns.setdefault(key_for.get(row["pattern_type"], row["pattern_type"]), []).append(detail)
    clusters = []
    for c in database.get_clusters_for_investigation(investigation_id):
        members = sorted(m["address"] for m in database.get_cluster_addresses(c["id"]))
        clusters.append({"root": c["label"] or (members[0] if members else ""), "size": len(members), "members": members})
    entity_map = {}
    for addr, rs in risk_scores.items():  # dataset matches are always High risk, so High/Medium/root suffices
        if rs["band"] != "low" or addr == inv["root_address"]:
            entity_map[addr] = [dict(a) for a in database.get_entity_attributions(addr)]
    return {
        "investigation_id": investigation_id, "root_address": inv["root_address"],
        "created_at": inv["created_at"], "notes": inv["notes"], "meta": {"max_hops": inv["max_hops"]},
        "addresses": list(risk_scores), "txs": [], "graph": None, "analytics": {},
        "risk_scores": risk_scores, "patterns": patterns, "clusters": clusters,
        "entity_map": entity_map, "stored_only": True,
    }


def export_all(result: dict) -> dict:
    json_path = export_json(result)
    csv_path = export_csv(result)
    png_path = export_graph_png(result)
    pdf_path = export_pdf(result, png_path=png_path)
    return {"json": json_path, "csv": csv_path, "png": png_path, "pdf": pdf_path}


if __name__ == "__main__":
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from core.pipeline import run_investigation

    synthetic_txs = [
        {"txid": "t1", "inputs": [{"address": "ROOT", "value_btc": 5.0}],
         "outputs": [{"address": "13AM4VW2dhxYgXeQepoHkHSQuy6NgaEb94", "value_btc": 4.9},
                     {"address": "CHANGE1", "value_btc": 0.09872311}]},
    ]
    result = run_investigation("ROOT", synthetic_txs=synthetic_txs, notes="report generator smoke test")
    paths = export_all(result)
    for fmt, p in paths.items():
        exists = Path(p).exists()
        size = Path(p).stat().st_size if exists else 0
        print(f"{fmt.upper():5s}: {p}  exists={exists}  size={size} bytes")
        assert exists and size > 0, f"FAIL: {fmt} export did not produce a real file"
    print("PASS: all four export formats generated real, non-empty files.")