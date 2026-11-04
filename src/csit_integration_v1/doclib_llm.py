"""KM primary LLM entry point for the three semantic metadata fields (same client the Wi-Fi digest uses)."""
import threading

_lock=threading.Lock()
_client=None

def _primary():
    global _client
    with _lock:
        if _client is None:
            from ..main import load_config
            from ..web_api.ollama_client import _build_primary_client
            client,_label=_build_primary_client(load_config())
            if client is None:raise RuntimeError("no primary LLM configured")
            _client=client
        return _client

def complete(prompt):
    response=_primary().chat.completions.create(messages=[{"role":"user","content":prompt}],temperature=0)
    return response.choices[0].message.content or ""
