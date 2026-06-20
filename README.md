# CSO Intelligence Assistant

A secure strategic intelligence assistant for the Chief Strategy Officer of an international financial center. Combines RAG over internal documents, live web search, daily intelligence briefings, deck generation, and voice I/O.

**Stack:** Gemini 2.5 Flash (chat + audio) · `gemini-embedding-001` (embeddings) · ChromaDB (vector store) · Tavily (web search) · Streamlit (UI) · python-pptx (deck output) · edge-tts (voice synthesis)

---

## Features

- **Tool-calling agent** — Gemini decides per turn whether to call `rag_search` (internal docs), `web_search` (Tavily), or `generate_deck` (PowerPoint output). Strict citation rules: every fact is tagged `[Doc: file, p.N]` or `[Web: domain]`.
- **Table-aware RAG** — PDF tables are extracted structurally with pdfplumber (default *and* text-alignment strategies for borderless tables), the section heading above each table is detected, and every cell is emitted as a standalone natural-language sentence so cell-level queries (e.g. "digital asset licenses Q2 2026") rank on direct keyword overlap.
- **Daily Strategic Briefing** — six parallel area summaries (Overnight, Market Signals, Competitor Moves, Regulatory Shifts, Performance Alerts, Risk Indicators) generated on demand and persisted per day under `briefings/`.
- **McKinsey-style deck generation** — action titles, lead-in lines, source captions, and slide types `bullets / table / chart`. PPTX is built in-process and offered as a download.
- **Voice I/O** — record a question with the mic (Gemini Flash audio transcription); click "Speak" on any answer for TTS playback (edge-tts).
- **Multi-key Gemini pool** — supply `GEMINI_API_KEY1`, `GEMINI_API_KEY2`, … and the agent rotates on rate-limit errors before falling back to exponential backoff.
- **Password gate** — `APP_PASSWORD` in `.env` protects the UI.

---

## Quickstart

### 1. Configure

```bash
git clone <repo-url>
cd AgentF
cp .env.example .env
```

Edit `.env`:

| Variable | Required | Notes |
|---|---|---|
| `GEMINI_API_KEY` | yes | From https://aistudio.google.com — used for chat, embeddings, and audio transcription |
| `GEMINI_API_KEY1`, `GEMINI_API_KEY2`, … | optional | Additional keys for the rotation pool. Useful on free tier (per-key daily quota). |
| `TAVILY_API_KEY` | yes | From https://tavily.com — used for web search |
| `APP_PASSWORD` | yes | Any string. Required to log into the UI. |
| `GEMINI_CHAT_MODEL` | optional | Default `gemini-2.5-flash` |
| `GEMINI_EMBED_MODEL` | optional | Default `models/gemini-embedding-001` |

### 2. Run with Docker

```bash
docker compose up --build
```

Open http://localhost:8501. ChromaDB is persisted in the `chroma_data` volume so indexed documents survive container restarts.

### 3. Run locally

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux

