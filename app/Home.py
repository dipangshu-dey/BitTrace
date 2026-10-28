"""
BitTrace v2 - Streamlit dashboard entry point.

Run with:  streamlit run app/Home.py
(run from the project root so the sys.path fix-up below can find config.py
and the core/ and db/ packages)
"""

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))

import streamlit as st
import config
from db import database
from ui_theme import apply_theme

st.set_page_config(page_title=config.APP_TITLE, page_icon=str(Path(__file__).resolve().parent.parent / "assets" / "bittrace.png"), layout="wide")
apply_theme()

database.init_db()

st.title("BitTrace")
st.caption(config.APP_TITLE)

st.markdown(
    """
BitTrace is a Bitcoin transaction forensics tool built around four objectives:

| Objective | What it does | Module |
|---|---|---|
| **1. Address clustering** | Groups addresses controlled by the same wallet via common-input-ownership + change-address detection | `core/clustering.py` |
| **2. Pattern detection** | Flags peel chains, fan-out/fan-in hubs, CoinJoin mixing, and circular flows | `core/pattern_detector.py` |
| **3. Risk scoring** | Explainable 0-100 risk score with a full signal breakdown per address | `core/risk_engine.py` |
| **4. Entity attribution** | Matches addresses against threat-intel lists and infers entity type (exchange, mixer, etc.) from behavior | `core/entity_attribution.py` |

Use the sidebar to navigate:
- **Investigate** - start a new investigation on a root address
- **Graph Explorer** - visualize the fund-flow graph for a past investigation
- **Timeline** - see transaction activity over time
- **History** - browse all past investigations
- **Statistics** - aggregate stats across everything BitTrace has seen
- **AI Assistant** - ask questions about an investigation in plain English (local Ollama + RAG)
    """
)

recent = database.list_investigations()[:5]
if recent:
    st.subheader("Recent investigations")
    for inv in recent:
        st.write(f"**#{inv['id']}** - `{inv['root_address']}` - {inv['created_at']}")
else:
    st.info("No investigations yet. Head to the **Investigate** page in the sidebar to start one.")

st.info(
    "Threat-intel lists ship with a **small set of real, sourced** addresses "
    "(verified OFAC/WannaCry/Silk Road cases - see `core/threat_intel.py` for citations), "
    "not a comprehensive sanctions database. See the README to pull the full OFAC SDN feed."
)

st.markdown(
    """
<style>
.bt-footer { margin: 3rem auto 0 auto; padding: 1.6rem 1rem 0.4rem 1rem; max-width: 560px;
             text-align: center; border-top: 1px solid #263041; }
.bt-footer-name { color: #3B9EBF; font-size: 1.05rem; font-weight: 600; letter-spacing: 0.18em;
                  text-transform: uppercase; }
.bt-footer-tag { color: #8B98A9; font-size: 0.78rem; letter-spacing: 0.08em; margin-top: 0.15rem; }
.bt-footer-rule { width: 48px; height: 2px; background: #3B9EBF; margin: 0.9rem auto 0.8rem auto;
                  opacity: 0.8; }
.bt-footer-by { color: #C9D4E0; font-size: 0.9rem; }
.bt-footer-by b { color: #E6EDF3; font-weight: 600; }
.bt-footer-edu { color: #8B98A9; font-size: 0.78rem; letter-spacing: 0.04em; margin-top: 0.25rem; }
</style>
<div class="bt-footer">
  <div class="bt-footer-name">BitTrace</div>
  <div class="bt-footer-tag">Bitcoin Transaction Forensics</div>
  <div class="bt-footer-rule"></div>
  <div class="bt-footer-by">Created by <b>Dipangshu Dey</b></div>
  <div class="bt-footer-edu">MSc Cyber Security &nbsp;|&nbsp; NFSU</div>
</div>
""",
    unsafe_allow_html=True,
)