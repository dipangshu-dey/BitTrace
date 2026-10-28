"""
BitTrace v2 - ai/ollama_client.py

Thin wrapper around a locally-running Ollama server. This keeps BitTrace's
AI assistant fully local/offline - no API keys, no data leaving the
investigator's machine, which matters for forensics work.

Requires Ollama installed and running locally (https://ollama.com) with a
model pulled, e.g.:
    ollama pull llama3.1

Fails gracefully (raises a clear, catchable OllamaUnavailableError) if the
server isn't reachable, so the rest of the app can degrade nicely rather
than crashing.
"""

from pathlib import Path
from typing import List, Optional
import sys

import requests

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config


class OllamaUnavailableError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, host: str = config.OLLAMA_HOST, model: str = config.OLLAMA_MODEL):
        self.host = host.rstrip("/")
        self.model = model

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=3)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def list_models(self) -> List[str]:
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=5)
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
        except requests.RequestException as e:
            raise OllamaUnavailableError(f"Could not reach Ollama at {self.host}: {e}") from e

    def has_model(self, model: Optional[str] = None) -> bool:
        """True if the model is installed (a bare name like `llama3.2` matches `llama3.2:latest`)."""
        want = (model or self.model).lower()
        for name in self.list_models():
            n = name.lower()
            if n == want or n == f"{want}:latest" or (":" not in want and n.split(":")[0] == want):
                return True
        return False

    def chat(self, messages: List[dict], model: Optional[str] = None, temperature: float = 0.2) -> str:
        """
        messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
        Returns the assistant's reply text.
        """
        payload = {
            "model": model or self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_ctx": config.OLLAMA_NUM_CTX},
        }
        try:
            resp = requests.post(f"{self.host}/api/chat", json=payload, timeout=config.OLLAMA_TIMEOUT_S)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "")
        except requests.RequestException as e:
            raise OllamaUnavailableError(
                f"Could not reach Ollama at {self.host} (model={model or self.model}). "
                f"Is `ollama serve` running and has the model been pulled? Original error: {e}"
            ) from e


if __name__ == "__main__":
    client = OllamaClient()
    if client.is_available():
        print(f"Ollama reachable at {client.host}. Models: {client.list_models()}")
        reply = client.chat([{"role": "user", "content": "Reply with exactly: OK"}])
        print("Test reply:", reply)
    else:
        print(f"Ollama not reachable at {client.host} in this environment (expected in a sandbox "
              f"with no local Ollama server) - this is the intended graceful-degradation path. "
              f"On your machine, run `ollama serve` and `ollama pull {config.OLLAMA_MODEL}` first.")
