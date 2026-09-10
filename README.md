# CSO Strategic Intelligence Agent

A strategic intelligence agent for a Chief Strategy Officer (CSO) of an international financial center. Combines RAG over internal documents, live web search, real-time market data, and Prophet-based time series forecasting — all accessible through a conversational chat interface.

**Stack:** Groq (llama-3.3-70b-versatile) · ONNX local embeddings · ChromaDB · Tavily · yfinance · Prophet · Plotly · Streamlit

---

## What it does

| Capability | How |
|---|---|
| Answer questions from internal documents | RAG over indexed PDFs, DOCX, PPTX with 4-layer chunking |
| Answer questions from live web | Tavily web search, cited inline |
| Live market prices & charts | yfinance — equities, FX, commodities, crypto, ETFs |
| Macroeconomic indicators | FRED API — CPI, Fed rate, VIX, yield spreads |
| Price forecasting | Facebook Prophet — trend + seasonality decomposition, 80% confidence band |
| Daily strategic briefing | 6 intelligence areas generated in parallel, saved as JSON |
| PowerPoint generation | McKinsey-style PPTX from any answer or briefing |
| Voice I/O | Groq Whisper STT + edge-tts TTS |

---

## Architecture

Two deployment targets on the `agent-dep` branch:

```
frontend/                     → Vercel
  app/
    page.tsx                  ← root page (auth gate + app shell, 4-view nav)
    layout.tsx
    globals.css
  components/
    ChatWindow.tsx            ← messages, voice input, inline charts, deck download
    MarketChart.tsx           ← Recharts normalised line chart + metric cards
    ForecastChart.tsx         ← Prophet forecast chart (actual + band + point forecast)
    MarketDashboard.tsx       ← Markets / Macro / Forecast tabs
    BriefingPanel.tsx         ← 6-section accordion, generate/refresh/deck buttons
    FileUpload.tsx            ← drag-drop indexing, sources list
  lib/
    api.ts                    ← typed API client (all calls to FastAPI backend)

backend/                      → AWS Lightsail (Docker)
  main.py                     ← FastAPI — 12 REST endpoints
  Dockerfile
  docker-compose.yml

agent.py          Agentic loop — 5 tools: rag_search, web_search, market_data, macro_data, forecast_market
rag.py            Document parsing, 4-layer chunking, ONNX embedding, ChromaDB
search.py         Tavily web search wrapper
market_data.py    yfinance + FRED data fetchers
forecasting.py    Prophet forecasting pipeline
briefing.py       Daily briefing — 6 areas parallel
voice.py          Groq Whisper STT + edge-tts TTS
deck.py           McKinsey-style PPTX generator
auth.py           Password gate
config.py         API keys, model config
eval/             Evaluation harness
```

The `main` branch retains the original Streamlit version (`app.py`) — fully functional for local/Docker use.

---

## Agent Tools

The agent is an agentic loop on Groq with 5 callable tools. The LLM decides which tool(s) to call based on the question:

| Tool | Trigger | Data source |
|---|---|---|
| `rag_search` | Questions about internal documents, KPIs, strategy, initiatives | ChromaDB (local) |
| `web_search` | Competitor moves, regulatory news, external intelligence | Tavily API |
| `market_data` | Prices, FX rates, index levels, commodities, crypto | Yahoo Finance (yfinance) |
| `macro_data` | CPI, unemployment, Fed rate, VIX, yield spreads | FRED API |
| `forecast_market` | Future price forecasts, outlook, projections | Prophet (trained on yfinance history) |

A hallucination guard blocks any answer that tries to respond without calling a tool (except for explicit market/forecast/deck requests).

---

## RAG Pipeline

| Step | Detail |
|---|---|
| Parsing | PDF (pdfplumber + table extraction), DOCX, PPTX, TXT, MD |
| Chunking | 4-layer hybrid strategy (see below) |
| Embedding | `all-MiniLM-L6-v2` via ChromaDB built-in ONNX — **no API key, runs locally** |
| Storage | ChromaDB persistent collection, cosine similarity |
| Retrieval | Top-12 chunks, page metadata included |
| Citations | `[Doc: filename, p.N]` inline in every answer |

**4-layer chunking strategy:**

| Layer | How | Best for |
|---|---|---|
| `section` | Split at numbered/markdown headings, heading prepended to every sub-chunk | Section-specific questions |
| `text` | Sliding window (1,200 chars, 200 overlap), natural boundary preference | Cross-section keyword queries |
| `bullet` | One chunk per bullet/list item ≥ 30 chars | Atomic facts |
| `table_row` | One natural-language sentence per table cell, e.g. `"Digital Asset Licenses Q2 2026: 28"` | Numeric lookups from tables |

---

## Time Series Forecasting (Prophet)

Forecasting is powered by **Facebook Prophet** — an open-source library from Meta that treats forecasting as a curve-fitting problem rather than autoregression.

### How it works

```
yfinance (daily OHLCV history)
    → Prophet model fit
        → trend (piecewise linear, automatic changepoint detection)
        + weekly seasonality (Fourier series, Mon–Fri market patterns)
        + yearly seasonality (Fourier series, annual cycles)
        → forecast: yhat + yhat_lower + yhat_upper (80% confidence band)
```

### Key model parameters

| Parameter | Value | Effect |
|---|---|---|
| `interval_width` | 0.80 | 80% confidence band |
| `weekly_seasonality` | True | Captures Mon–Fri patterns |
| `yearly_seasonality` | True | Captures annual cycles |
| `changepoint_prior_scale` | 0.05 | Moderate trend flexibility, reduces overfitting |

