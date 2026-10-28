from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import html
import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from ui_theme import apply_theme, metric_cards, style_figure, TEXT, MUTED, GRID
from core.dashboard_data import (RELATIONS, RELATION_COLOR, RELATION_HELP, RELATION_SYMBOL,
                                 short_id, timeline_frame)

st.set_page_config(page_title="Timeline - BitTrace", layout="wide")
apply_theme()
st.title("Transaction Timeline")

from db import database
from core.dashboard_data import investigation_label


def _load_timeline_result(inv_id):
    """Result dict for ONE investigation. Uses the in-session result when it is the same
    investigation, otherwise rebuilds it from the stored investigation_transactions links
    (never from a global transaction query). Legacy investigations without links get no txs."""
    live = st.session_state.get("last_result")
    if live and live.get("investigation_id") == inv_id and live.get("txs"):
        return live
    from core.report_generator import result_from_database
    base = result_from_database(inv_id)
    if base is None:
        return None
    txs = database.get_investigation_transactions(inv_id) if database.has_transaction_links(inv_id) else []
    for t in txs:
        for a in (t.get("inputs") or []) + (t.get("outputs") or []):
            try:
                a["value_btc"] = float(a.get("value_btc") or 0)
            except (TypeError, ValueError):
                a["value_btc"] = 0.0
    base["txs"] = txs
    return base


try:
    summaries = database.get_investigation_summaries()
except Exception as exc:   # missing/unreadable database
    st.error(f"Could not read investigations: {exc}")
    st.stop()
if not summaries:
    st.info("No investigations exist yet. Run one on the **Investigate** page, then come back here.")
    st.stop()

ids = [r["id"] for r in summaries]
labels = {r["id"]: investigation_label(r) for r in summaries}
live_id = (st.session_state.get("last_result") or {}).get("investigation_id")
if st.session_state.get("timeline_inv_id") not in ids:   # first visit, or the selection was deleted
    st.session_state["timeline_inv_id"] = live_id if live_id in ids else ids[0]
sel_id = st.selectbox("Investigation", ids, key="timeline_inv_id", format_func=lambda i: labels[i])

result = _load_timeline_result(sel_id)
if result is None:
    st.warning("This investigation no longer exists.")
    st.stop()

meta = result.get("meta", {})
df = timeline_frame(result)
if df.empty:
    st.warning("No timeline data available for this investigation.")
    st.stop()

# ---------------------------------------------------------------- header
st.markdown(f"Investigation **#{result['investigation_id']}** - investigated address `{result['root_address']}`")
scope = f"{len(df):,} transactions in the analysed sample."
if meta.get("synthetic"):
    scope += " Demo data: these are synthetic transactions, not real blockchain activity."
elif meta.get("root_tx_total"):
    scope += (f" The investigated address has {meta['root_tx_total']:,} on-chain transactions; "
              f"only the most recent {meta.get('root_tx_fetched', 0):,} were fetched, plus transactions of "
              f"neighbouring addresses when more than one hop is traced.")
st.caption(scope)

# ---------------------------------------------------------------- summary cards
n_time = int(df["has_time"].sum())
counts = {r: int((df["relation"] == r).sum()) for r in RELATIONS}
if n_time:
    first, last = df.loc[df["has_time"], "time"].min(), df.loc[df["has_time"], "time"].max()
    span = (f"{first:%Y-%m-%d}", f"to {last:%Y-%m-%d} (UTC)") if first.date() != last.date() else (f"{first:%Y-%m-%d}", "UTC")
else:
    span = ("Not available", "no block times")
metric_cards([
    ("Transactions", f"{len(df):,}", "in this analysis", "#3B9EBF"),
    ("Outgoing", f"{counts['Outgoing']:,}", "investigated address sends", RELATION_COLOR["Outgoing"]),
    ("Incoming", f"{counts['Incoming']:,}", "investigated address receives", RELATION_COLOR["Incoming"]),
    ("Related", f"{counts['Related']:,}", "neighbouring addresses", RELATION_COLOR["Related"]),
    ("Time span", span[0], span[1], "#3B9EBF"),
])

# ---------------------------------------------------------------- time / order notice
if n_time == 0:
    st.info(
        "**No block times are available** for these transactions (expected for demo data or unconfirmed "
        "transactions). The chart therefore shows the **order in which BitTrace processed them** "
        "(1 = first). This is not blockchain chronology."
    )
