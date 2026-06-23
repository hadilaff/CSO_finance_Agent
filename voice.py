"""Voice I/O: audio transcription via Groq Whisper + edge-tts speech synthesis."""
from __future__ import annotations

import asyncio
import io
import re

from config import get_groq_client

DEFAULT_TTS_VOICE = "en-US-AriaNeural"

_MIME_BY_EXT = {
    ".wav":  "audio/wav",
    ".mp3":  "audio/mp3",
    ".m4a":  "audio/mp4",
    ".webm": "audio/webm",
    ".ogg":  "audio/ogg",
    ".flac": "audio/flac",
}


def _mime_for(filename: str) -> str:
    lower = filename.lower()
    for ext, mime in _MIME_BY_EXT.items():
        if lower.endswith(ext):
            return mime
    return "audio/wav"


def transcribe(audio_bytes: bytes, filename: str = "audio.wav") -> str:
    """Transcribe audio using Groq's Whisper endpoint."""
    client = get_groq_client()
    file_tuple = (filename, io.BytesIO(audio_bytes), _mime_for(filename))
    resp = client.audio.transcriptions.create(
        file=file_tuple,
        model="whisper-large-v3-turbo",
        response_format="text",
    )
    return (resp or "").strip()


# ---------- markdown/citation cleanup so TTS doesn't read out brackets ----------

_RE_CITATIONS  = re.compile(r"\[(?:Doc|Web)[^\]]*\]")
_RE_MD_LINKS   = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_RE_BOLD_ITAL  = re.compile(r"\*+([^*]+)\*+")
_RE_HEADERS    = re.compile(r"^#+\s*", re.MULTILINE)
_RE_CODE_TICKS = re.compile(r"`+([^`]*)`+")
_RE_MULTISPACE = re.compile(r"\s+")


def _clean_for_tts(text: str) -> str:
    text = _RE_CITATIONS.sub("", text)
    text = _RE_MD_LINKS.sub(r"\1", text)
    text = _RE_BOLD_ITAL.sub(r"\1", text)
    text = _RE_CODE_TICKS.sub(r"\1", text)
    text = _RE_HEADERS.sub("", text)
    text = text.replace("•", "").replace("—", "-").replace("·", "")
    text = _RE_MULTISPACE.sub(" ", text).strip()
    return text


async def _synthesize_async(text: str, voice: str) -> bytes:
    import edge_tts
    comm = edge_tts.Communicate(text, voice)
    buf = bytearray()
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            buf.extend(chunk["data"])
    return bytes(buf)


def synthesize(text: str, voice: str = DEFAULT_TTS_VOICE) -> bytes:
    """Generate MP3 bytes from text using edge-tts (Microsoft Edge voices)."""
    cleaned = _clean_for_tts(text)
    if not cleaned:
        return b""
    try:
        return asyncio.run(_synthesize_async(cleaned, voice))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_synthesize_async(cleaned, voice))
        finally:
            loop.close()
