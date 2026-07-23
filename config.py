"""Config: env vars, paths, Azure OpenAI chat client, Groq client (Whisper only),
local ONNX embeddings (no API key needed).

Chat model  → Azure OpenAI (gpt-5-chat via DEPLOYMENT_NAME)
Voice (STT) → Groq Whisper (unchanged)
Embeddings  → local ONNX all-MiniLM-L6-v2 (unchanged)
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------- Tavily (web search) ----------
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()

# ---------- Azure OpenAI (chat + tool calling) ----------
AZURE_ENDPOINT       = os.getenv("AZURE_ENDPOINT", "").strip()
AZURE_API_KEY        = os.getenv("AZURE_API_KEY", "").strip()
AZURE_API_VERSION    = os.getenv("AZURE_API_VERSION", "2026-05-05").strip()
DEPLOYMENT_NAME      = os.getenv("DEPLOYMENT_NAME", "").strip()   # e.g. "gpt-5-chat"

# CHAT_MODEL is the deployment name on Azure (used in .create(model=...) calls)
CHAT_MODEL = DEPLOYMENT_NAME

# ---------- Groq (Whisper STT only — chat is now Azure) ----------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

# ---------- Embeddings (local ONNX — no API key) ----------
EMBED_MODEL = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2").strip()

# ---------- Paths ----------
PROJECT_DIR = Path(__file__).parent
CHROMA_DIR  = PROJECT_DIR / ".chroma"
CHROMA_DIR.mkdir(exist_ok=True)

# ---------- Lazy clients ----------
_azure_client = None
_groq_client  = None


def get_azure_client():
    """Azure AI Foundry inference client for chat and tool calling.

    The endpoint https://<resource>.services.ai.azure.com/openai/v1 is an
    Azure AI Foundry endpoint — it uses the standard OpenAI client (not AzureOpenAI)
    with the endpoint as base_url and the Azure key as api_key.
    No api_version needed for this endpoint type.
    """
    global _azure_client
    if _azure_client is None:
        if not AZURE_ENDPOINT:
            raise RuntimeError("AZURE_ENDPOINT is not set. Add it to your .env file.")
        if not AZURE_API_KEY:
            raise RuntimeError("AZURE_API_KEY is not set. Add it to your .env file.")
        if not DEPLOYMENT_NAME:
            raise RuntimeError("DEPLOYMENT_NAME is not set. Add it to your .env file.")
        from openai import OpenAI
        _azure_client = OpenAI(
            base_url=AZURE_ENDPOINT,
            api_key=AZURE_API_KEY,
        )
    return _azure_client


def get_groq_client():
    """Groq client — used exclusively for Whisper voice transcription."""
    global _groq_client
    if _groq_client is None:
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set. Required for voice transcription.")
        from groq import Groq
        _groq_client = Groq(api_key=GROQ_API_KEY)
    return _groq_client


# ---------- Backwards-compat alias ----------
# Any module that still calls get_groq_client() for CHAT purposes should be
# updated to call get_azure_client() instead. The alias below is kept so that
# voice.py (which legitimately uses Groq Whisper) continues to work unchanged.
