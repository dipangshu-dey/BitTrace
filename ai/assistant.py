"""
BitTrace v2 - ai/assistant.py

The local AI investigation assistant: retrieves relevant facts about the
current investigation via rag_engine, then asks the local Ollama model to
answer the user's question grounded in those facts only.
"""

from pathlib import Path
from typing import List, Optional
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))

import re

from ai.ollama_client import OllamaClient, OllamaUnavailableError
from ai.rag_engine import build_documents, RagIndex
from ai.investigation_context import CONTEXT_KIND, build_context_documents

SYSTEM_PROMPT = (
    "You are BitTrace's investigation assistant. You help a forensics investigator "
    "understand a Bitcoin address clustering/pattern-detection/risk-scoring run. "
    "Answer ONLY using the CONTEXT provided below - it comes directly from the "
    "investigation's own data. If the context doesn't contain the answer, say so "
    "plainly rather than guessing. Be concise and factual. Never invent addresses, "
    "transaction IDs, or risk scores that are not in the context."
)

# Used for a saved investigation selected on the AI Assistant page.
INVESTIGATION_PROMPT = (
    "You are BitTrace's investigation assistant, helping a forensic investigator. You are answering questions about "
    "ONE saved investigation: #{iid}, investigated address {root}.\n"
    "The CONTEXT in each message is that investigation's saved data and nothing else.\n"
    "Rules:\n"
    "1. Use only facts in CONTEXT. Never invent or guess addresses, transaction IDs, amounts, dates, risk scores, patterns "
    "or threat-intelligence matches. Quote addresses and numbers exactly as written in CONTEXT.\n"
    "2. If CONTEXT does not contain what was asked, say: \"That is not available in investigation #{iid}.\" and, if useful, "
    "say what IS available. Never fill a gap from general knowledge or from any other investigation.\n"
    "3. Format every answer in two parts. First 'Findings from the saved data:' - short bullets with the exact values. "
    "Then 'My interpretation (not a recorded finding):' - at most a few sentences of reasoning, clearly hedged. "
    "Leave out the interpretation part if the question is a pure lookup.\n"
    "4. Risk scores and bands are BitTrace's rule-based estimates, not proof of wrongdoing; say so when you rank or recommend.\n"
    "5. Use plain language, as for someone new to blockchain analysis."
)


def strip_reasoning(text: str) -> str:
    """Remove <think>...</think> blocks that reasoning models (e.g. qwen3) may put in the reply."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"^.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)   # opening tag missing
    return text.strip()


class Assistant:
    """Answers questions about ONE investigation.

    Pass either a stored-investigation context (ai.investigation_context.load_investigation_context,
    used by the AI Assistant page) or, for backwards compatibility, a live pipeline result dict.
    An Assistant never reads anything outside the data it was built with, and keeps its own
    conversation history, so a different investigation needs a different Assistant.
    """

    def __init__(self, investigation_result: dict, ollama_client: Optional[OllamaClient] = None):
        self.result = investigation_result
        self.client = ollama_client or OllamaClient()
        self.investigation_id = investigation_result["investigation_id"]
        self.root_address = investigation_result["root_address"]
        if investigation_result.get("kind") == CONTEXT_KIND:
            docs = build_context_documents(investigation_result)
            self.pinned = [d for d in docs if d.get("pinned")]
            self.index = RagIndex([d for d in docs if not d.get("pinned")])
            self.system_prompt = INVESTIGATION_PROMPT.format(iid=self.investigation_id, root=self.root_address)
        else:
            self.pinned = []
            self.index = RagIndex(build_documents(investigation_result))
            self.system_prompt = SYSTEM_PROMPT
        self.history: List[dict] = []

    def retrieve(self, question: str) -> List[dict]:
        seen, out = set(), []
        for d in self.pinned + self.index.query(question):
            if d["id"] not in seen:
                seen.add(d["id"])
                out.append(d)
        return out

    def ask(self, question: str) -> str:
        retrieved = self.retrieve(question)
        context = "\n".join(f"- {d['text']}" for d in retrieved)

        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(self.history[-6:])  # small rolling window of prior turns (this investigation only)
        messages.append({
            "role": "user",
            "content": f"CONTEXT (investigation #{self.investigation_id} only):\n{context}\n\nQUESTION: {question}",
        })

        try:
            answer = strip_reasoning(self.client.chat(messages))
        except OllamaUnavailableError as e:
            return (f"[AI assistant unavailable] {e}\n\n"
                    f"Here's what I found directly from the investigation data instead:\n{context}")
        if not answer:
            answer = "The model returned an empty reply. Please try rephrasing the question."
        else:
            self.history.append({"role": "user", "content": question})
            self.history.append({"role": "assistant", "content": answer})
        return answer


if __name__ == "__main__":
    fake_result = {
        "investigation_id": 1, "root_address": "ROOT", "addresses": ["ROOT", "A"],
        "clusters": [], "patterns": {"peel_chain": [], "fan_out": [], "fan_in": [],
                                      "coinjoin": [], "circular_flow": []},
        "risk_scores": {"A": {"score": 80, "band": "high",
                               "breakdown": [{"signal": "ransomware_match", "points": 35, "reason": "x"}]}},
        "entity_map": {},
    }
    assistant = Assistant(fake_result)
    answer = assistant.ask("What is the risk score of address A?")
    print("Assistant answer:\n", answer)
    print("\n(If Ollama isn't running in this environment, the graceful-degradation "
          "fallback above should still surface the correct retrieved facts.)")
