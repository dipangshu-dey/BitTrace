"""AI Assistant: the selected investigation alone controls the data the model sees."""
import pytest

import config
from db import database
from ai.assistant import Assistant, strip_reasoning
from ai.investigation_context import (list_investigation_options, load_investigation_context,
                                      build_context_documents)
from ai.ollama_client import OllamaUnavailableError


class FakeClient:
    """Stands in for Ollama: records the prompt it receives and answers with a canned reply."""
    model = "fake"

    def __init__(self, reply="Findings from the saved data: ok", fail=False):
        self.calls, self.reply, self.fail = [], reply, fail

    def chat(self, messages, **kw):
        self.calls.append(messages)
        if self.fail:
            raise OllamaUnavailableError("connection refused")
        return self.reply


def _tx(txid, ins, outs, t=1_600_000_000):
    return {"txid": txid, "block_time": t,
            "inputs": [{"address": a, "value_btc": v} for a, v in ins],
            "outputs": [{"address": a, "value_btc": v} for a, v in outs]}


@pytest.fixture
def two_investigations(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "ai.db")
    database.init_db()
    from core.pipeline import run_investigation
    a = run_investigation("ROOT_ALPHA", synthetic_txs=[
        _tx("a1", [("ROOT_ALPHA", 5.0)], [("ALPHA_PAYEE", 4.9), ("ALPHA_CHANGE", 0.09)])], notes="alpha run")
    b = run_investigation("ROOT_BRAVO", synthetic_txs=[
        _tx("b1", [("ROOT_BRAVO", 2.0)], [("BRAVO_PAYEE", 1.9), ("BRAVO_CHANGE", 0.09)])], notes="bravo run")
    return a["investigation_id"], b["investigation_id"]


def test_options_list_ids_and_addresses(two_investigations):
    ida, idb = two_investigations
    opts = {o["id"]: o for o in list_investigation_options()}
    assert opts[ida]["root_address"] == "ROOT_ALPHA" and f"#{ida}" in opts[ida]["label"] and "ROOT_ALPHA" in opts[ida]["label"]
    assert opts[idb]["root_address"] == "ROOT_BRAVO"


def test_context_contains_only_the_selected_investigation(two_investigations):
    ida, idb = two_investigations
    text_a = " ".join(d["text"] for d in build_context_documents(load_investigation_context(ida)))
    text_b = " ".join(d["text"] for d in build_context_documents(load_investigation_context(idb)))
    assert "ROOT_ALPHA" in text_a and "ALPHA_PAYEE" in text_a and "BRAVO" not in text_a
    assert "ROOT_BRAVO" in text_b and "BRAVO_PAYEE" in text_b and "ALPHA" not in text_b


def test_prompt_sent_to_model_follows_the_selection(two_investigations):
    ida, idb = two_investigations
    fa, fb = FakeClient(), FakeClient()
    asst_a = Assistant(load_investigation_context(ida), fa)
    asst_b = Assistant(load_investigation_context(idb), fb)
    asst_a.ask("Explain the transaction flow.")
    asst_b.ask("Explain the transaction flow.")
    sent_a = " ".join(m["content"] for m in fa.calls[0])
    sent_b = " ".join(m["content"] for m in fb.calls[0])
    assert f"#{ida}" in sent_a and "ALPHA" in sent_a and "BRAVO" not in sent_a
    assert f"#{idb}" in sent_b and "BRAVO" in sent_b and "ALPHA" not in sent_b
    # a second question on A must not carry B's data either (history is per assistant)
    asst_a.ask("Which addresses should I investigate further?")
    assert "BRAVO" not in " ".join(m["content"] for m in fa.calls[1])


def test_unavailable_ollama_falls_back_to_saved_facts(two_investigations):
    ida, _ = two_investigations
    answer = Assistant(load_investigation_context(ida), FakeClient(fail=True)).ask("Summarize the investigation findings.")
    assert "unavailable" in answer.lower() and "ROOT_ALPHA" in answer and "BRAVO" not in answer


def test_missing_investigation_and_empty_run(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "e.db")
    database.init_db()
    assert load_investigation_context(999) is None
    iid = database.create_investigation("1EMPTYRUN", 1)           # a run that never saved results
    ctx = load_investigation_context(iid)
    assert ctx["complete"] is False and ctx["threat_matches"] == [] and ctx["flows"] == []
    text = " ".join(d["text"] for d in build_context_documents(ctx))
    assert "NO saved results" in text
    assert [o for o in list_investigation_options() if o["id"] == iid][0]["complete"] is False


def test_strip_reasoning():
    assert strip_reasoning("<think>hidden</think>\n\nAnswer") == "Answer"
    assert strip_reasoning("hidden</think>Answer") == "Answer"
    assert strip_reasoning("plain") == "plain"
