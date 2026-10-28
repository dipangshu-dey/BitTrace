from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import config
from ui_theme import apply_theme, metric_cards, RISK_COLOR
from ai.assistant import Assistant
from ai.ollama_client import OllamaClient, OllamaUnavailableError
from ai.investigation_context import list_investigation_options, load_investigation_context

st.set_page_config(page_title="AI Assistant - BitTrace", layout="wide")
apply_theme()
st.title("AI Investigation Assistant")
st.caption("Runs fully locally via Ollama - no data leaves your machine.")

client = OllamaClient()


@st.cache_data(ttl=10)
def ollama_status(host: str, model: str) -> str:
    """'ok', 'down' (server unreachable) or 'no_model' (server up, model not installed)."""
    c = OllamaClient(host=host, model=model)
    if not c.is_available():
        return "down"
    try:
        return "ok" if c.has_model() else "no_model"
    except OllamaUnavailableError:
        return "down"


# ---------------------------------------------------------------- investigation selector (top of page)
try:
    options = list_investigation_options()
except Exception as exc:  # unreadable or locked database - say so instead of a stack trace
    st.error(f"The saved investigations could not be loaded: {exc}")
    st.stop()

if not options:
    st.info("No investigations are saved yet. Run one on the **Investigate** page first, then come back here.")
    st.stop()

by_id = {o["id"]: o for o in options}
ids = list(by_id)

# Default selection: the investigation just run in this session if it is saved, otherwise the newest one with saved results.
# After that the selector alone decides; session results are never used as the data source.
if st.session_state.get("ai_investigation_id") not in by_id:
    live = (st.session_state.get("last_result") or {}).get("investigation_id")
    st.session_state["ai_investigation_id"] = live if live in by_id else next((o["id"] for o in options if o["complete"]), ids[0])

sel_col, btn_col = st.columns([5, 1])
selected_id = sel_col.selectbox(
    "Investigation to analyse", ids, key="ai_investigation_id", format_func=lambda i: by_id[i]["label"],
    help="Every answer is based only on the saved data of the investigation selected here. "
         "Your questions and the assistant's answers are kept separately for each investigation.",
)
btn_col.markdown('<div style="height:1.75rem"></div>', unsafe_allow_html=True)
reload_clicked = btn_col.button("Reload data", width="stretch",
                                help="Re-read this investigation's saved data from the database.")
opt = by_id[selected_id]

# ---------------------------------------------------------------- load the selected investigation from the database
assistants = st.session_state.setdefault("ai_assistants", {})
chats = st.session_state.setdefault("ai_chats", {})
# forget investigations that no longer exist (deleted on the History page)
for stale in [k for k in list(assistants) if k not in by_id]:
    assistants.pop(stale, None)
    chats.pop(stale, None)

entry = assistants.get(selected_id)
stale_notice = False
if reload_clicked or entry is None or entry["fingerprint"] != opt["fingerprint"]:
    stale_notice = entry is not None and not reload_clicked
    try:
        ctx = load_investigation_context(selected_id)
    except Exception as exc:
        st.error(f"Investigation #{selected_id} could not be loaded from the database: {exc}")
        st.stop()
    if ctx is None:
        st.error(f"Investigation #{selected_id} no longer exists in the database.")
        st.stop()
    entry = {"fingerprint": opt["fingerprint"], "context": ctx, "assistant": Assistant(ctx, client)}
    assistants[selected_id] = entry
    if stale_notice:
        chats[selected_id] = []   # saved data changed under an old conversation; do not keep answers built on the old data
    chats.setdefault(selected_id, [])
ctx, assistant = entry["context"], entry["assistant"]
chat = chats.setdefault(selected_id, [])

# Defensive: the assistant, its data and the selector must all describe the same investigation.
assert assistant.investigation_id == ctx["investigation_id"] == selected_id, "AI context does not match the selected investigation"

# ---------------------------------------------------------------- what is selected
if stale_notice:
    st.info(f"The saved data for investigation #{selected_id} changed, so it was reloaded and its earlier conversation was cleared.")
