from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import html

import streamlit as st
from ui_theme import apply_theme, pdf_download_button, RISK_COLOR, RISK_LABEL
import config
from core.pipeline import run_investigation, FetchError
from core.validation import is_valid_btc_address
from core.report_generator import export_all, build_pdf_report
from core.demo_data import build_demo_transactions

st.set_page_config(page_title="Investigate - BitTrace", layout="wide")
apply_theme()

# ---------------------------------------------------------------------------
# Page-specific styling (scoped to .bt-* classes and the form on this page only)
# ---------------------------------------------------------------------------
st.markdown(
    """
<style>
.block-container { max-width: 1240px !important; }
:root { --bt-bg:#0B1220; --bt-card:#111A2B; --bt-card2:#0E1626; --bt-line:#1F2C42; --bt-line2:#2A3A55;
        --bt-text:#E6EDF5; --bt-mute:#8A9BB4; --bt-cyan:#3BC4D9; --bt-blue:#3B82C4; --bt-teal:#2BB5A0; }

/* ---------- hero ---------- */
.bt-hero { position:relative; display:flex; justify-content:space-between; align-items:center; gap:1.5rem; flex-wrap:wrap;
           background:linear-gradient(180deg,#111C30 0%,#0E1626 100%); border:1px solid var(--bt-line);
           border-radius:10px; padding:1.5rem 1.8rem; margin-bottom:1.4rem; overflow:hidden; }
.bt-hero::before { content:""; position:absolute; left:0; top:0; bottom:0; width:4px;
                   background:linear-gradient(180deg,var(--bt-cyan),var(--bt-blue)); }
.bt-eyebrow { color:var(--bt-cyan); font-size:0.72rem; font-weight:600; letter-spacing:0.16em; text-transform:uppercase; }
.bt-title { color:var(--bt-text); font-size:1.85rem; font-weight:650; letter-spacing:-0.02em; margin:0.2rem 0 0.35rem 0; line-height:1.2; }
.bt-sub { color:var(--bt-mute); font-size:0.93rem; line-height:1.55; max-width:44rem; }
.bt-chips { display:flex; gap:0.5rem; flex-wrap:wrap; }
.bt-chip { display:flex; align-items:center; gap:0.45rem; border:1px solid var(--bt-line2); background:rgba(59,196,217,0.06);
           color:#BFD0E6; font-size:0.78rem; padding:0.35rem 0.7rem; border-radius:999px; white-space:nowrap; }
.bt-chip i { width:7px; height:7px; border-radius:50%; background:var(--bt-teal); display:inline-block; }

/* ---------- section headers ---------- */
.bt-sec { display:flex; align-items:baseline; justify-content:space-between; gap:1rem; flex-wrap:wrap;
          margin:1.9rem 0 0.8rem 0; padding-bottom:0.55rem; border-bottom:1px solid var(--bt-line); }
.bt-sec-t { color:var(--bt-text); font-size:1.08rem; font-weight:620; letter-spacing:-0.005em; }
.bt-sec-t span { color:var(--bt-cyan); margin-right:0.5rem; font-weight:500; font-size:0.8rem; letter-spacing:0.1em; }
.bt-sec-d { color:var(--bt-mute); font-size:0.82rem; }

/* ---------- workspace form ---------- */
div[data-testid="stForm"] { background:var(--bt-card); border:1px solid var(--bt-line) !important; border-radius:10px;
                            padding:1.5rem 1.6rem 1.3rem 1.6rem; box-shadow:0 8px 24px rgba(0,0,0,0.25); }
div[data-testid="stForm"] label p { color:#C3D0E3; font-size:0.82rem; font-weight:600; letter-spacing:0.02em; }
div[data-testid="stForm"] div[data-baseweb="input"], div[data-testid="stForm"] div[data-baseweb="textarea"] {
    background:var(--bt-card2) !important; border:1px solid var(--bt-line2) !important; border-radius:6px !important;
    transition:border-color .15s, box-shadow .15s; }
div[data-testid="stForm"] div[data-baseweb="input"]:focus-within, div[data-testid="stForm"] div[data-baseweb="textarea"]:focus-within {
    border-color:var(--bt-cyan) !important; box-shadow:0 0 0 3px rgba(59,196,217,0.15); }
div[data-testid="stForm"] input { font-family:"Cascadia Mono",Consolas,monospace !important; font-size:0.92rem !important; }
div[data-testid="stFormSubmitButton"] > button { width:100%; min-height:3rem; font-size:1rem; font-weight:600; letter-spacing:0.02em;
    border-radius:6px; border:1px solid #5AD3E6; color:#06121C;
    background:linear-gradient(180deg,#46CCE0,#2FA9C4); box-shadow:0 4px 14px rgba(59,196,217,0.25);
    transition:transform .12s, box-shadow .12s, filter .12s; }
div[data-testid="stFormSubmitButton"] > button:hover { background:linear-gradient(180deg,#5AD6E9,#38B5CF); color:#06121C;
    transform:translateY(-1px); box-shadow:0 6px 18px rgba(59,196,217,0.35); border-color:#7FE0F0; }
.bt-demo-hint { color:var(--bt-mute); font-size:0.78rem; line-height:1.45; }

/* ---------- case banner ---------- */
.bt-case { display:flex; flex-wrap:wrap; gap:1.6rem 2.4rem; align-items:center; background:var(--bt-card);
           border:1px solid var(--bt-line); border-radius:10px; padding:1rem 1.4rem; }
.bt-case-k { color:var(--bt-mute); font-size:0.7rem; letter-spacing:0.12em; text-transform:uppercase; }
.bt-case-v { color:var(--bt-text); font-size:1.05rem; font-weight:600; margin-top:0.15rem; }
.bt-case-addr { font-family:"Cascadia Mono",Consolas,monospace; font-size:0.9rem; color:#CFE3F5; word-break:break-all;
                background:var(--bt-card2); border:1px solid var(--bt-line2); border-radius:6px; padding:0.3rem 0.6rem; margin-top:0.15rem; display:inline-block; }
.bt-note { color:var(--bt-mute); font-size:0.84rem; line-height:1.55; margin:0.7rem 0 0 0; }

/* ---------- metric cards ---------- */
.bt-cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:0.9rem; margin-top:0.9rem; }
.bt-card { position:relative; background:var(--bt-card); border:1px solid var(--bt-line); border-radius:10px; padding:1rem 1.15rem 1rem 1.15rem;
           transition:border-color .15s, transform .15s, box-shadow .15s; overflow:hidden; }
.bt-card:hover { border-color:var(--c); transform:translateY(-2px); box-shadow:0 8px 20px rgba(0,0,0,0.3); }
.bt-card::after { content:""; position:absolute; left:0; right:0; bottom:0; height:2px; background:var(--c); opacity:0.7; }
.bt-card-top { display:flex; justify-content:space-between; align-items:center; }
.bt-card-k { color:var(--bt-mute); font-size:0.72rem; letter-spacing:0.1em; text-transform:uppercase; font-weight:600; }
.bt-ico { width:1.9rem; height:1.9rem; border-radius:7px; display:flex; align-items:center; justify-content:center;
          background:color-mix(in srgb, var(--c) 16%, transparent); color:var(--c); font-size:0.95rem; }
.bt-card-v { color:var(--bt-text); font-size:2rem; font-weight:650; letter-spacing:-0.02em; margin-top:0.45rem; line-height:1.1; }
.bt-card-s { color:var(--bt-mute); font-size:0.76rem; margin-top:0.2rem; }

/* ---------- risk table ---------- */
.bt-tablewrap { background:var(--bt-card); border:1px solid var(--bt-line); border-radius:10px; overflow:hidden; }
.bt-scroll { max-height:520px; overflow:auto; }
table.bt-t { width:100%; border-collapse:collapse; table-layout:fixed; }
table.bt-t th { position:sticky; top:0; z-index:1; background:#0F1829; color:var(--bt-mute); font-size:0.7rem; letter-spacing:0.1em;
                text-transform:uppercase; font-weight:600; padding:0.7rem 0.9rem; border-bottom:1px solid var(--bt-line2); text-align:left; }
table.bt-t td { padding:0.6rem 0.9rem; border-bottom:1px solid #18243A; color:#D5E0F0; font-size:0.86rem; vertical-align:middle; }
table.bt-t tbody tr { transition:background .12s; }
table.bt-t tbody tr:hover { background:rgba(59,196,217,0.07); }
table.bt-t tbody tr:last-child td { border-bottom:none; }
table.bt-t .num { text-align:right; font-variant-numeric:tabular-nums; }
table.bt-t .addr { font-family:"Cascadia Mono",Consolas,monospace; font-size:0.82rem; word-break:break-all; color:#CFE3F5; }
.bt-badge { display:inline-flex; align-items:center; gap:0.4rem; padding:0.18rem 0.65rem; border-radius:999px; font-size:0.74rem;
            font-weight:600; border:1px solid color-mix(in srgb, var(--c) 55%, transparent);
            background:color-mix(in srgb, var(--c) 14%, transparent); color:var(--c); }
.bt-badge i { width:6px; height:6px; border-radius:50%; background:var(--c); }
.bt-sig { font-family:"Cascadia Mono",Consolas,monospace; font-size:0.78rem; color:#9FD6E0; background:rgba(59,196,217,0.08);
          border:1px solid rgba(59,196,217,0.2); border-radius:4px; padding:0.1rem 0.45rem; }
.bt-bar { height:5px; border-radius:3px; background:#1A2740; margin-top:0.35rem; overflow:hidden; }
.bt-bar b { display:block; height:100%; background:var(--c); }
.bt-tfoot { color:var(--bt-mute); font-size:0.78rem; padding:0.6rem 0.9rem; border-top:1px solid var(--bt-line); background:#0F1829; }

/* ---------- pattern bars ---------- */
.bt-pat { background:var(--bt-card); border:1px solid var(--bt-line); border-radius:10px; padding:0.6rem 1.1rem; }
.bt-pat-r { display:grid; grid-template-columns:minmax(120px,200px) 1fr 3rem; gap:0.9rem; align-items:center; padding:0.5rem 0; border-bottom:1px solid #18243A; }
.bt-pat-r:last-child { border-bottom:none; }
.bt-pat-n { color:#D5E0F0; font-size:0.86rem; }
.bt-pat-b { height:8px; background:#1A2740; border-radius:4px; overflow:hidden; }
.bt-pat-b b { display:block; height:100%; background:linear-gradient(90deg,var(--bt-blue),var(--bt-cyan)); border-radius:4px; }
.bt-pat-c { color:var(--bt-text); font-weight:600; text-align:right; font-variant-numeric:tabular-nums; }

/* ---------- export panel ---------- */
.bt-exp { background:var(--bt-card); border:1px solid var(--bt-line); border-radius:10px; padding:1rem 1.2rem; height:100%; }
.bt-exp-t { color:var(--bt-text); font-weight:620; font-size:0.98rem; }
.bt-exp-d { color:var(--bt-mute); font-size:0.82rem; line-height:1.5; margin:0.3rem 0 0.2rem 0; }
.stDownloadButton > button, .stButton > button { border-radius:6px; transition:all .15s; }
</style>
""",
    unsafe_allow_html=True,
)


