"""RAG: parse uploaded docs (PDF/DOCX/PPTX/TXT), chunk, embed with Gemini,
store and search in a persistent Chroma collection."""
from __future__ import annotations

import io
import re
import time
import logging
from pathlib import Path

import chromadb
from chromadb.config import Settings
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from config import CHROMA_DIR, EMBED_MODEL, get_embed_client

logger = logging.getLogger(__name__)

# Embedding models to try in order when one is unavailable
EMBED_MODEL_FALLBACKS = [
    EMBED_MODEL,                    # primary: models/gemini-embedding-001
    "models/gemini-embedding-2",    # newer model, fallback
]

COLLECTION_NAME = "institutional_knowledge"


# ---------- Document parsing ----------

def _parse_pdf(data: bytes) -> list[tuple[int, str]]:
    """Return list of (page_number, text) tuples — one per page."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append((i, text))
    return pages


def _parse_docx(data: bytes) -> str:
    from docx import Document
    doc = Document(io.BytesIO(data))
    paragraphs = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
    # also pull table text
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                paragraphs.append(" | ".join(cells))
    return "\n".join(paragraphs)


def _parse_pptx(data: bytes) -> str:
    from pptx import Presentation
    pres = Presentation(io.BytesIO(data))
    parts = []
    for i, slide in enumerate(pres.slides, start=1):
        lines = []
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text and shape.text.strip():
                lines.append(shape.text.strip())
        if lines:
            parts.append(f"[Slide {i}]\n" + "\n".join(lines))
    return "\n\n".join(parts)


def _parse_text(data: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="ignore")


def parse_file(filename: str, data: bytes) -> str:
    """Parse a file and return plain text (page markers embedded for PDFs)."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        pages = _parse_pdf(data)
        return "\n\n".join(f"[Page {p}]\n{t}" for p, t in pages)
    parsers = {
        ".docx": _parse_docx,
        ".pptx": _parse_pptx,
        ".txt": _parse_text,
        ".md": _parse_text,
    }
    parser = parsers.get(ext)
    if parser is None:
        raise ValueError(f"Unsupported file type: {ext}")
    return parser(data)


def parse_file_with_pages(filename: str, data: bytes) -> list[tuple[int, str]]:
    """Parse a file and return (page_number, text) pairs.

    For non-PDF formats, the whole document is treated as page 1.
    """
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return _parse_pdf(data)
    text = parse_file(filename, data)
    return [(1, text)] if text.strip() else []


# ---------- Chunking ----------

def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> list[str]:
    """Split text into overlapping chunks at paragraph/sentence boundaries."""
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        end = min(i + chunk_size, n)
        if end < n:
            # prefer to break at a natural boundary in the second half of the window
            for sep in ("\n\n", "\n", ". ", " "):
                idx = text.rfind(sep, i + chunk_size // 2, end)
                if idx > i:
                    end = idx + len(sep)
                    break
        chunk = text[i:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        i = max(end - overlap, i + 1)
    return chunks


# ---------- Gemini embedding function for Chroma ----------

def _embed_with_retry(
    texts: list[str],
    max_retries: int = 5,
    base_delay: float = 2.0,
) -> Embeddings:
    """Embed texts using Gemini with exponential backoff and model fallback.

    Retries on 503 (UNAVAILABLE) and 429 (RESOURCE_EXHAUSTED). After
    ``max_retries`` failures on the primary model, tries fallback models once
    each before raising.
    """
    last_exc: Exception | None = None

    for model in dict.fromkeys(EMBED_MODEL_FALLBACKS):  # deduplicated, order kept
        delay = base_delay
        for attempt in range(1, max_retries + 1):
            try:
                client = get_embed_client()
                result = client.models.embed_content(
                    model=model,
                    contents=texts,
                )
                return [list(e.values) for e in result.embeddings]
            except Exception as e:
                err_str = str(e)
                is_retryable = any(
                    code in err_str for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED")
                )
                if not is_retryable:
                    raise  # non-transient error — don't retry
                last_exc = e
                wait = delay * (2 ** (attempt - 1))
                logger.warning(
                    "Embedding attempt %d/%d failed for model %s (%s). "
                    "Retrying in %.1fs…",
                    attempt, max_retries, model, err_str[:120], wait,
                )
                time.sleep(wait)

        logger.warning("All %d retries exhausted for model %s. Trying next fallback…", max_retries, model)

    raise RuntimeError(
        f"Gemini embedding failed after retrying all models. Last error: {last_exc}"
    )


class GeminiEmbeddingFunction(EmbeddingFunction):
    """Calls Gemini's embed_content for both indexing and querying,
    with automatic retry + model fallback on transient errors."""

    def __init__(self, model: str = EMBED_MODEL):
        self.model = model

    def __call__(self, input: Documents) -> Embeddings:
        return _embed_with_retry(list(input))


# ---------- Chroma collection ----------

_client: chromadb.PersistentClient | None = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=GeminiEmbeddingFunction(),
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def index_file(filename: str, data: bytes) -> int:
    """Parse, chunk, embed, and store one file. Returns the number of chunks indexed."""
    pages = parse_file_with_pages(filename, data)
    if not pages:
        return 0

    # Build chunks with page metadata
    all_chunks: list[str] = []
    all_metadatas: list[dict] = []
    chunk_idx = 0
    for page_num, page_text in pages:
        for chunk in chunk_text(page_text):
            all_chunks.append(chunk)
            all_metadatas.append({
                "source": filename,
                "chunk": chunk_idx,
                "page": page_num,
            })
            chunk_idx += 1

    if not all_chunks:
        return 0

    coll = _get_collection()
    # Remove any prior chunks for this filename (re-upload safe).
    try:
        coll.delete(where={"source": filename})
    except Exception:
        pass
    ids = [f"{filename}::{i}" for i in range(len(all_chunks))]
    coll.add(documents=all_chunks, ids=ids, metadatas=all_metadatas)
    return len(all_chunks)


def search(query: str, k: int = 5) -> list[dict]:
    coll = _get_collection()
    n = coll.count()
    if n == 0:
        return []
    result = coll.query(query_texts=[query], n_results=min(k, n))
    hits: list[dict] = []
    for doc, meta, dist in zip(
        result["documents"][0],
        result["metadatas"][0],
        result["distances"][0],
    ):
        hits.append({
            "text": doc,
            "source": (meta or {}).get("source", "?"),
            "page": (meta or {}).get("page", None),
            "chunk": (meta or {}).get("chunk", 0),
            "score": round(1.0 - float(dist), 3),
        })
    return hits


def list_sources() -> list[str]:
    coll = _get_collection()
    if coll.count() == 0:
        return []
    data = coll.get(include=["metadatas"])
    metas = data.get("metadatas") or []
    return sorted({m["source"] for m in metas if m and "source" in m})


def clear_index() -> None:
    global _client, _collection
    if _client is None:
        _client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
    try:
        _client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    _collection = None