elif n_time < len(df):
    st.warning(
        f"{len(df) - n_time:,} of {len(df):,} transactions have no block time (for example, unconfirmed "
        f"transactions). They are not drawn on the time axis but remain in the table below."
    )

# ---------------------------------------------------------------- activity-timeline styling (this page only)
st.markdown(
    """
<style>
.bt-ch { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:flex-start; gap:0.8rem 1.6rem;
         padding:0 0 0.8rem 0; border-bottom:1px solid #263041; margin-bottom:0.8rem; }
.bt-ch-main { flex:1 1 380px; min-width:260px; }
.bt-ch-title { color:#E6EDF3; font-size:1.1rem; font-weight:600; line-height:1.3; }
.bt-ch-sub { color:#9AA7B8; font-size:0.85rem; line-height:1.5; margin-top:0.25rem; max-width:46rem; }
.bt-ch-sub b { color:#E6EDF3; font-weight:600; }
.bt-ch-legend { display:flex; flex-direction:column; gap:0.3rem; flex:0 0 auto; }
.bt-ch-key { display:flex; align-items:center; gap:0.55rem; background:#121821; border:1px solid #263041;
             border-radius:3px; padding:0.25rem 0.65rem; color:#C9D4E0; font-size:0.82rem; white-space:nowrap; }
.bt-ch-key em { color:#8B98A9; font-style:normal; font-size:0.76rem; margin-left:auto; padding-left:0.8rem; }
.bt-pulse { position:relative; display:inline-block; width:0.8rem; height:1.05rem; flex:none; }
.bt-pulse i { position:absolute; left:50%; width:2px; margin-left:-1px; }
.bt-pulse b { position:absolute; left:50%; width:0.55rem; height:0.55rem; margin-left:-0.275rem; border-radius:50%; }
.bt-pulse-up i { top:0.28rem; bottom:50%; } .bt-pulse-up b { top:0; }
.bt-pulse-down i { top:50%; bottom:0.28rem; } .bt-pulse-down b { bottom:0; }
.bt-pulse-flat i { top:0.28rem; bottom:0.1rem; } .bt-pulse-flat b { top:0; }
.bt-ch-note { color:#8B98A9; font-size:0.8rem; line-height:1.5; margin:0.2rem 0 0.4rem 0; }
.bt-ch-note b { color:#C9D4E0; font-weight:600; }
.bt-sel { border:1px solid #263041; border-left:3px solid var(--c); background:#121821; border-radius:3px;
          padding:0.8rem 1rem 0.7rem 1rem; margin:0.4rem 0 0.3rem 0; }
.bt-sel-h { color:#8B98A9; font-size:0.74rem; text-transform:uppercase; letter-spacing:0.07em; margin-bottom:0.5rem; }
.bt-sel-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(170px, 1fr)); gap:0.6rem 1.4rem; }
.bt-sel-k { color:#8B98A9; font-size:0.74rem; text-transform:uppercase; letter-spacing:0.05em; }
.bt-sel-v { color:#E6EDF3; font-size:1.02rem; font-weight:600; margin-top:0.1rem; }
.bt-sel-v small { color:#8B98A9; font-weight:400; font-size:0.78rem; }
.bt-sel-hint { border:1px dashed #2F3B4E; border-radius:3px; color:#8B98A9; font-size:0.85rem;
               padding:0.7rem 1rem; margin:0.4rem 0 0.3rem 0; }
</style>
""",
    unsafe_allow_html=True,
)

LANE_LABEL = {"Incoming": "Incoming - received by the investigated address",
              "Outgoing": "Outgoing - sent by the investigated address",
              "Related": "Related - neighbouring addresses only"}


def _fmt_btc(v: float) -> str:
    """Compact BTC number for axis labels (no scientific notation)."""
    if v >= 1000:
        return f"{v:,.0f}"
    return f"{v:.8f}".rstrip("0").rstrip(".") or "0"