def _section(num: str, title: str, desc: str = "") -> None:
    d = f'<div class="bt-sec-d">{html.escape(desc)}</div>' if desc else ""
    st.markdown(f'<div class="bt-sec"><div class="bt-sec-t"><span>{num}</span>{html.escape(title)}</div>{d}</div>',
                unsafe_allow_html=True)


def _pretty(name: str) -> str:
    return str(name).replace("_", " ").title()


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown(
    """
<div class="bt-hero">
  <div>
    <div class="bt-eyebrow">BitTrace &middot; </div>
    <div class="bt-title">BitTrace: Bitcoin Transaction Forensics and Investigation System</div>
    <div class="bt-sub">Trace a Bitcoin address across the transaction graph, cluster related addresses, detect laundering
    patterns and score every address for risk - producing an evidence-ready case file.</div>
  </div>
  <div class="bt-chips">
    <span class="bt-chip"><i></i>Address clustering</span>
    <span class="bt-chip"><i></i>Pattern detection</span>
    <span class="bt-chip"><i></i>Explainable risk scoring</span>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Investigation workspace (same fields, validation and engine call as before)
# ---------------------------------------------------------------------------
_section("01", "Investigation workspace", "Define the target and the depth of the trace")
with st.form("investigate_form"):
    root_address = st.text_input(
        "Root Bitcoin address", max_chars=100, placeholder="e.g. 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
    left, right = st.columns([1, 1], gap="large")
    with left:
        max_hops = st.slider("Max hops to trace", min_value=1, max_value=3, value=2,
                             help="1 = the address's own transactions. Each extra hop also fetches the busiest counterparties, so it takes longer.")
        use_demo_data = st.checkbox(
            "Use built-in synthetic demo data instead of live network fetch "
            "(useful if this environment has no internet access, or for a repeatable demo)",
            value=False,
        )
    with right:
        notes = st.text_area("Notes (optional)", placeholder="Case reference, investigator name, etc.", height=120)
    submitted = st.form_submit_button("Run investigation", type="primary")

if submitted:
    if not root_address and not use_demo_data:
        st.error("Enter a Bitcoin address, or check the demo-data box.")
    elif root_address and not use_demo_data and not is_valid_btc_address(root_address):
        st.error("That is not a valid Bitcoin address (the checksum failed). Check for typos or missing characters.")
    else:
        with st.spinner("Running BitTrace pipeline..."):
            synthetic_txs = None
            if use_demo_data:
                root_address = root_address or "DEMO_ROOT"
                synthetic_txs = build_demo_transactions(root_address)

            try:
                result = run_investigation(root_address, max_hops=max_hops,
                                            synthetic_txs=synthetic_txs, notes=notes)
            except FetchError as e:
                st.error(str(e))
                st.stop()
            except Exception as e:
                st.exception(e)
                st.stop()

        st.success(f"Investigation #{result['investigation_id']} complete.")
        st.session_state["last_result"] = result

# Results are drawn from session state, OUTSIDE the `if submitted:` block above, because a form
# submit button is only True on the single run that follows the click.
result = st.session_state.get("last_result")
if not result:
    st.markdown(
        '<div class="bt-note" style="text-align:center;padding:2rem 0 1rem 0;">No investigation has been run in this '
        'session yet. Enter an address above (or enable demo data) and run an investigation to see the case file here.</div>',
        unsafe_allow_html=True,
    )
else:
    meta = result.get("meta", {})
    risk_rows = sorted(result["risk_scores"].values(), key=lambda r: r["score"], reverse=True)
    n_patterns = sum(len(v) for v in result["patterns"].values())
    high_risk = sum(1 for r in risk_rows if r["band"] == "high")
    n_txs = meta.get("txs_analysed")
    if n_txs is None:
        n_txs = len(result.get("txs") or [])

    # ------------------------------------------------------------------ case overview
    _section("02", "Results overview", f"Case file for investigation #{result['investigation_id']}")
    st.markdown(
        f'<div class="bt-case"><div><div class="bt-case-k">Investigation</div>'
        f'<div class="bt-case-v">#{int(result["investigation_id"])}</div></div>'
        f'<div style="flex:1 1 320px;min-width:0"><div class="bt-case-k">Investigated address</div>'
        f'<div class="bt-case-addr">{html.escape(str(result["root_address"]))}</div></div></div>',
        unsafe_allow_html=True,
    )
    if meta.get("synthetic"):
        st.info("Demo mode: synthetic transactions, not live blockchain data.")
    elif meta.get("root_tx_total"):
        st.markdown(
            f'<div class="bt-note">Analysed {meta["txs_analysed"]:,} transactions across {meta["addresses_expanded"]} '
            f'address(es). The root address has {meta["root_tx_total"]:,} on-chain; the most recent '
            f'{meta.get("root_tx_fetched", 0):,} were used.</div>', unsafe_allow_html=True)

    cards = [
        ("Transactions analysed", f"{int(n_txs):,}", "in this analysis", "#3BC4D9", "&#8644;"),
        ("Addresses seen", f"{len(result['addresses']):,}", "unique addresses", "#3B82C4", "&#9673;"),
        ("Clusters", f"{len(result['clusters']):,}", "related address groups", "#2BB5A0", "&#9741;"),
        ("Patterns found", f"{n_patterns:,}", "behavioural findings", "#8E7CC3", "&#9672;"),
        ("High-risk addresses", f"{high_risk:,}", "band: high", RISK_COLOR.get("high", "#E05252"), "&#9650;"),
    ]
    st.markdown(
        '<div class="bt-cards">' + "".join(
            f'<div class="bt-card" style="--c:{c}"><div class="bt-card-top"><div class="bt-card-k">{html.escape(k)}</div>'
            f'<div class="bt-ico">{ic}</div></div><div class="bt-card-v">{v}</div><div class="bt-card-s">{html.escape(s)}</div></div>'
            for k, v, s, c, ic in cards) + "</div>",
        unsafe_allow_html=True,
    )

    # ------------------------------------------------------------------ risk analysis
    _section("03", "Risk analysis", f"{len(risk_rows):,} scored addresses, highest score first")
    if risk_rows:
        top_score = max(float(r["score"]) for r in risk_rows) or 1.0
        body = []
        for r in risk_rows:
            band = str(r["band"])
            color = RISK_COLOR.get(band, "#8A9BB4")
            label = RISK_LABEL.get(band, band.title())
            sig = r["breakdown"][0]["signal"] if r["breakdown"] else "-"
            width = max(2, min(100, float(r["score"]) / top_score * 100))
            body.append(
                f'<tr style="--c:{color}"><td class="addr">{html.escape(str(r["address"]))}</td>'
                f'<td class="num">{html.escape(str(r["score"]))}<div class="bt-bar"><b style="width:{width:.0f}%"></b></div></td>'
                f'<td><span class="bt-badge" style="--c:{color}"><i></i>{html.escape(str(label))}</span></td>'
                f'<td><span class="bt-sig">{html.escape(str(sig))}</span></td></tr>')
        st.markdown(
            '<div class="bt-tablewrap"><div class="bt-scroll"><table class="bt-t"><colgroup><col style="width:52%">'
            '<col style="width:14%"><col style="width:14%"><col style="width:20%"></colgroup><thead><tr><th>Address</th>'
            '<th class="num">Score</th><th>Band</th><th>Top signal</th></tr></thead><tbody>' + "".join(body) +
            f'</tbody></table></div><div class="bt-tfoot">{len(risk_rows):,} addresses &middot; band shown as classified by the risk engine</div></div>',
            unsafe_allow_html=True)
    else:
        st.info("No risk scores were produced for this investigation.")

    # ------------------------------------------------------------------ pattern findings
    counts = {k: len(v) for k, v in result["patterns"].items() if len(v)}
    if counts:
        _section("04", "Pattern findings", f"{n_patterns:,} findings across {len(counts)} pattern types")
        top = max(counts.values())
        st.markdown('<div class="bt-pat">' + "".join(
            f'<div class="bt-pat-r"><div class="bt-pat-n">{html.escape(_pretty(k))}</div>'
            f'<div class="bt-pat-b"><b style="width:{max(3, c / top * 100):.0f}%"></b></div><div class="bt-pat-c">{c:,}</div></div>'
            for k, c in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)) + "</div>", unsafe_allow_html=True)

    # ------------------------------------------------------------------ cluster analysis
    clusters = sorted(result["clusters"], key=lambda c: c.get("size", 0), reverse=True)
    if clusters:
        shown = clusters[:15]
        _section("05", "Cluster analysis", f"Largest {len(shown)} of {len(clusters):,} clusters")
        rows_html = "".join(
            f'<tr><td class="addr">{html.escape(str(c.get("root", "")))}</td><td class="num">{int(c.get("size", 0)):,}</td></tr>'
            for c in shown)
        st.markdown(
            '<div class="bt-tablewrap"><div class="bt-scroll"><table class="bt-t"><colgroup><col style="width:82%"><col style="width:18%">'
            '</colgroup><thead><tr><th>Cluster root</th><th class="num">Addresses</th></tr></thead><tbody>' + rows_html +
            '</tbody></table></div></div>', unsafe_allow_html=True)

    # ------------------------------------------------------------------ reports and exports
    _section("06", "Reports and exports", "Evidence package for this investigation")
    e1, e2 = st.columns(2, gap="medium")
    with e1:
        st.markdown('<div class="bt-exp"><div class="bt-exp-t">PDF case report</div><div class="bt-exp-d">Case details, key '
                    'findings, risk scores, high-risk addresses, graph analysis, detected patterns and transaction details '
                    'for this investigation.</div></div>', unsafe_allow_html=True)
        pdf_download_button(
            lambda: build_pdf_report(result),
            cache_key=f"pdf-live-{result['investigation_id']}",
            file_name=f"BitTrace_investigation_{result['investigation_id']}_report.pdf",
            label="Download PDF report",
        )
    with e2:
        st.markdown('<div class="bt-exp"><div class="bt-exp-t">Other export formats</div><div class="bt-exp-d">Saves the PDF, '
                    'CSV, JSON and PNG files into the reports/ folder next to the app.</div></div>', unsafe_allow_html=True)
        if st.button("Export report (PDF/CSV/JSON/PNG)", help="Saves all four files into the reports/ folder next to the app."):
            with st.spinner("Generating exports..."):
                paths = export_all(result)
            st.success("Exported:")
            for fmt, p in paths.items():
                st.write(f"- **{fmt.upper()}**: `{p}`")