st.markdown(f"**Selected:** investigation **#{selected_id}** - investigated address `{ctx['root_address']}`")
bands = {b: sum(1 for r in ctx["risk"] if r["band"] == b) for b in ("high", "medium", "low")}
metric_cards([
    ("Investigation", f"#{selected_id}", f"{(ctx['created_at'] or '')[:16]} UTC, {ctx['max_hops']} hop(s)"),
    ("Addresses scored", f"{len(ctx['risk']):,}", "saved risk scores"),
    ("High risk", f"{bands['high']:,}", f"{bands['medium']:,} medium, {bands['low']:,} low", RISK_COLOR.get("high", "#E5534B")),
    ("Clusters", f"{len(ctx['clusters']):,}", "same-wallet groups"),
    ("Patterns", f"{len(ctx['patterns']):,}", "suspicious patterns"),
    ("Threat matches", f"{len(ctx['threat_matches']):,}", "on threat lists"),
])
if not ctx["complete"]:
    st.warning(f"Investigation #{selected_id} has no saved results (the run did not finish). "
               f"The assistant can only tell you that; pick another investigation for findings.")

# ---------------------------------------------------------------- Ollama status
status = ollama_status(client.host, client.model)
if status == "down":
    st.warning(
        f"Ollama isn't reachable at `{client.host}`. Install it from https://ollama.com, make sure the Ollama service is "
        f"running and the `{client.model}` model is installed, then refresh this page. "
        f"Until then, questions below will just show the raw retrieved facts."
    )
elif status == "no_model":
    st.warning(f"Ollama is running, but the `{client.model}` model is not installed. Run `ollama pull {client.model}` "
               f"(or set the OLLAMA_MODEL environment variable to a model you have). Until then, answers show the raw retrieved facts.")
else:
    st.caption(f"Model: `{client.model}` via Ollama. Answers separate recorded findings from the model's interpretation.")

# ---------------------------------------------------------------- conversation (this investigation only)
AVATAR = {"user": ":material/person:", "assistant": ":material/policy:"}

with st.expander("Suggested questions"):
    suggestions = [
        "What happened in this investigation?",
        "Explain the transaction flow.",
        "Which addresses received or sent Bitcoin?",
        "Were any suspicious transaction patterns detected?",
        "What are the risk scores of the addresses?",
        "Were any threat intelligence matches found?",
        "Explain the transaction graph in simple language.",
        "Summarize the investigation findings.",
        "Which addresses should I investigate further, and why?",
    ]
    picked = None
    cols = st.columns(3)
    for i, q in enumerate(suggestions):
        if cols[i % 3].button(q, key=f"ai_sugg_{selected_id}_{i}", width="stretch"):
            picked = q

if not chat:
    st.caption(f"No questions asked about investigation #{selected_id} yet.")
for m in chat:
    with st.chat_message(m["role"], avatar=AVATAR[m["role"]]):
        st.write(m["content"])
        if m["role"] == "assistant":
            st.caption(f"Based on the saved data of investigation #{m['investigation_id']}.")

typed = st.chat_input(f"Ask about investigation #{selected_id}, e.g. 'Which addresses are high risk and why?'")
question = typed or picked
if question:
    chat.append({"role": "user", "content": question, "investigation_id": selected_id})
    with st.chat_message("user", avatar=AVATAR["user"]):
        st.write(question)
    with st.chat_message("assistant", avatar=AVATAR["assistant"]):
        with st.spinner(f"Thinking about investigation #{selected_id}..."):
            answer = assistant.ask(question)
        st.write(answer)
        st.caption(f"Based on the saved data of investigation #{selected_id}.")
    chat.append({"role": "assistant", "content": answer, "investigation_id": selected_id})

if chat and st.button("Clear this conversation", key=f"ai_clear_{selected_id}",
                      help="Clears the conversation for this investigation only."):
    chats[selected_id] = []
    assistant.history.clear()
    st.rerun()
