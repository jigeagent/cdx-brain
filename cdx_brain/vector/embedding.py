from __future__ import annotations
import logging, os
import numpy as np
logger = logging.getLogger(__name__)
DEFAULT_DIMS = 384
_provider = None

def _get_provider():
    global _provider
    if _provider is not None:
        return _provider
    ov_url = os.environ.get("CDX_BRAIN_OV_URL", "")
    if ov_url:
        try:
            import httpx
            resp = httpx.post(ov_url + "/api/v1/embed", json={"text": "test"}, timeout=2.0)
            if resp.status_code == 200:
                _provider = _OVProvider(ov_url)
                return _provider
        except Exception:
            pass
    try:
        from sentence_transformers import SentenceTransformer
        _provider = _STProvider(SentenceTransformer("all-MiniLM-L6-v2"))
        return _provider
    except Exception:
        pass
    _provider = _NumpyFallbackProvider()
    return _provider

class _OVProvider:
    def __init__(self, url):
        self._url = url.rstrip("/")
    def embed(self, text):
        import httpx
        resp = httpx.post(self._url + "/api/v1/embed", json={"text": text}, timeout=5.0)
        resp.raise_for_status()
        return resp.json().get("embedding", [])

class _STProvider:
    def __init__(self, model):
        self._model = model
    def embed(self, text):
        return self._model.encode(text, normalize_embeddings=True).tolist()

class _NumpyFallbackProvider:
    def __init__(self, dims=DEFAULT_DIMS):
        self._dims = dims
    def embed(self, text):
        rng = np.random.RandomState(hash(text) & 0xFFFFFFFF)
        vec = rng.randn(self._dims)
        norm = np.linalg.norm(vec)
        if norm > 1e-12:
            vec = vec / norm
        return vec.tolist()

def compute_query_embedding(text: str):
    if not text or not text.strip():
        return None
    try:
        return _get_provider().embed(text[:2048])
    except Exception as e:
        logger.warning("embedding failed: %s", e)
        return None

def compute_trace_embedding(user_content: str, assistant_content: str = ""):
    sep = chr(92) + chr(110)
    return compute_query_embedding(user_content + sep + assistant_content)