pip install -r requirements.txt
streamlit run app.py
```

---

## Usage

1. **Sign in** with `APP_PASSWORD`.
2. **Upload documents** (PDF / DOCX / PPTX / TXT / MD) via the sidebar → click *Index uploaded files*.
3. **Generate today's briefing** from the expander at the top of the main panel, or jump straight to the chat.
4. **Ask anything** — the agent picks its tool: internal documents, web, or a fresh deck.
5. **Voice** — open the *Speak your question* expander to record, or click *Speak* on any answer.

---

## Architecture

```
app.py          Streamlit UI (auth gate, upload, chat, briefing, voice, deck downloads)
agent.py        Gemini agent loop with rag_search / web_search / generate_deck tools
rag.py          PDF/DOCX/PPTX parsing, table-aware extraction, chunking, Chroma storage
search.py       Tavily web-search wrapper
deck.py         McKinsey-style PPTX generation via python-pptx
briefing.py     Parallel multi-area daily briefing generator
voice.py        Mic transcription (Gemini) + TTS (edge-tts)
auth.py         APP_PASSWORD gate
config.py       Env vars, Gemini client pool, lazy init
eval/           Evaluation suite (see below)
files/          Sample institutional documents
briefings/      Persisted daily briefing JSON
.chroma/        Persistent vector store (gitignored)
```

### How table-aware RAG indexing works

For each PDF page, `rag.py` does:

1. **Free-text extraction** with pdfplumber (whole-page reading order).
2. **Table detection** — tries `find_tables()` with the default line-based strategy first, then a text-alignment strategy (catches borderless KPI tables that have no drawn lines).
3. **Section-heading lookup** — for each detected table, finds the closest line above its bbox matching `^\d+\.\s+[A-Z]` (e.g. `4. Key Performance Indicators`).
4. **Three representations per table** are appended to the page text:
   - Markdown grid (`| KPI | Q2 2025 | … |`) for structural context
   - One whole-row sentence per data row (`Digital Asset Licenses: Q2 2025 = 12, Q1 2026 = 19, Q2 2026 = 28, Target = 35.`)
   - One per-cell sentence (`In '4. Key Performance Indicators', Digital Asset Licenses Q2 2026: 28.`)
5. **Atomic indexing** — `index_file()` runs the normal chunker on the full page (text + tables in context), *and* indexes each per-row/per-cell sentence as its own Chroma document with `kind='table_row'`. A cell-level query then matches directly on keyword overlap and lands at rank 1.

Top-k retrieval is `k=5` (set in `agent.py`).

---

## Evaluation suite (`eval/`)

Tests routing accuracy, retrieval Hit@k, citation validity, must-contain coverage, and an LLM-as-judge correctness/faithfulness/focus score.

```
eval/
├── rag_eval_set.csv     Test set: question, expected_tools, expected_sources,
│                        expected_pages, must_contain, ground_truth
├── run_eval.py          Main runner — calls run_agent per row, computes all metrics
├── check_retrieval.py   Chat-free Hit@k check (embedding endpoint only)
├── reindex.py           Clears Chroma and re-indexes everything in files/
├── inspect_chunks.py    Dumps stored chunks for one source (no API calls)
└── results.json         Per-row results + summary (gitignored)
```

### Typical workflow

```bash
# 1. Re-index after any parser/chunker change
python eval/reindex.py

# 2. Quickly verify retrieval Hit@k without burning chat quota
python eval/check_retrieval.py
python eval/check_retrieval.py --ids R03 --show-chunks

# 3. Run the full evaluation
python eval/run_eval.py                            # full run, with LLM judge
python eval/run_eval.py --no-judge                 # skip judge (no extra Gemini calls)
python eval/run_eval.py --ids R01,W01              # specific rows
python eval/run_eval.py --resume --delay 8         # resume after quota reset, pace at 8s/row
```

Aggregate summary is printed to stdout; per-row detail goes to `eval/results.json`.

### Metrics computed

| Metric | What it tests |
|---|---|
| `routing_match_rate` | Did the agent call the expected tool set? (Jaccard match) |
| `retrieval_hit_rate` | For RAG rows, did `rag_search` surface the expected `source` + `page`? |
| `citation_valid_rate` | Every cited `[Doc: …]` / `[Web: …]` traces back to an actual tool result |
| `must_contain_coverage` | Key facts present verbatim in the answer |
| `judge_correctness / faithfulness / focus` | LLM-as-judge (Gemini), 1–5 per axis |

### Inspecting Chroma without API calls

```bash
python eval/inspect_chunks.py                                                # list sources
python eval/inspect_chunks.py board_strategy_memo_q2_2026.pdf                # all chunks
python eval/inspect_chunks.py board_strategy_memo_q2_2026.pdf --page 1
python eval/inspect_chunks.py board_strategy_memo_q2_2026.pdf --grep "Digital Asset" --full
```

---

## Notes

- **Free-tier Gemini quota** is 20 chat requests per key per day. The agent rotates across `GEMINI_API_KEY*` and falls back to exponential backoff. For full eval runs, supply 2+ keys or run with `--delay`.
- **Re-indexing required** after any change to `rag.py` parsing or chunking. Streamlit also caches imported modules, so fully restart Streamlit (not just refresh the browser) for parser changes to take effect.
- **PDF source artifacts** (e.g. overlapping cell text in poorly-rendered PDFs) propagate through extraction. The eval flags these via `must_contain`; the fix is at the source PDF, not in the parser.
