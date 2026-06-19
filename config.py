"""Config: env vars, paths, lazy Gemini client."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()


def _load_groq_keys() -> list[str]:
    """Collect all GROQ_API_KEY* env vars.

    Accepts any suffix style: GROQ_API_KEY, GROQ_API_KEY1, GROQ_API_KEY_2,
    GROQ_API_KEY42, etc. Sorted by trailing number (bare key first), deduped.
    """
    matches: list[tuple[int, str]] = []
    for name, val in os.environ.items():
        if not name.startswith("GROQ_API_KEY"):
            continue
        val = val.strip()
        if not val:
            continue
        suffix = name[len("GROQ_API_KEY"):].lstrip("_")
        order = int(suffix) if suffix.isdigit() else 0
        matches.append((order, val))
    matches.sort(key=lambda x: x[0])
    seen: set[str] = set()
    keys: list[str] = []
    for _, k in matches:
        if k in seen:
            continue
        seen.add(k)
        keys.append(k)
    return keys


GROQ_API_KEYS = _load_groq_keys()
GROQ_API_KEY  = GROQ_API_KEYS[0] if GROQ_API_KEYS else ""  # back-compat alias

# Chat runs on Groq; embeddings stay on Gemini
CHAT_MODEL  = os.getenv("GROQ_CHAT_MODEL", "openai/gpt-oss-120b").strip()
EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "models/gemini-embedding-001").strip()

PROJECT_DIR = Path(__file__).parent
CHROMA_DIR  = PROJECT_DIR / ".chroma"
CHROMA_DIR.mkdir(exist_ok=True)

_groq_clients: list = []
_groq_active_idx = 0
_embed_client = None   # Gemini v1 — embeddings only
_chat_client  = None   # Gemini v1beta — kept as fallback, not used by default


def _ensure_groq_pool() -> None:
    global _groq_clients
    if _groq_clients:
        return
    if not GROQ_API_KEYS:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Add it to your .env file."
        )
    from groq import Groq
    _groq_clients = [Groq(api_key=k) for k in GROQ_API_KEYS]


def get_groq_client():
    """Return the currently-active Groq client from the pool."""
    _ensure_groq_pool()
    return _groq_clients[_groq_active_idx]


def rotate_groq_client() -> int:
    """Advance to the next key in the pool. Returns the new active index (1-based)."""
    global _groq_active_idx
    _ensure_groq_pool()
    if len(_groq_clients) <= 1:
        return _groq_active_idx + 1
    _groq_active_idx = (_groq_active_idx + 1) % len(_groq_clients)
    return _groq_active_idx + 1


def groq_pool_size() -> int:
    return len(GROQ_API_KEYS)


def get_embed_client():
    """Gemini v1 client — embeddings only."""
    global _embed_client
    if _embed_client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it to your .env file."
            )
        from google import genai
        from google.genai import types as _types
        _embed_client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options=_types.HttpOptions(api_version="v1"),
        )
    return _embed_client


def get_gemini_client():
    """Gemini v1beta client — kept for backward compatibility."""
    global _chat_client
    if _chat_client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it to your .env file."
            )
        from google import genai
        from google.genai import types as _types
        _chat_client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options=_types.HttpOptions(api_version="v1beta"),
        )
    return _chat_client