def _nice_ticks(max_btc: float, log: bool, c: float) -> list:
    """BTC values (> 0) at which to label a lane, at most about 6."""
    if max_btc <= 0:
        return []
    if log:
        lo, hi = math.ceil(math.log10(c) - 1e-9), math.floor(math.log10(max_btc) + 1e-9)
        vals = [10.0 ** k for k in range(lo, hi + 1)]
        if not vals:
            vals = [max_btc]
        while len(vals) > 6:
            vals = vals[::2]
        return vals
    raw = max_btc / 3
    mag = 10 ** math.floor(math.log10(raw))
    step = next(k * mag for k in (1, 2, 2.5, 5, 10) if raw <= k * mag)
    return [step * i for i in range(1, int(max_btc // step) + 1)] or [max_btc]


# ---------------------------------------------------------------- chart card
with st.container(border=True):
    # Header: what this is, in plain English, plus a legend that explains where each kind of line goes.
    legend_rows = []
    for r, kind, where in (("Incoming", "up", "above the line"), ("Outgoing", "down", "below the line"),
                           ("Related", "flat", "lower panel")):
        legend_rows.append(
            f'<div class="bt-ch-key" title="{html.escape(RELATION_HELP[r])}">'
            f'<span class="bt-pulse bt-pulse-{kind}"><i style="background:{RELATION_COLOR[r]}"></i>'
            f'<b style="background:{RELATION_COLOR[r]}"></b></span>'
            f'<span><b>{html.escape(r)}</b> - {where}</span><em>{counts[r]:,}</em></div>'
        )
    if n_time:
        explain = ("Each line is <b>one transaction</b>, placed at the time its block was confirmed. Lines rising above the "
                   "centre line are <b>Incoming</b> (the investigated address received BTC); lines dropping below are "
                   "<b>Outgoing</b> (it sent BTC). <b>The longer the line, the more BTC.</b> Click a line for its details.")
    else:
        explain = ("No block times exist for this data, so each line is one transaction placed in the <b>order BitTrace "
                   "processed it - not blockchain chronology</b>. Lines above the centre line are <b>Incoming</b>, lines "
                   "below are <b>Outgoing</b>; <b>the longer the line, the more BTC.</b> Click a line for its details.")
    st.markdown(
        '<div class="bt-ch"><div class="bt-ch-main"><div class="bt-ch-title">Transaction Value Over Time</div>'
        f'<div class="bt-ch-sub">{explain}</div></div>'
        '<div class="bt-ch-legend">' + "".join(legend_rows) + "</div></div>",
        unsafe_allow_html=True,
    )

    # Controls: existing relation filter and value scale, plus one way to zoom in on busy periods.
    c1, c2, c3 = st.columns([3, 2, 2])
    shown = c1.multiselect("Show transactions", list(RELATIONS), default=list(RELATIONS),
                           help="Filter the chart and the table by how a transaction relates to the investigated address. "
                                + " ".join(f"{r}: {RELATION_HELP[r]}." for r in RELATIONS))
    scale = c2.radio("Value scale", ("Linear", "Logarithmic"), index=0, horizontal=True, key="timeline_value_scale",
                     help="Linear: line length is proportional to BTC. Logarithmic: compresses the scale so small "
                          "transactions stay visible next to very large ones. No transaction is removed under either scale.")
    focus = c3.radio("View", ("Full timeline", "Busiest period"), index=0, horizontal=True, key="timeline_view",
                     help="Full timeline shows everything. Busiest period zooms to the stretch of the timeline "
                          "with the most transactions, so crowded lines can be told apart. You can also drag on the "
                          "chart to zoom, and use the home icon in the chart toolbar to reset.")
    log_axis = scale == "Logarithmic"

    view = df[df["relation"].isin(shown)].copy()
    if view.empty:
        st.warning("No transactions match the selected filter.")
        st.stop()
    view["time_text"] = view["time"].dt.strftime("%Y-%m-%d %H:%M").fillna("n/a")   # also used by the table below

    # ------------------------------------------------------------ chart data (real values only)
    plot = view[view["has_time"]].copy() if n_time else view.copy()
    if plot.empty:
        st.warning("None of the selected transactions has a block time, so there is nothing to draw on the time axis.")
        st.stop()
    plot["x"] = plot["time"] if n_time else plot["order"]
    plot["when"] = plot["time"].dt.strftime("%Y-%m-%d %H:%M:%S UTC").fillna("Not available")
    plot["id_text"] = plot["txid"].replace("", pd.NA).fillna("Not available")
    plot["value_text"] = plot["value_btc"].map(lambda v: f"{v:,.8f} BTC")

    # Line length. Zero (and any invalid negative) values get length 0: they stay on the centre line
    # as a marker instead of being dropped. The tooltip always shows the real value.
    vclip = np.nan_to_num(plot["value_btc"].to_numpy(float), nan=0.0).clip(min=0)
    positive = vclip[vclip > 0]
    use_log = log_axis and positive.size > 0
    c0 = float(positive.min()) if positive.size else 1.0   # log scale: length = log10(1 + value / smallest value)

    def length(v):
        v = np.asarray(v, dtype=float)
        return np.log10(1 + v / c0) if use_log else v

    plot["vclip"] = vclip
    plot["mag"] = length(vclip)
    plot["y"] = np.where(plot["relation"] == "Outgoing", -plot["mag"], plot["mag"])
    n_zero = int((vclip == 0).sum())

    has_main = bool(plot["relation"].isin(["Incoming", "Outgoing"]).any())
    has_rel = bool((plot["relation"] == "Related").any())
    lanes = (["main"] if has_main else []) + (["rel"] if has_rel else [])
    row_of = {name: i + 1 for i, name in enumerate(lanes)}
    n_rows = len(lanes)

    fig = make_subplots(rows=n_rows, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                        row_heights=[0.72, 0.28] if n_rows == 2 else [1.0])
    style_figure(fig, height=590 if n_rows == 2 else 450)

    hover = ("<b>%{customdata[1]} transaction</b>"
             "<br>Block time (UTC): <b>%{customdata[2]}</b>"
             "<br>Value: <b>%{customdata[3]}</b>"
             "<br>Transaction ID:<br>%{customdata[0]}<extra></extra>")
    custom_cols = ["id_text", "relation", "when", "value_text", "txid"]
    n_pts = len(plot)
    msize = 9 if n_pts <= 150 else 7 if n_pts <= 800 else 5
    lw = 1.8 if n_pts <= 150 else 1.3 if n_pts <= 800 else 1.0
    curve_txids = {}

    def add_lane(rel: str, row: int) -> None:
        sub = plot[plot["relation"] == rel]
        if sub.empty:
            return
        color = RELATION_COLOR[rel]
        lx, ly = [], []
        for x, y in zip(sub["x"], sub["y"]):          # one vertical stem per transaction, from the centre line
            lx += [x, x, None]
            ly += [0, y, None]
        fig.add_trace(go.Scatter(x=lx, y=ly, mode="lines", line=dict(color=color, width=lw), opacity=0.6,
                                 hoverinfo="skip", showlegend=False), row=row, col=1)
        fig.add_trace(go.Scatter(x=sub["x"], y=sub["y"], mode="markers", name=rel, showlegend=False,
                                 customdata=sub[custom_cols].to_numpy(), hovertemplate=hover,
                                 marker=dict(size=msize, color=color, opacity=0.95, line=dict(width=1.2, color="#0D1117"))),
                      row=row, col=1)
        curve_txids[len(fig.data) - 1] = list(sub["txid"])

    if has_main:
        for rel in ("Incoming", "Outgoing"):
            add_lane(rel, row_of["main"])
    if has_rel:
        add_lane("Related", row_of["rel"])

    # Pinned transaction (from a click on the chart): ring around it.
    def _selected_txid():
        try:
            ev = st.session_state.get("timeline_chart")
            pts = (ev.get("selection") or {}).get("points") or [] if ev else []
        except Exception:
            return None
        for p in pts:
            cd = p.get("customdata")
            cand = cd[4] if isinstance(cd, (list, tuple)) and len(cd) > 4 else None
            if cand is None:
                ids = curve_txids.get(p.get("curve_number"))
                idx = p.get("point_index")
                cand = ids[idx] if ids is not None and isinstance(idx, int) and 0 <= idx < len(ids) else None
            if cand and cand in set(plot["txid"]):
                return cand
        return None

    selected = _selected_txid()
    if selected:
        srow = plot[plot["txid"] == selected].iloc[0]
        fig.add_trace(go.Scatter(x=[srow["x"]], y=[srow["y"]], mode="markers", hoverinfo="skip", showlegend=False,
                                 marker=dict(size=msize + 10, symbol="circle-open", color="#FFFFFF", line=dict(width=2))),
                      row=row_of["rel"] if srow["relation"] == "Related" else row_of["main"], col=1)

    # ------------------------------------------------------------ axes
    def _ticks(max_btc, signed_neg=0.0, span=0.0):
        pos = _nice_ticks(max_btc, use_log, c0)
        neg = _nice_ticks(signed_neg, use_log, c0)
        if use_log and span:   # drop log labels that would sit on top of the "0" label at the centre line
            pos = [v for v in pos if float(length(v)) >= 0.09 * span] or pos[-1:]
            neg = [v for v in neg if float(length(v)) >= 0.09 * span] or neg[-1:]
        vals = [-float(length(v)) for v in neg][::-1] + [0.0] + [float(length(v)) for v in pos]
        text = [_fmt_btc(v) for v in neg][::-1] + ["0"] + [_fmt_btc(v) for v in pos]
        return vals, text

    def _max(rel):
        s = vclip[(plot["relation"] == rel).to_numpy()]
        return float(s.max()) if s.size else 0.0

    grid = "rgba(38,48,65,0.55)"
    if has_main:
        m_in, m_out = _max("Incoming"), _max("Outgoing")
        f_in, f_out = float(length(m_in)), float(length(m_out))
        span_ref = max(f_in, f_out) or 1.0
        top = bottom = span_ref * 1.12   # same scale above and below, so Incoming and Outgoing are directly comparable
        tick_in, tick_out = max(m_in, m_out), max(m_in, m_out)   # label both halves up to the same BTC value
        tv, tt = _ticks(tick_in, tick_out, span_ref)
        fig.update_yaxes(row=row_of["main"], col=1, range=[-bottom, top], tickvals=tv, ticktext=tt,
                         title=dict(text="BTC per transaction" + (" (log scale)" if use_log else ""),
                                    font=dict(size=11, color=MUTED), standoff=6))
        yid = "y" if row_of["main"] == 1 else f"y{row_of['main']}"
        for rel, ypos, anchor in (("Incoming", 0.985, "top"), ("Outgoing", 0.015, "bottom")):
            if rel in shown:
                fig.add_annotation(xref="paper", x=0.004, xanchor="left", yref=f"{yid} domain", y=ypos, yanchor=anchor,
                                   text=("&#9650; " if rel == "Incoming" else "&#9660; ") + LANE_LABEL[rel], showarrow=False,
                                   font=dict(size=11.5, color=RELATION_COLOR[rel]), bgcolor="rgba(13,17,23,0.75)",
                                   borderpad=3)
    if has_rel:
        m_rel = _max("Related")
        f_rel = float(length(m_rel)) or 1.0
        tv, tt = _ticks(m_rel, 0.0, f_rel)
        fig.update_yaxes(row=row_of["rel"], col=1, range=[-0.08 * f_rel, f_rel * 1.2], tickvals=tv, ticktext=tt,
                         title=dict(text="BTC", font=dict(size=11, color=MUTED), standoff=6))
        yid = "y" if row_of["rel"] == 1 else f"y{row_of['rel']}"
        fig.add_annotation(xref="paper", x=0.004, xanchor="left", yref=f"{yid} domain", y=0.985, yanchor="top",
                           text=LANE_LABEL["Related"], showarrow=False, font=dict(size=11.5, color=RELATION_COLOR["Related"]),
                           bgcolor="rgba(13,17,23,0.75)", borderpad=3)
    fig.update_yaxes(fixedrange=True, showgrid=True, gridcolor=grid, gridwidth=1, zeroline=True, zerolinecolor="#6B7C93",
                     zerolinewidth=1.6, showline=False, ticks="", tickfont=dict(size=11.5, color=MUTED), automargin=True)

    fig.update_xaxes(showgrid=False, zeroline=False, showline=True, linecolor=GRID, ticks="outside", tickcolor=GRID,
                     ticklen=4, tickfont=dict(size=11.5, color=MUTED), automargin=True)
    fig.update_xaxes(row=n_rows, col=1,
                     title=dict(text="Block time (UTC)" if n_time else "Processing order (1 = first analysed; not chronological)",
                                font=dict(size=12, color=MUTED), standoff=8),
                     **(dict(tickformatstops=[
                         dict(dtickrange=[None, 86400000 * 1.5], value="%d %b\n%H:%M"),
                         dict(dtickrange=[86400000 * 1.5, 86400000 * 75], value="%d %b %Y"),
                         dict(dtickrange=[86400000 * 75, None], value="%b %Y")],
                         hoverformat="%Y-%m-%d %H:%M") if n_time else dict(tickformat="d")))

    # ------------------------------------------------------------ view: full timeline or busiest period
    busiest_note = ""
    if focus == "Busiest period" and n_pts > 1:
        xs = (np.sort(plot["time"].map(lambda t: t.timestamp()).to_numpy(float)) if n_time
              else np.sort(plot["order"].to_numpy(float)))
        full = float(xs[-1] - xs[0])
        win = max(full / 12, 86400.0) if n_time else max(n_pts / 12, 5.0)
        ends = np.searchsorted(xs, xs + win, side="right")
        best = int(np.argmax(ends - np.arange(len(xs))))
        n_in = int(ends[best] - best)
        lo, hi = float(xs[best]), float(xs[best] + win)
        pad = win * 0.05
        if n_in >= n_pts:
            busiest_note = "All plotted transactions fall inside the busiest period, so this is the same as the full timeline."
        else:
            if n_time:
                rng = [pd.to_datetime(v, unit="s").strftime("%Y-%m-%d %H:%M:%S") for v in (lo - pad, hi + pad)]
                busiest_note = (f"Zoomed to {pd.to_datetime(lo, unit='s'):%d %b %Y} - {pd.to_datetime(hi, unit='s'):%d %b %Y} (UTC), "
                                f"which holds {n_in:,} of the {n_pts:,} plotted transactions. Choose Full timeline to return.")
            else:
                rng = [lo - pad, hi + pad]
                busiest_note = (f"Zoomed to processing positions {lo:.0f}-{hi:.0f}, which hold {n_in:,} of the {n_pts:,} "
                                f"plotted transactions. Choose Full timeline to return.")
            fig.update_xaxes(range=rng)

    fig.update_layout(
        margin=dict(l=8, r=16, t=34, b=8), showlegend=False, hovermode="closest", dragmode="zoom",
        hoverlabel=dict(bgcolor="#0F141B", bordercolor="#3B4A60", align="left", namelength=0,
                        font=dict(size=12.5, color=TEXT, family="Segoe UI, Arial, sans-serif")),
        modebar=dict(orientation="h", bgcolor="rgba(0,0,0,0)", color=MUTED, activecolor=TEXT),
        uirevision=f"{focus}|{scale}|{','.join(shown)}",   # keeps your zoom when you click a transaction
    )
    chart_config = {"displaylogo": False, "scrollZoom": False,
                    "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
                    "toImageButtonOptions": {"filename": "bittrace_transaction_timeline"}}
    try:
        st.plotly_chart(fig, width="stretch", config=chart_config, key="timeline_chart",
                        on_select="rerun", selection_mode="points")
    except TypeError:   # older Streamlit without chart selection: the "Inspect a transaction" box below still works
        st.plotly_chart(fig, width="stretch", config=chart_config)
    if busiest_note:
        st.caption(busiest_note)

    # ------------------------------------------------------------ scale explanation
    if use_log:
        note = ("<b>Logarithmic scale:</b> line length grows with the number of digits in the value, so tiny and huge "
                "transactions are both visible. A line twice as long is <b>not</b> twice the BTC - read the values from the "
                "axis labels or the tooltip.")
    elif log_axis:
        note = ("<b>Linear scale</b> (logarithmic is unavailable because none of the plotted transactions has a value above "
                "0 BTC): line length is proportional to BTC.")
    else:
        note = ("<b>Linear scale:</b> line length is proportional to BTC, so one very large transaction can make small ones "
                "look tiny. Switch to <b>Logarithmic</b>, or use <b>Busiest period</b> / drag on the chart to zoom in.")
    if n_zero:
        note += (f" {n_zero:,} transaction{'s' if n_zero != 1 else ''} with a value of 0 BTC "
                 f"{'have' if n_zero != 1 else 'has'} no line length and appear as a dot on the centre line.")
    st.markdown(f'<div class="bt-ch-note">{note}</div>', unsafe_allow_html=True)

    # ------------------------------------------------------------ selected transaction
    if selected:
        s = plot[plot["txid"] == selected].iloc[0]
        color = RELATION_COLOR[s["relation"]]
        st.markdown(
            f'<div class="bt-sel" style="--c:{color}"><div class="bt-sel-h">Selected transaction</div><div class="bt-sel-grid">'
            f'<div><div class="bt-sel-k">Direction</div><div class="bt-sel-v" style="color:{color}">{html.escape(s["relation"])}'
            f'<br><small>{html.escape(RELATION_HELP[s["relation"]])}</small></div></div>'
            f'<div><div class="bt-sel-k">Block time (UTC)</div><div class="bt-sel-v">{html.escape(str(s["when"]))}</div></div>'
            f'<div><div class="bt-sel-k">Value (outputs total)</div><div class="bt-sel-v">{html.escape(s["value_text"])}</div></div>'
            f'<div><div class="bt-sel-k">Inputs / outputs</div><div class="bt-sel-v">{int(s["n_inputs"])} / {int(s["n_outputs"])}</div></div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        st.code(selected, language=None)
    else:
        st.markdown('<div class="bt-sel-hint">Hover over a line to preview a transaction, or <b>click</b> it to pin its full '
                    'details here. You can also pick any transaction from the <b>Inspect a transaction</b> box further down.</div>',
                    unsafe_allow_html=True)

# ---------------------------------------------------------------- table
st.subheader("Transactions")
if n_time:
    table = view.sort_values(["has_time", "time", "order"], ascending=[False, False, True])
else:
    table = view.sort_values("order")
display = pd.DataFrame({
    "#": table["order"],
    "Transaction ID": table["short_txid"],
    "Block time (UTC)": table["time_text"],
    "Relation": table["relation"],
    "Inputs": table["n_inputs"],
    "Outputs": table["n_outputs"],
    "Output total (BTC)": table["value_btc"],
})
st.dataframe(
    display, width="stretch", hide_index=True, height=min(520, 38 + 35 * len(display)),
    column_config={
        "#": st.column_config.NumberColumn("#", width="small", help="Order in which BitTrace processed the transaction"),
        "Transaction ID": st.column_config.TextColumn("Transaction ID", width="medium",
                                                      help="Shortened; select a transaction below for the full ID"),
        "Block time (UTC)": st.column_config.TextColumn("Block time (UTC)", width="medium",
                                                        help="n/a = no block time available"),
        "Relation": st.column_config.TextColumn("Relation", width="small"),
        "Inputs": st.column_config.NumberColumn("Inputs", width="small", format="%d"),
        "Outputs": st.column_config.NumberColumn("Outputs", width="small", format="%d"),
        "Output total (BTC)": st.column_config.NumberColumn("Output total (BTC)", width="medium", format="%.8f"),
    },
)
st.caption("Transaction IDs are shortened so the table stays readable. "
           + ("Sorted newest first." if n_time else "Listed in processing order."))

# ---------------------------------------------------------------- one transaction in full
st.subheader("Inspect a transaction")
by_id = {t["txid"]: t for t in result.get("txs", [])}
order_of = dict(zip(df["txid"], df["order"]))
relation_of = dict(zip(df["txid"], df["relation"]))
choice = st.selectbox(
    "Transaction", list(table["txid"]),
    format_func=lambda t: f"#{order_of[t]}  {short_id(t, 12, 8)}  ({relation_of[t]})",
)
if choice:
    st.markdown("Full transaction ID (use the copy button):")
    st.code(choice, language=None)
    tx = by_id.get(choice, {})
    left, right = st.columns(2)
    for col, title, items in ((left, "Inputs (senders)", tx.get("inputs") or []),
                              (right, "Outputs (recipients)", tx.get("outputs") or [])):
        col.markdown(f"**{title}**")
        if items:
            col.dataframe(
                pd.DataFrame({"Address": [i.get("address") or "(no address)" for i in items],
                              "BTC": [i.get("value_btc") for i in items]}),
                hide_index=True, width="stretch",
                column_config={"BTC": st.column_config.NumberColumn("BTC", format="%.8f")},
            )
        else:
            col.caption("None recorded.")