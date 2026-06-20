# CSO Intelligence Assistant

A strategic intelligence chatbot for a Chief Strategy Officer, combining RAG over internal documents with live web search.

**Stack:** Groq (llama-3.3-70b) · Gemini embeddings · ChromaDB · Tavily · Streamlit

---

## Quickstart

### 1. Clone and configure

```bash
git clone <repo-url>
cd AgentF
cp .env.example .env
```

Edit `.env` and add your three API keys:

| Key | Where to get it |
|---|---|
| `GEMINI_API_KEY` | https://aistudio.google.com — used for embeddings only |
| `GROQ_API_KEY` | https://console.groq.com — used for chat (free tier is generous) |
| `TAVILY_API_KEY` | https://tavily.com — used for web search |

### 2. Run with Docker

```bash
docker compose up --build
```

Open http://localhost:8501

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

1. Upload internal documents (PDF, DOCX, PPTX, TXT, MD) via the sidebar
2. Click **Index uploaded files**
3. Ask questions in the chat — the assistant will search your documents and/or the web as needed

---

## Architecture

```
app.py          Streamlit UI
agent.py        Groq agent loop with tool calling
rag.py          Document parsing, chunking, embedding (Gemini), ChromaDB storage
search.py       Tavily web search wrapper
config.py       API keys, model config, lazy client init
```

ChromaDB is persisted in a Docker volume (`chroma_data`) so indexed documents survive container restarts.
