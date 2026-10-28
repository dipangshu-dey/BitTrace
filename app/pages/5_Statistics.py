from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import config
from db import database as db
from ui_theme import apply_theme, metric_cards, style_figure, RISK_COLOR
from core.dashboard_data import (BANDS, BAND_LABEL, PATTERN_LABEL, band_counts, band_ranges_text, investigation_status,
                                 pattern_counts, score_histogram, select_ids, short_id)

st.set_page_config(page_title="Statistics - BitTrace", layout="wide")
apply_theme()
st.title("Aggregate Statistics")

try:
    summaries = db.get_investigation_summaries()
    score_rows = db.get_score_rows()
    pattern_rows = db.get_pattern_counts()
except Exception as exc:
    st.error(f"The statistics could not be loaded from the database: {exc}")
    st.stop()

if not summaries:
    st.info("No investigations yet - nothing to summarise. Run one on the **Investigate** page.")
    st.stop()

# ---------------------------------------------------------------- scope
SCOPES = {
    "All saved investigations": "all",
    "Latest run of each address": "latest",
    "A single investigation": "single",
}
s1, s2 = st.columns([3, 2])
scope_label = s1.radio("Include", list(SCOPES), horizontal=True,
                       help="Investigating the same address again saves a new investigation. "
                            "'Latest run' counts each address once, using its newest completed run.")
scope = SCOPES[scope_label]
single_id = None
if scope == "single":
    options = [r["id"] for r in summaries]
    first_done = next((i for i, r in enumerate(summaries) if r["n_scored"]), 0)  # default to the newest completed run
    single_id = s2.selectbox("Investigation", options, index=first_done,
                             format_func=lambda i: next(f"#{r['id']} | {short_id(r['root_address'], 8, 6)} | {r['created_at'][:16]}"
                                                         for r in summaries if r["id"] == i))
ids = select_ids(summaries, scope, single_id)
in_scope = [r for r in summaries if r["id"] in set(ids)]

distinct = len({r["root_address"] for r in summaries})
if scope == "all" and len(summaries) > distinct:
    st.info(f"{len(summaries) - distinct} of the {len(summaries)} saved investigations repeat an address that was "
            f"already investigated, so its addresses are counted once per run. Choose "
            f"**Latest run of each address** to count each investigated address once.")

if not ids:
    st.warning("There are no completed investigations in this selection, so there is nothing to chart.")
    st.stop()

bands = band_counts(score_rows, ids)
patterns = pattern_counts(pattern_rows, ids)
n_scored = sum(bands.values())
n_patterns = sum(patterns.values())
incomplete = sum(1 for r in in_scope if investigation_status(r) == "Incomplete")

# ---------------------------------------------------------------- summary cards
ranges = band_ranges_text().split(" | ")
metric_cards([
    ("Investigations", f"{len(ids):,}", "in this selection"),
    ("Addresses scored", f"{n_scored:,}", "risk-score records"),
    ("High risk", f"{bands['high']:,}", ranges[2], RISK_COLOR["high"]),
    ("Medium risk", f"{bands['medium']:,}", ranges[1], RISK_COLOR["medium"]),
    ("Low risk", f"{bands['low']:,}", ranges[0], RISK_COLOR["low"]),
    ("Patterns detected", f"{n_patterns:,}", "instances"),
])
if n_scored == 0:
    st.warning("The selected investigations have no stored risk scores yet.")
    st.stop()

log_axis = st.checkbox("Logarithmic count axis on the risk charts", value=False,
                       help="Counts are very uneven (for example thousands of low-risk addresses and a handful of "
                            "high-risk ones). A log axis makes the small groups visible. Zero counts cannot be drawn on a log axis.")

# ---------------------------------------------------------------- risk distribution + patterns
left, right = st.columns(2)

with left:
    st.subheader("Risk distribution")
    st.caption("Number of scored addresses in each risk band. The label above each bar is the count and its share of all scored addresses.")
    order = ["low", "medium", "high"]
    range_index = {"low": 0, "medium": 1, "high": 2}
    texts = []
    for b in order:
        n = bands[b]
        pct = 100.0 * n / n_scored
        texts.append(f"{n:,}<br>({'<0.1' if 0 < pct < 0.1 else f'{pct:.1f}'}%)")
    fig = go.Figure(go.Bar(
        x=[f"{BAND_LABEL[b]}<br>({ranges[range_index[b]].split(' ', 1)[1]})" for b in order],
        y=[bands[b] for b in order],
        marker_color=[RISK_COLOR[b] for b in order],
        text=texts, textposition="outside", cliponaxis=False,
        customdata=[[BAND_LABEL[b], bands[b], 100.0 * bands[b] / n_scored] for b in order],
        hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]:,} addresses (%{customdata[2]:.2f}% of scored)<extra></extra>",
    ))
    style_figure(fig, height=380)
    fig.update_yaxes(title="Addresses", type="log" if log_axis else "linear",
                     range=None if log_axis else [0, max(bands.values()) * 1.22])
    fig.update_layout(showlegend=False, bargap=0.35)
    st.plotly_chart(fig, width="stretch")
    if bands["medium"] == 0 and bands["high"] == 0:
        st.caption("All scored addresses in this selection are low risk.")

