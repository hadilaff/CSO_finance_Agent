"""Config: env vars, paths, Groq chat client, local ONNX embeddings (no API key needed)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "").strip()

# Chat + voice transcription via Groq; embeddings via local ONNX (all-MiniLM-L6-v2)
CHAT_MODEL  = os.getenv("GROQ_CHAT_MODEL", "llama-3.3-70b-versatile").strip()
EMBED_MODEL = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2").strip()

PROJECT_DIR = Path(__file__).parent
CHROMA_DIR  = PROJECT_DIR / ".chroma"
CHROMA_DIR.mkdir(exist_ok=True)

_groq_client = None


def get_groq_client():
    """Groq client for chat, tool-calling, and voice transcription."""
    global _groq_client
    if _groq_client is None:
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set. Add it to your .env file.")
        from groq import Groq
        _groq_client = Groq(api_key=GROQ_API_KEY)
    return _groq_client
