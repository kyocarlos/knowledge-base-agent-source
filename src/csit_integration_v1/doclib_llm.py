"""KM primary LLM entry point for the three semantic metadata fields (same client the Wi-Fi digest uses).

The CSIT worker image has no application package (src.web_api), so when KM_CSIT_LLM_BASE_URL is set the same OpenAI-compatible gateway the
primary LLM uses (sub2api) is called directly: KM_CSIT_LLM_BASE_URL, KM_CSIT_LLM_MODEL and the key read from the file KM_CSIT_LLM_API_KEY_FILE.
"""
import os,threading

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

def _gateway(prompt):
    import httpx
    key=open(os.environ["KM_CSIT_LLM_API_KEY_FILE"],encoding="utf-8").read().strip()
    r=httpx.post(os.environ["KM_CSIT_LLM_BASE_URL"].rstrip("/")+"/chat/completions",headers={"Authorization":"Bearer "+key},timeout=float(os.getenv("KM_CSIT_LLM_TIMEOUT","60")),
        json={"model":os.environ["KM_CSIT_LLM_MODEL"],"messages":[{"role":"user","content":prompt}],"temperature":0})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""

def complete(prompt):
    if os.getenv("KM_CSIT_LLM_BASE_URL"):return _gateway(prompt)
    response=_primary().chat.completions.create(messages=[{"role":"user","content":prompt}],temperature=0)
    return response.choices[0].message.content or ""