### What it can and cannot do

| Can | Cannot |
|---|---|
| Extrapolate current trend forward | React to news or events |
| Capture seasonal patterns | Predict black swan events |
| Return calibrated confidence intervals | Guarantee price accuracy |
| Detect past trend changepoints automatically | Know about earnings, rate decisions, geopolitics |

### Supported instruments

Equities (S&P 500, FTSE, Nikkei, Hang Seng), FX (EUR/USD, GBP/USD, USD/AED, USD/SGD), Commodities (Gold, WTI, Brent), Crypto (BTC, ETH), and bond ETF proxies (TLT, HYG). Any valid Yahoo Finance ticker is also accepted.

---

## Market Data Dashboard

The **📈 Market Data** panel has three tabs:

- **📊 Markets** — fetch and compare up to N instruments, normalised line chart (base = 100) + raw price toggle, metric cards with % change
- **🏦 Macro (FRED)** — Fed rate, CPI, unemployment, VIX, yield spreads (requires `FRED_API_KEY`)
- **🔮 Forecast** — select instrument + horizon (7–90 days) + training history (6mo–5y), run Prophet, view forecast chart + optional trend decomposition

Charts also render **inline in chat** when the agent calls `market_data`, `macro_data`, or `forecast_market`.

---

## Quickstart

### Branch guide

| Branch | Stack | Use case |
|---|---|---|
| `main` | Streamlit + Docker | Local dev, quick demo |
| `agent-dep` | Next.js + FastAPI + Docker | Vercel frontend + Lightsail backend |

---

### Option A — Streamlit (main branch, simplest)

```bash
git checkout main
docker compose up --build
```
Open http://localhost:8501

---

### Option B — Next.js + FastAPI (agent-dep branch)

#### 1. Clone and configure

```bash
git checkout agent-dep
```

Edit `.env` with your API keys:

| Key | Where | Required |
|---|---|---|
| `GROQ_API_KEY` | https://console.groq.com | Yes |
| `TAVILY_API_KEY` | https://tavily.com | Yes |
| `APP_PASSWORD` | Choose any | Yes |
| `FRED_API_KEY` | https://fred.stlouisfed.org/docs/api/api_key.html | No |

#### 2. Start the FastAPI backend

```bash
# From project root
cd backend
docker compose up --build
# API running at http://localhost:8000
# Docs at http://localhost:8000/docs
```

#### 3. Start the Next.js frontend

```bash
cd frontend
npm install
npm run dev
# UI at http://localhost:3000
```

#### 4. Deploy

**Backend → AWS Lightsail:**
```bash
# On your Lightsail instance
git clone <repo> && cd Agent
cd backend && docker compose up -d --build
```

**Frontend → Vercel:**
```bash
cd frontend
# Set environment variable in Vercel dashboard:
# NEXT_PUBLIC_API_URL = https://your-lightsail-ip-or-domain
vercel deploy
```

---

## Usage

1. Sign in with your `APP_PASSWORD`
2. Upload internal documents via the sidebar → click **Index uploaded files**
3. Ask questions in chat — the agent routes to the right tool automatically
4. Use the **📅 Today's Strategic Briefing** panel for a daily 6-area intelligence summary
5. Use the **📈 Market Data** panel to explore live prices, macro indicators, and forecasts
6. Ask for a deck to get a downloadable McKinsey-style PowerPoint

**Example chat questions:**
- *"What are our Q2 KPIs and which initiatives are at risk?"* → RAG
- *"What is DIFC announcing this week?"* → web search
- *"Show me Gold and Bitcoin over the last 6 months"* → market data + chart
- *"Forecast EUR/USD for the next 30 days"* → Prophet forecast + chart
- *"What is the current Fed rate and VIX?"* → FRED macro data
- *"Build me a deck on our strategic priorities"* → RAG + PowerPoint

---

## Models & Services

| Component | Model / Service | Provider |
|---|---|---|
| Chat + tool calling | `llama-3.3-70b-versatile` | Groq |
| Voice transcription | `whisper-large-v3-turbo` | Groq |
| Text-to-speech | `en-US-AriaNeural` (edge-tts) | Local / Microsoft Edge |
| Embeddings | `all-MiniLM-L6-v2` (ONNX) | Local |
| Market data | Yahoo Finance | yfinance (free, no key) |
| Macro data | FRED database | fredapi (free key) |
| Forecasting | Prophet + Stan | Meta / open-source |
| Web search | Tavily | Tavily API |

---

## Evaluation

```bash
# Fast run (no LLM judge)
python eval/run_eval.py --no-judge --delay 3

# With LLM judge
python eval/run_eval.py --delay 3

# Smoke test (first 3 rows only)
python eval/run_eval.py --no-judge --limit 3
```

Results saved to `eval/results.json`. Metrics: tool routing accuracy, retrieval hit rate, citation validity, must-contain coverage.

### Latest results (10 questions, no LLM judge)

| Metric | Score |
|---|---|
| Routing match rate | 90% |
| Routing Jaccard avg | 0.90 |
| Retrieval hit rate avg | 88.9% |
| Citation valid rate avg | 100% |
| Must-contain coverage avg | 77.8% |

---

## Security

`APP_PASSWORD` with `hmac.compare_digest` is appropriate for demo and internal use. For production, replace with bcrypt-hashed multi-user credentials and a query audit log.

ChromaDB is persisted in a Docker volume (`chroma_data`) — indexed documents survive container restarts. Only `docker compose down -v` wipes the index.