with right:
    st.subheader("Detected patterns")
    st.caption("How many times each suspicious pattern was detected. Each flagged hub, chain, cycle or transaction "
               "counts as one instance. Zero means none were detected.")
    keys = sorted(patterns, key=lambda k: (-patterns[k], k))
    palette = {"fan_in": "#3B9EBF", "fan_out": "#7B6FD0", "coinjoin": "#D98E04",
               "peel_chain": "#2E8B57", "circular_flow": "#B5486B"}
    fig2 = go.Figure(go.Bar(
        y=[PATTERN_LABEL.get(k, k) for k in keys], x=[patterns[k] for k in keys], orientation="h",
        marker_color=[palette.get(k, "#8B98A9") for k in keys],
        text=[f"{patterns[k]:,}" for k in keys], textposition="outside", cliponaxis=False,
        hovertemplate="<b>%{y}</b>: %{x:,} detected<extra></extra>",
    ))
    style_figure(fig2, height=380)
    fig2.update_yaxes(autorange="reversed", title=None)
    fig2.update_xaxes(title="Detected instances", range=[0, max(max(patterns.values()), 1) * 1.18])
    fig2.update_layout(showlegend=False, bargap=0.35)
    st.plotly_chart(fig2, width="stretch")

# ---------------------------------------------------------------- score distribution
st.subheader("Risk-score distribution")
st.caption(f"How the risk scores are spread from 0 to {config.RISK_SCORE_MAX}, in bins of 5 points. "
           f"Dashed lines mark the band boundaries ({band_ranges_text()}). "
           f"When a few bars are far taller than the rest, switch on the logarithmic axis above to see the small ones.")
hist = score_histogram(score_rows, ids)
fig3 = go.Figure()
for b in order:
    sub = hist[hist["band"] == b]
    fig3.add_trace(go.Bar(
        x=sub["bin_start"] + 2.5, y=sub["count"], width=4.6, name=BAND_LABEL[b], marker_color=RISK_COLOR[b],
        customdata=sub[["label", "count"]].values,
        hovertemplate=f"<b>Score %{{customdata[0]}}</b><br>%{{customdata[1]:,}} addresses<br>{BAND_LABEL[b]}<extra></extra>",
    ))
for edge, label in ((config.RISK_BAND_MEDIUM, "Medium starts"), (config.RISK_BAND_HIGH, "High starts")):
    fig3.add_vline(x=edge, line_dash="dash", line_color="#8B98A9", line_width=1,
                   annotation_text=f"{label} ({edge})", annotation_position="top right", annotation_font_size=11)
style_figure(fig3, height=380)
fig3.update_xaxes(title="Risk score", range=[0, config.RISK_SCORE_MAX], dtick=10)
fig3.update_yaxes(title="Addresses", type="log" if log_axis else "linear")
fig3.update_layout(barmode="overlay", margin=dict(l=10, r=10, t=44, b=10),
                   legend=dict(orientation="h", y=1.12, yanchor="bottom", x=0))
st.plotly_chart(fig3, width="stretch")

# ---------------------------------------------------------------- per investigation
st.subheader("Risk by investigation")
st.caption("The same band counts for each investigation in this selection.")
rows = [{"ID": r["id"], "Investigated address": short_id(r["root_address"], 10, 8), "Date (UTC)": r["created_at"],
         "Status": investigation_status(r), "Addresses scored": r["n_scored"], "High": r["n_high"],
         "Medium": r["n_medium"], "Low": r["n_low"]} for r in in_scope]
st.dataframe(
    pd.DataFrame(rows), width="stretch", hide_index=True, height=min(420, 38 + 35 * len(rows)),
    column_config={"ID": st.column_config.NumberColumn("ID", width="small", format="%d"),
                   **{k: st.column_config.NumberColumn(k, format="%d") for k in ("Addresses scored", "High", "Medium", "Low")}},
)
if incomplete:
    st.caption(f"{incomplete} investigation(s) in this selection are incomplete (no scores saved) and contribute no addresses.")
