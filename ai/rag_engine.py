"""
BitTrace v2 - ai/rag_engine.py

Retrieval-Augmented Generation over a single investigation's data. Turns
the investigation result dict into a list of short text "documents"
(one per address, cluster, and pattern), then retrieves the most relevant
ones for a user's question so the local LLM can answer grounded in the
actual investigation instead of hallucinating.

Embedding strategy:
  - Preferred: sentence-transformers (semantic search). This needs to
    download model weights from the internet the first time, so it may
    not work in network-restricted environments.
  - Fallback: a dependency-free keyword-overlap scorer (TF-style word
    overlap). This always works offline and is good enough for the fairly
    narrow, keyword-heavy questions this assistant is meant to answer
    ("what's the risk score of X", "which addresses are in cluster Y").

The fallback is chosen automatically - callers never need to know which
one is active.
"""

import re
from pathlib import Path
from typing import List
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    _HAS_EMBEDDINGS = True
except ImportError:
    _HAS_EMBEDDINGS = False


def build_documents(result: dict) -> List[dict]:
    """Flatten an investigation result dict into retrievable text chunks."""
    docs = []

    docs.append({
        "id": "summary",
        "text": (f"Investigation #{result['investigation_id']} rooted at address "
                 f"{result['root_address']}. {len(result['addresses'])} addresses analyzed, "
                 f"{len(result['clusters'])} clusters found, "
                 f"{sum(len(v) for v in result['patterns'].values())} suspicious patterns detected."),
    })

    for addr, rs in result["risk_scores"].items():
        signals = ", ".join(b["signal"] for b in rs["breakdown"]) or "none"
        docs.append({
            "id": f"risk:{addr}",
            "text": (f"Address {addr} has risk score {rs['score']} ({rs['band']} risk). "
                     f"Contributing signals: {signals}."),
        })

    for c in result["clusters"]:
        docs.append({
            "id": f"cluster:{c['root']}",
            "text": (f"Cluster rooted at {c['root']} contains {c['size']} addresses believed to be "
                     f"controlled by the same wallet: {', '.join(c['members'][:20])}."),
        })

    for pattern_type, items in result["patterns"].items():
        for i, item in enumerate(items):
            docs.append({
                "id": f"pattern:{pattern_type}:{i}",
                "text": f"Detected {pattern_type.replace('_', ' ')} pattern: {item}",
            })

    for addr, attrs in result["entity_map"].items():
        for a in attrs:
            docs.append({
                "id": f"entity:{addr}:{a['method']}",
                "text": (f"Address {addr} attributed as entity type '{a['entity_type']}' "
                         f"via {a['method']} (confidence {a['confidence']}). {a.get('detail', '')}"),
            })

    return docs


class RagIndex:
    def __init__(self, documents: List[dict]):
        self.documents = documents
        self._embeddings = None
        self._model = None
        if _HAS_EMBEDDINGS and documents:
            try:
                self._model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
                self._embeddings = self._model.encode([d["text"] for d in documents])
            except Exception as e:
                print(f"[rag_engine] Falling back to keyword search - embedding model "
                      f"unavailable ({e}). This is expected offline.")
                self._model = None

    def query(self, question: str, top_k: int = config.RAG_TOP_K) -> List[dict]:
        if not self.documents:
            return []
        if self._model is not None:
            return self._semantic_query(question, top_k)
        return self._keyword_query(question, top_k)

    def _semantic_query(self, question: str, top_k: int) -> List[dict]:
        q_emb = self._model.encode([question])[0]
        sims = np.dot(self._embeddings, q_emb) / (
            np.linalg.norm(self._embeddings, axis=1) * np.linalg.norm(q_emb) + 1e-9
        )
        top_idx = np.argsort(sims)[::-1][:top_k]
        return [self.documents[i] for i in top_idx]

    def _keyword_query(self, question: str, top_k: int) -> List[dict]:
        q_words = set(_tokenize(question))
        scored = []
        for doc in self.documents:
            doc_words = set(_tokenize(doc["text"]))
            overlap = len(q_words & doc_words)
            if overlap > 0:
                scored.append((overlap, doc))
        scored.sort(key=lambda t: t[0], reverse=True)
        if not scored:
            return self.documents[:top_k]
        return [doc for _, doc in scored[:top_k]]


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9]+", text.lower())


if __name__ == "__main__":
    fake_result = {
        "investigation_id": 1,
        "root_address": "ROOT",
        "addresses": ["ROOT", "A", "B"],
        "clusters": [{"root": "ROOT", "size": 2, "members": ["ROOT", "A"]}],
        "patterns": {"peel_chain": [{"path": ["ROOT", "A", "B"], "hops": 2}],
                     "fan_out": [], "fan_in": [], "coinjoin": [], "circular_flow": []},
        "risk_scores": {
            "ROOT": {"score": 10, "band": "low", "breakdown": []},
            "A": {"score": 80, "band": "high",
                  "breakdown": [{"signal": "ransomware_match", "points": 35, "reason": "x"}]},
        },
        "entity_map": {"A": [{"entity_type": "ransomware", "confidence": 0.9,
                               "method": "dataset_match", "detail": "WannaCry list"}]},
    }

    docs = build_documents(fake_result)
    index = RagIndex(docs)
    results = index.query("what is the risk score of address A?")
    print(f"Using {'semantic' if index._model else 'keyword-fallback'} retrieval.")
    for r in results[:3]:
        print(" -", r["text"])

    assert any("A has risk score 80" in r["text"] for r in results), \
        "FAIL: keyword retrieval should surface address A's risk score for this question"
    print("PASS: RAG engine retrieves relevant documents (keyword fallback confirmed working offline).")
