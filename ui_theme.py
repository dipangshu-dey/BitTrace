"""Shared look-and-feel for every BitTrace page.

Call apply_theme() once, right after st.set_page_config(), on every page.
Pure CSS - no external fonts or network calls, so it works offline.

Also holds the small UI helpers shared by several pages: the risk-band colour
palette (the same colours the Graph Explorer uses), summary cards, a Plotly
dark-theme helper and the PDF download button.
"""

import html
import traceback
from typing import Callable, Optional, Sequence

import streamlit as st

from core.graph_view import BAND_COLOR, BAND_LABEL  # same palette as the Graph Explorer

TEXT, MUTED, GRID, PANEL, ACCENT = "#E6EDF3", "#8B98A9", "#263041", "#151B23", "#3B9EBF"
RISK_COLOR = dict(BAND_COLOR)   # high red, medium amber, low green
RISK_LABEL = dict(BAND_LABEL)   # "High risk" ... always shown as text too

_CSS = """
<style>
html, body, [class*="css"], .stApp {
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
}

/* Page container: tighter, readable width */
.block-container {
    padding-top: 2.2rem;
    padding-bottom: 3rem;
    max-width: 1180px;
}

/* Headings: understated instead of oversized */
h1 { font-size: 1.7rem !important; font-weight: 600 !important;
     letter-spacing: -0.01em; padding-bottom: 0.4rem;
     border-bottom: 1px solid #263041; margin-bottom: 1rem; }
h2 { font-size: 1.25rem !important; font-weight: 600 !important; }
h3 { font-size: 1.05rem !important; font-weight: 600 !important; }

/* Addresses, hashes, module names */
code, pre, .stCode {
    font-family: "Cascadia Mono", Consolas, "Courier New", monospace !important;
    font-size: 0.85em !important;
}
:not(pre) > code {
    background: #1B2330 !important;
    color: #C9D4E0 !important;
    border: 1px solid #263041;
    border-radius: 3px;
    padding: 0.1em 0.35em;
}

/* Alerts: flat panel with a thin accent edge */
div[data-testid="stAlert"] {
    border-radius: 3px;
    border: 1px solid #263041;
    background: #151B23;
}

/* Inputs and buttons */
.stButton > button, .stDownloadButton > button, div[data-testid="stFormSubmitButton"] > button {
    border-radius: 3px;
    border: 1px solid #3B9EBF;
    background: transparent;
    color: #E6EDF3;
    font-weight: 500;
    padding: 0.4rem 1.1rem;
}
.stButton > button:hover, .stDownloadButton > button:hover,
div[data-testid="stFormSubmitButton"] > button:hover {
    background: #3B9EBF; color: #0D1117; border-color: #3B9EBF;
}
div[data-baseweb="input"], div[data-baseweb="textarea"], div[data-baseweb="select"] > div {
    border-radius: 3px !important;
}

/* Tables and metrics */
table { font-size: 0.92rem; }
th { background: #151B23 !important; }
div[data-testid="stMetricValue"] { font-size: 1.6rem; font-weight: 600; }
div[data-testid="stMetricLabel"] { color: #8B98A9; }
div[data-testid="stExpander"] { border: 1px solid #263041; border-radius: 3px; }

/* Sidebar wordmark above the page list */
section[data-testid="stSidebar"] { border-right: 1px solid #263041; }
[data-testid="stSidebarNav"]::before {
    content: "BitTrace";
    display: block;
    padding: 1.1rem 1.1rem 0.2rem 1.1rem;
    font-size: 1.15rem; font-weight: 600; letter-spacing: 0.02em; color: #E6EDF3;
}
[data-testid="stSidebarNav"]::after {
    content: "BitTrace: Bitcoin Transaction Forensics and Investigation System";
    display: block;
    padding: 0 1.1rem 0.9rem 1.1rem;
    font-size: 0.75rem; color: #8B98A9; text-transform: uppercase; letter-spacing: 0.08em;
}

/* Chat: neutral avatars instead of bright coloured ones */
[data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"] {
    background: #1F2937 !important; color: #C9D4E0 !important; border-radius: 4px;
}
[data-testid="stChatMessage"] { border: 1px solid #263041; border-radius: 3px; background: #121821; }

/* Remove Streamlit chrome */
[data-testid="stAppDeployButton"], footer { display: none !important; }
/* Developer credit pinned to the bottom of the sidebar (see sidebar_credit) */
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    display: flex; flex-direction: column; min-height: 100%;
}
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
    margin-top: auto; padding-top: 1rem; padding-bottom: 0.9rem;
}
.bt-sidebar-credit { border-top: 1px solid #263041; padding: 0.7rem 0.2rem 0 0.2rem;
                     line-height: 1.35; }
.bt-sidebar-credit .bt-sc-name { color: #3B9EBF; font-size: 0.72rem; font-weight: 600;
                                 letter-spacing: 0.12em; }
.bt-sidebar-credit .bt-sc-by { color: #8B98A9; font-size: 0.64rem; margin-top: 0.35rem;
                               text-transform: uppercase; letter-spacing: 0.08em; }
.bt-sidebar-credit .bt-sc-dev { color: #C9D4E0; font-size: 0.78rem; font-weight: 500; }
/* Summary cards (ui_theme.metric_cards) */
.bt-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(125px, 1fr));
            gap: 0.7rem; margin: 0.3rem 0 1.2rem 0; }
.bt-card { background: #151B23; border: 1px solid #263041; border-top: 3px solid #3B9EBF;
           border-radius: 4px; padding: 0.65rem 0.85rem 0.7rem 0.85rem; }
.bt-card-label { color: #8B98A9; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em; }
.bt-card-value { color: #E6EDF3; font-size: 1.65rem; font-weight: 600; line-height: 1.25; margin-top: 0.1rem; }
.bt-card-sub { color: #8B98A9; font-size: 0.78rem; margin-top: 0.05rem; }
.bt-legend { display: flex; flex-wrap: wrap; gap: 0.4rem 1.4rem; margin: 0.2rem 0 0.9rem 0;
             color: #C9D4E0; font-size: 0.88rem; }
.bt-dot { display: inline-block; width: 0.7rem; height: 0.7rem; border-radius: 50%;
          margin-right: 0.35rem; vertical-align: baseline; }
</style>
"""


