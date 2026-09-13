# CSO Strategic Intelligence Agent

A strategic intelligence agent for a Chief Strategy Officer (CSO) of an international financial center. Combines RAG over internal documents, live web search, real-time market data, and Prophet-based time series forecasting — all accessible through a conversational chat interface.

---

## 🌐 Live Demo

**Frontend:** [https://cso-finance-agent.vercel.app](https://cso-finance-agent.vercel.app)

> 🔐 Password protected. To request access, contact ME **

---

## Deployment

| Layer | Platform | Stack |
|---|---|---|
| Frontend | [Vercel](https://vercel.com) | Next.js 15 + Tailwind + Recharts |
| Backend | [AWS Lightsail](https://lightsail.aws.amazon.com) | FastAPI + Docker |
| Vector store | AWS Lightsail (persistent volume) | ChromaDB |
| Briefing storage | AWS Lightsail (persistent volume) | JSON files |

```
User browser
    ↓  HTTPS
Vercel (Next.js frontend)
    ↓  server-side proxy (/api/proxy/*)
AWS Lightsail (FastAPI backend — Docker)
    ↓
ChromaDB · Groq · Tavily · yfinance · Prophet
```

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

```
frontend/                     → Vercel
  app/
    page.tsx                  ← auth gate + 4-view app shell (Chat/Markets/Briefing/Docs)
    api/auth/route.ts         ← server-side password validation
    api/proxy/[...path]/      ← reverse proxy to Lightsail backend
  components/
    ChatWindow.tsx            ← messages, voice input, inline charts, deck download
    MarketChart.tsx           ← Recharts normalised line chart + metric cards
    ForecastChart.tsx         ← Prophet forecast chart (actual + band + point forecast)
    MarketDashboard.tsx       ← Markets / Macro / Forecast tabs
    BriefingPanel.tsx         ← 6-section accordion, generate/refresh/deck buttons
    FileUpload.tsx            ← drag-drop indexing, sources list
  lib/
    api.ts                    ← typed API client

backend/                      → AWS Lightsail (Docker)
  main.py                     ← FastAPI — 12 REST endpoints
  agent.py                    ← Agentic loop — 5 tools
  rag.py                      ← Document parsing, 4-layer chunking, ChromaDB
  market_data.py              ← yfinance + FRED data fetchers
  forecasting.py              ← Prophet forecasting pipeline
  briefing.py                 ← Daily briefing — 6 areas parallel
  search.py                   ← Tavily web search wrapper
  voice.py                    ← Groq Whisper STT + edge-tts TTS
  deck.py                     ← McKinsey-style PPTX generator
  Dockerfile
  docker-compose.yml
```

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

### Supported instruments

Equities (S&P 500, FTSE, Nikkei, Hang Seng), FX (EUR/USD, GBP/USD, USD/AED, USD/SGD), Commodities (Gold, WTI, Brent), Crypto (BTC, ETH), and bond ETF proxies (TLT, HYG).

---

## Local Development

### Option A — Streamlit (main branch, simplest)

```bash
git checkout main
docker compose up --build
```
Open http://localhost:8501

### Option B — Next.js + FastAPI (agent-dep branch)

```bash
git checkout agent-dep
```

Create `.env` at project root:

```
GROQ_API_KEY=your_groq_key
TAVILY_API_KEY=your_tavily_key
APP_PASSWORD=your_password
FRED_API_KEY=your_fred_key        # optional
```

Start the backend:

```bash
cd backend
docker compose up --build
# API at http://localhost:8000
# Docs at http://localhost:8000/docs
```

Start the frontend:

```bash
cd frontend
npm install
npm run dev
# UI at http://localhost:3000
```

---

## Self-hosting on AWS Lightsail

```bash
# On your Lightsail instance
git clone https://github.com/hadilaff/CSO_finance_Agent.git
cd CSO_finance_Agent
git checkout agent-dep

# Create .env with your keys
nano .env

# Start the backend
cd backend
sudo docker-compose up -d --build
```

Open port **8000** in the Lightsail firewall (Networking tab → Add rule → TCP 8000).

Set these in **Vercel → Settings → Environment Variables**:

| Variable | Value |
|---|---|
| `APP_PASSWORD` | your password |
| `API_URL` | `http://your-lightsail-ip:8000` |

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
python eval/run_eval.py --no-judge --delay 3   # fast
python eval/run_eval.py --delay 3              # with LLM judge
python eval/run_eval.py --no-judge --limit 3   # smoke test
```

| Metric | Score |
|---|---|
| Routing match rate | 90% |
| Routing Jaccard avg | 0.90 |
| Retrieval hit rate avg | 88.9% |
| Citation valid rate avg | 100% |
| Must-contain coverage avg | 77.8% |

---

## Security

- Passwords are validated server-side via a Next.js API route — never exposed to the browser
- ChromaDB is persisted in a Docker named volume — survives container restarts
- API keys live in `.env` on the server only — never committed to git
