from pathlib import Path
import json
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import streamlit as st
from ui_theme import apply_theme, metric_cards, pdf_download_button, RISK_COLOR
from db import database
from core.dashboard_data import (BAND_LABEL, PATTERN_LABEL, PATTERN_ORDER, band_ranges_text, history_frame,
                                 investigation_label, investigation_status, risk_summary, short_id)
from core.report_generator import build_pdf_report, result_from_database

st.set_page_config(page_title="History - BitTrace", layout="wide")
apply_theme()
st.title("Investigation History")
st.caption("Saved investigations are local to this BitTrace installation. "
           f"Risk bands: {band_ranges_text()}.")

try:
    summaries = database.get_investigation_summaries()
except Exception as exc:  # unreadable or locked database - say so instead of a stack trace
    st.error(f"The investigation history could not be loaded: {exc}")
    st.stop()

if not summaries:
    st.info("No investigations yet. Run one on the **Investigate** page and it will appear here.")
    st.stop()

# ---------------------------------------------------------------- overview cards
completed = sum(1 for r in summaries if investigation_status(r) == "Completed")
with_high = sum(1 for r in summaries if r["n_high"])
metric_cards([
    ("Investigations", f"{len(summaries):,}", f"{len({r['root_address'] for r in summaries}):,} distinct addresses"),
    ("Completed", f"{completed:,}", "results saved", "#2ca02c"),
    ("Incomplete", f"{len(summaries) - completed:,}", "no results saved", "#ff9f1c"),
    ("With high-risk addresses", f"{with_high:,}", "at least one scored High", RISK_COLOR["high"]),
])

# ---------------------------------------------------------------- filters + table
f1, f2 = st.columns([3, 2])
query = f1.text_input("Search", placeholder="Address, investigation ID or note text").strip().lower()
status_filter = f2.multiselect("Status", ["Completed", "Incomplete"], default=["Completed", "Incomplete"])

visible = [
    r for r in summaries
    if investigation_status(r) in status_filter
    and (not query or query in r["root_address"].lower() or query in str(r["id"])
         or query in (r.get("notes") or "").lower())
]
if not visible:
    st.warning("No investigations match the current search and filter.")
    st.stop()

table = history_frame(visible)
table.insert(2, "Address (short)", table["Investigated address"].map(lambda a: short_id(a, 10, 8)))
shown = table.drop(columns=["Investigated address", "Notes", "Stored txs (address)", "Max score",
                            "Clusters", "Patterns", "Hops"]).copy()
shown["Date (UTC)"] = shown["Date (UTC)"].astype(str).str[:16]  # to the minute; full time is in the details panel


def _band_style(value: str) -> str:
    colour = {BAND_LABEL["high"]: RISK_COLOR["high"], BAND_LABEL["medium"]: RISK_COLOR["medium"],
              BAND_LABEL["low"]: RISK_COLOR["low"]}.get(value)
    return f"color: {colour}; font-weight: 600" if colour else ""


st.dataframe(
    shown.style.map(_band_style, subset=["Highest band"]),
    width="stretch", hide_index=True, height=min(480, 38 + 35 * len(shown)),
    column_config={  # explicit pixel widths so every column fits without sideways scrolling
        "ID": st.column_config.NumberColumn("ID", width=50, format="%d"),
        "Address (short)": st.column_config.TextColumn("Investigated address", width=160),
        "Date (UTC)": st.column_config.TextColumn("Date (UTC)", width=130),
        "Status": st.column_config.TextColumn("Status", width=90),
        "Addresses scored": st.column_config.NumberColumn("Scored", width=70, format="%d", help="Addresses scored"),
        "Highest band": st.column_config.TextColumn("Highest risk", width=105),
        "High": st.column_config.NumberColumn("High", width=60, format="%d", help="Addresses scored High"),
        "Medium": st.column_config.NumberColumn("Medium", width=75, format="%d"),
        "Low": st.column_config.NumberColumn("Low", width=60, format="%d"),
    },
)
st.caption("Newest first. 'Incomplete' means the run stopped before its scores were saved. "
           "Pick an investigation below for the full address, notes, findings and a PDF report.")

# ---------------------------------------------------------------- one investigation
st.subheader("Investigation details")
by_id = {r["id"]: r for r in visible}
selected_id = st.selectbox("Investigation", list(by_id), format_func=lambda i: investigation_label(by_id[i]))
sel = by_id[selected_id]
status = investigation_status(sel)