def sidebar_credit() -> None:
    """Small developer credit at the bottom of the sidebar, below the page list."""
    st.sidebar.markdown(
        '<div class="bt-sidebar-credit">'
        '<div class="bt-sc-name">BITTRACE</div>'
        '<div class="bt-sc-by">Developed by</div>'
        '<div class="bt-sc-dev">Dipangshu Dey</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def apply_theme() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    sidebar_credit()


def metric_cards(items: Sequence[tuple]) -> None:
    """Row of summary cards. Each item: (label, value[, sub_text[, accent_hex]]).

    All text is HTML-escaped. Colour is only decoration here: every card has a
    text label, so nothing relies on colour alone.
    """
    cards = []
    for it in items:
        label, value = it[0], it[1]
        sub = it[2] if len(it) > 2 and it[2] else ""
        accent = it[3] if len(it) > 3 and it[3] else ACCENT
        cards.append(
            f'<div class="bt-card" style="border-top-color:{html.escape(accent)}">'
            f'<div class="bt-card-label">{html.escape(str(label))}</div>'
            f'<div class="bt-card-value">{html.escape(str(value))}</div>'
            f'<div class="bt-card-sub">{html.escape(str(sub))}</div></div>'
        )
    st.markdown('<div class="bt-cards">' + "".join(cards) + "</div>", unsafe_allow_html=True)


def legend(entries: Sequence[tuple]) -> None:
    """Colour-dot legend. Each entry: (colour_hex, bold_label, explanation)."""
    parts = [
        f'<span><span class="bt-dot" style="background:{html.escape(c)}"></span>'
        f'<b>{html.escape(l)}</b> - {html.escape(d)}</span>'
        for c, l, d in entries
    ]
    st.markdown('<div class="bt-legend">' + "".join(parts) + "</div>", unsafe_allow_html=True)


def style_figure(fig, height: int = 360, title: Optional[str] = None):
    """Apply the dark BitTrace look to a Plotly figure."""
    fig.update_layout(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT, size=13),
        margin=dict(l=10, r=10, t=48 if title else 16, b=10),
        hoverlabel=dict(bgcolor=PANEL, font_size=13, font_color=TEXT),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=12)),
        **({"title": dict(text=title, font=dict(size=16), x=0)} if title else {}),
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID, tickfont=dict(size=12))
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID, tickfont=dict(size=12))
    return fig


def pdf_download_button(build: Callable[[], bytes], cache_key: str, file_name: str,
                        label: str = "Download PDF report", help: Optional[str] = None) -> None:
    """Build the PDF once per `cache_key` (kept in session state) and offer it
    through st.download_button. A failure shows a clear error instead of
    breaking the page."""
    data = st.session_state.get(cache_key)
    if data is None:
        try:
            with st.spinner("Preparing PDF report..."):
                data = build()
        except Exception as exc:
            st.error(f"The PDF report could not be generated: {exc}")
            with st.expander("Technical details"):
                st.code(traceback.format_exc())
            return
        st.session_state[cache_key] = data
    st.download_button(label, data=data, file_name=file_name, mime="application/pdf",
                       key=f"{cache_key}:download", type="primary", help=help)