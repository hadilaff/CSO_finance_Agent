from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------- Tavily (web search) ----------
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()


# ---------- Groq (Whisper STT only — chat is now Azure) ----------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

# ---------- Embeddings (local ONNX — no API key) ----------
CHAT_MODEL  = os.getenv("GROQ_CHAT_MODEL", "openai/gpt-oss-120b").strip()
EMBED_MODEL = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2").strip()

# ---------- Paths ----------
PROJECT_DIR = Path(__file__).parent
CHROMA_DIR  = PROJECT_DIR / ".chroma"
CHROMA_DIR.mkdir(exist_ok=True)

# ---------- Lazy clients ----------

_groq_client  = None


def get_groq_client():
    """Groq client — used exclusively for Whisper voice transcription."""
    global _groq_client
    if _groq_client is None:
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set. Required for voice transcription.")
        from groq import Groq
        _groq_client = Groq(api_key=GROQ_API_KEY)
    return _groq_client