metric_cards([
    ("Status", status, f"hops traced: {sel['max_hops']}", "#2ca02c" if status == "Completed" else "#ff9f1c"),
    ("Addresses scored", f"{sel['n_scored']:,}", ""),
    ("High risk", f"{sel['n_high']:,}", band_ranges_text().split(" | ")[2], RISK_COLOR["high"]),
    ("Medium risk", f"{sel['n_medium']:,}", band_ranges_text().split(" | ")[1], RISK_COLOR["medium"]),
    ("Low risk", f"{sel['n_low']:,}", band_ranges_text().split(" | ")[0], RISK_COLOR["low"]),
])
st.markdown(f"**Investigated address:** `{sel['root_address']}`")
st.markdown(f"**Date (UTC):** {sel['created_at']}  |  **Risk summary:** {risk_summary(sel)}  |  "
            f"**Clusters:** {sel['n_clusters']:,}  |  **Patterns detected:** {sel['n_patterns']:,}")
st.markdown(f"**Notes:** {(sel.get('notes') or '').strip() or '-'}")
if sel["stored_root_txs"]:
    st.caption(f"{sel['stored_root_txs']:,} transactions involving this address are stored locally "
               f"(shared by every investigation of the address; not the exact set analysed in this run).")

if status == "Incomplete":
    st.warning("No results were saved for this investigation, so there is nothing to show or report. "
               "It can be deleted below, or run again from the **Investigate** page.")
else:
    # ---- findings
    try:
        score_rows = database.get_risk_scores_for_investigation(selected_id)
        top = []
        for s in score_rows[:10]:
            try:
                signals = ", ".join(b.get("signal", "?") for b in (json.loads(s["explanation_json"] or "{}") or {}).get("breakdown", []))
            except (TypeError, ValueError):
                signals = ""
            top.append({"Address": s["address"], "Score": float(s["score"]),
                        "Risk band": BAND_LABEL.get(s["band"], s["band"]), "Signals": signals or "none"})
        st.markdown("**Highest-scoring addresses**")
        st.dataframe(
            pd.DataFrame(top).style.map(_band_style, subset=["Risk band"]),
            width="stretch", hide_index=True,
            column_config={"Score": st.column_config.NumberColumn("Score", format="%.0f", width="small"),
                           "Address": st.column_config.TextColumn("Address", width="large"),
                           "Risk band": st.column_config.TextColumn("Risk band", width="small"),
                           "Signals": st.column_config.TextColumn("Signals", width="large")},
        )
        pattern_rows = database.get_patterns_for_investigation(selected_id)
        if pattern_rows:
            counts = {}
            for p in pattern_rows:
                counts[p["pattern_type"]] = counts.get(p["pattern_type"], 0) + 1
            st.markdown("**Detected patterns**")
            st.dataframe(
                pd.DataFrame([{"Pattern": PATTERN_LABEL.get(k, k), "Instances": counts[k]}
                              for k in list(PATTERN_ORDER) + [k for k in counts if k not in PATTERN_ORDER] if k in counts]),
                hide_index=True, width="stretch",
                column_config={"Instances": st.column_config.NumberColumn("Instances", format="%d")},
            )
        else:
            st.caption("No transaction patterns were detected in this investigation.")
    except Exception as exc:
        st.error(f"Some details of this investigation could not be loaded: {exc}")

    # ---- PDF report
    st.markdown("**Report**")
    live = st.session_state.get("last_result")
    use_live = bool(live) and live.get("investigation_id") == selected_id
    if use_live:
        st.caption("This investigation is still open in this session, so the report includes its transactions and graph.")
        pdf_download_button(lambda: build_pdf_report(live), f"pdf-live-{selected_id}",
                            f"BitTrace_investigation_{selected_id}_report.pdf")
    else:
        st.caption("Built from the stored records (scores, patterns, clusters, notes). Transactions and the fund-flow "
                   "graph are not saved per investigation, so they are not included.")
        pdf_download_button(lambda: build_pdf_report(result_from_database(selected_id)), f"pdf-stored-{selected_id}",
                            f"BitTrace_investigation_{selected_id}_report.pdf")

# ---------------------------------------------------------------- delete
st.divider()
with st.expander("Delete this investigation"):
    st.write("Removes this investigation's clusters, patterns and risk scores. Shared blockchain transaction data is kept.")
    confirm = st.checkbox(f"Yes, permanently delete investigation #{selected_id}", key=f"confirm-delete-{selected_id}")
    if st.button("Delete investigation", type="secondary", disabled=not confirm, key=f"delete-{selected_id}"):
        database.delete_investigation(selected_id)
        if st.session_state.get("last_result", {}).get("investigation_id") == selected_id:
            st.session_state.pop("last_result", None)
        for k in (f"pdf-live-{selected_id}", f"pdf-stored-{selected_id}"):
            st.session_state.pop(k, None)
        st.success(f"Investigation #{selected_id} deleted. Shared blockchain transaction data was retained.")
        st.rerun()
