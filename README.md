# CSO Intelligence Assistant

A strategic intelligence chatbot for a Chief Strategy Officer, combining RAG over internal documents with live web search.

**Stack:** Groq (llama-3.3-70b-versatile) · ONNX local embeddings · ChromaDB · Tavily · Streamlit

---

## Architecture

```
app.py          Streamlit UI — auth gate, document upload, daily briefing, chat
agent.py        Groq agent loop with tool calling (rag_search, web_search, generate_deck)
rag.py          Document parsing, chunking, local ONNX embedding, ChromaDB storage
search.py       Tavily web search wrapper
briefing.py     Daily strategic briefing — 6 intelligence areas, parallel fetch + summarize
voice.py        Voice input (Groq Whisper) + TTS output (edge-tts)
deck.py         McKinsey-style PowerPoint generation from agent tool calls
auth.py         Password gate (hmac.compare_digest)
config.py       API keys, model config, lazy Groq client init
eval/           Evaluation harness — routing, retrieval, citation, must-contain metrics
```

---

## RAG Pipeline

| Step | Detail |
|---|---|
| Parsing | PDF (pdfplumber + table extraction), DOCX, PPTX, TXT, MD |
| Chunking | 4-layer hybrid strategy (see below) |
| Embedding | `all-MiniLM-L6-v2` via ChromaDB's built-in ONNX runtime — **no API key, runs locally** |
| Storage | ChromaDB persistent collection with cosine similarity index |
| Retrieval | Top-6 chunks by cosine similarity, page metadata included |
| Citations | `[Doc: filename, p.N]` inline in every answer |

**Chunking strategy — 4 layers per page:**

| Layer | How | Best for |
|---|---|---|
| `section` | Split at numbered headings (`1. Title`, `## Title`), prepend heading to every sub-chunk | Section-specific questions ("what are our milestones?") |
| `text` | Sliding window (1,200 chars, 200 overlap), split at natural boundaries | Cross-section and keyword queries |
| `bullet` | One chunk per bullet/list item ≥30 chars | Atomic facts ("recruit 12 professionals", "45% progress") |
| `table_row` | One sentence per table cell in natural language | Numeric lookups ("28% growth", "$4.2M budget") |

Each document page produces all 4 chunk types, stored together in ChromaDB. Retrieval picks the best match across all layers.

---

## Quickstart

### 1. Clone and configure

```bash
git clone <repo-url>
```

Edit `.env` and add your API keys:

| Key | Where to get it | Required |
|---|---|---|
| `GROQ_API_KEY` | https://console.groq.com | Yes |
| `TAVILY_API_KEY` | https://tavily.com | Yes |
| `APP_PASSWORD` | Choose password | Yes |


### 2. Run with Docker

```bash
docker compose up --build
```

Open http://localhost:8501

> First startup downloads the ONNX embedding model (~90MB, cached after first run).

### 3. Run locally (without Docker)

```bash
python -m venv .venv

# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

---

## Usage

1. Sign in with your `APP_PASSWORD`
2. Upload internal documents (PDF, DOCX, PPTX, TXT, MD) via the sidebar
3. Click **Index uploaded files** — documents are embedded locally and stored in ChromaDB
4. Ask questions in the chat — the agent searches your docs and/or the web as needed
5. Use the **Today's Strategic Briefing** panel for a daily 6-area intelligence summary
6. Ask for a deck to get a downloadable PowerPoint from any answer

---

## Models

| Component | Model | Provider |
|---|---|---|
| Chat + tool calling | `llama-3.3-70b-versatile` | Groq |
| Voice transcription | `whisper-large-v3-turbo` | Groq |
| Text-to-speech | `en-US-AriaNeural` (edge-tts) | Local / Microsoft Edge |
| Embeddings | `all-MiniLM-L6-v2` (ONNX) | Local |

---

## Evaluation

```bash
# Run eval (no LLM judge — faster)
python eval/run_eval.py --no-judge --delay 3

# Run with LLM judge
python eval/run_eval.py --delay 3

# Smoke test (first 3 rows only)
python eval/run_eval.py --no-judge --limit 3
```

Results are saved to `eval/results.json`. Metrics: routing accuracy, retrieval hit rate, citation validity, must-contain coverage.

### Latest results (10 questions, no LLM judge)

| Metric | Score |
|---|---|
| Routing match rate | 90% |
| Routing Jaccard avg | 0.90 |
| Retrieval hit rate avg | 88.9% |
| Citation valid rate avg | 100% |
| Must-contain coverage avg | 77.8% |

---

## Security note

`APP_PASSWORD` with `hmac.compare_digest` is appropriate for demo and internal use. For production, replace with bcrypt-hashed multi-user credentials and a query audit log.

ChromaDB is persisted in a Docker volume (`chroma_data`) — indexed documents survive container restarts. Only `docker compose down -v` wipes it.
