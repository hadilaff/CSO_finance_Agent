"""Config: env vars, paths, lazy Gemini client pool (chat + embeddings)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()


def _load_gemini_keys() -> list[str]:
    """Collect all GEMINI_API_KEY* env vars.

    Accepts any suffix style: GEMINI_API_KEY, GEMINI_API_KEY1, GEMINI_API_KEY_2,
    GEMINI_API_KEY42, etc. Sorted by trailing number (bare key first), deduped.
    """
    matches: list[tuple[int, str]] = []
    for name, val in os.environ.items():
        if not name.startswith("GEMINI_API_KEY"):
            continue
        val = val.strip()
        if not val:
            continue
        suffix = name[len("GEMINI_API_KEY"):].lstrip("_")
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


GEMINI_API_KEYS = _load_gemini_keys()
GEMINI_API_KEY = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""  # back-compat alias

# Chat + transcription run on Gemini Flash; embeddings on gemini-embedding-001.
CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-2.5-flash").strip()
AUDIO_MODEL = os.getenv("GEMINI_AUDIO_MODEL", "gemini-2.5-flash").strip()
EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "models/gemini-embedding-001").strip()

PROJECT_DIR = Path(__file__).parent
CHROMA_DIR = PROJECT_DIR / ".chroma"
CHROMA_DIR.mkdir(exist_ok=True)


_gemini_clients: list = []
_gemini_active_idx = 0


def _ensure_gemini_pool() -> None:
    """Build the chat client pool (v1beta — supports system_instruction + tools)."""
    global _gemini_clients
    if _gemini_clients:
        return
    if not GEMINI_API_KEYS:
        raise RuntimeError(
            "No GEMINI_API_KEY* found in env. Set GEMINI_API_KEY (or "
            "GEMINI_API_KEY1, GEMINI_API_KEY2, …) in your .env file."
        )
    from google import genai
    from google.genai import types as _types
    _gemini_clients = [
        genai.Client(api_key=k, http_options=_types.HttpOptions(api_version="v1beta"))
        for k in GEMINI_API_KEYS
    ]


def get_gemini_client():
    """Return the currently-active Gemini client from the pool."""
    _ensure_gemini_pool()
    return _gemini_clients[_gemini_active_idx]


def rotate_gemini_client() -> int:
    """Advance to the next key in the pool. Returns the new active index (1-based)."""
    global _gemini_active_idx
    _ensure_gemini_pool()
    if len(_gemini_clients) <= 1:
        return _gemini_active_idx + 1
    _gemini_active_idx = (_gemini_active_idx + 1) % len(_gemini_clients)
    return _gemini_active_idx + 1


def gemini_pool_size() -> int:
    return len(GEMINI_API_KEYS)


# Back-compat aliases — rag.py and other modules import these.
def get_embed_client():
    """Embedding client — shares the chat pool (any rotation applies)."""
    return get_gemini_client()


def get_chat_client():
    return get_gemini_client()
