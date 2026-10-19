"""FastAPI backend — wraps all Python intelligence modules as REST endpoints.

All heavy logic lives in the existing modules (agent.py, rag.py, etc.).
This file is purely the HTTP layer.

Endpoints
---------
POST   /api/chat                  agentic chat
POST   /api/index                 upload + index documents
GET    /api/sources               list indexed sources
DELETE /api/index                 clear ChromaDB index
POST   /api/market                fetch market prices (yfinance)
POST   /api/macro                 fetch macro indicators (FRED)
POST   /api/forecast              run Prophet forecast
POST   /api/briefing/generate     generate today's briefing
GET    /api/briefing/{date}       load a saved briefing
POST   /api/briefing/deck         build PPTX from briefing
GET    /api/deck/{deck_id}        download a generated PPTX
POST   /api/transcribe            Whisper STT (audio → text)
GET    /api/health                health check
"""
from __future__ import annotations

import sys
import os

# All modules are in the same directory as main.py
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import io
import json
import logging
from datetime import date as _date
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

# ── Project modules (unchanged) ──────────────────────────────────────────────
from agent import run_agent
from briefing import (
    briefing_to_deck_spec,
    generate_briefing,
    load_briefing,
)
from deck import get_deck, store_deck
from forecasting import run_forecast
from market_data import fetch_macro_data, fetch_market_data
from rag import clear_index, index_file, list_sources
from voice import transcribe

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="CSO Intelligence Agent API",
    version="1.0.0",
    description="Strategic intelligence backend — RAG, web search, market data, forecasting.",
)

# CORS — allow Vercel frontend (and localhost for dev)
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,https://*.vercel.app",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten to ALLOWED_ORIGINS in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic request / response models ───────────────────────────────────────

class HistoryTurn(BaseModel):
    role: str          # "user" | "assistant"
    text: str

class ChatRequest(BaseModel):
    message: str
    history: list[HistoryTurn] = Field(default_factory=list)

class ChatToolCall(BaseModel):
    name: str
    args: dict
    result: Any

class ChatResponse(BaseModel):
    answer: str
    tool_calls: list[ChatToolCall]


class MarketRequest(BaseModel):
    tickers: list[str]
    period: str = "3mo"

class MacroRequest(BaseModel):
    series_ids: list[str]
    period: str = "1y"

class ForecastRequest(BaseModel):
    ticker: str
    periods: int = 30
    history_period: str = "2y"


class BriefingDeckRequest(BaseModel):
    date: str          # YYYY-MM-DD


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok"}


# ── Chat ──────────────────────────────────────────────────────────────────────

@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """Run the agentic loop and return the answer + tool trace."""
    try:
        history = [{"role": t.role, "text": t.text} for t in req.history]
        result  = run_agent(req.message, history)
        return ChatResponse(
            answer     = result["answer"],
            tool_calls = result["tool_calls"],
        )
    except Exception as e:
        logger.exception("Chat error")
        raise HTTPException(status_code=500, detail=str(e))


# ── Document indexing ─────────────────────────────────────────────────────────

@app.post("/api/index")
async def index_documents(files: list[UploadFile] = File(...)):
    """Upload one or more documents and index them into ChromaDB."""
    results = []
    for f in files:
        try:
            data   = await f.read()
            n      = index_file(f.filename, data)
            results.append({"filename": f.filename, "chunks": n, "status": "ok"})
        except Exception as e:
            results.append({"filename": f.filename, "status": "error", "detail": str(e)})
    return {"results": results}


@app.get("/api/sources")
def sources():
    """List all indexed document sources."""
    try:
        return {"sources": list_sources()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/index")
def delete_index():
    """Wipe the entire ChromaDB index."""
    try:
        clear_index()
        return {"status": "cleared"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Market data ───────────────────────────────────────────────────────────────

@app.post("/api/market")
def market(req: MarketRequest):
    """Fetch historical price series for one or more tickers via yfinance."""
    try:
        result = fetch_market_data(req.tickers, period=req.period)
        # Convert dataclasses to plain dicts
        return {
            "period":   result.period,
            "interval": result.interval,
            "errors":   result.errors,
            "series": [
                {
                    "ticker":     s.ticker,
                    "label":      s.label,
                    "dates":      s.dates,
                    "values":     s.values,
                    "currency":   s.currency,
                    "pct_change": s.pct_change,
                    "latest":     s.latest,
                }
                for s in result.series
            ],
        }
    except Exception as e:
        logger.exception("Market data error")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/macro")
def macro(req: MacroRequest):
    """Fetch macroeconomic indicators from FRED."""
    try:
        result = fetch_macro_data(req.series_ids, period=req.period)
        return {
            "errors": result.errors,
            "series": [
                {
                    "ticker":     s.ticker,
                    "label":      s.label,
                    "dates":      s.dates,
                    "values":     s.values,
                    "pct_change": s.pct_change,
                    "latest":     s.latest,
                }
                for s in result.series
            ],
        }
    except Exception as e:
        logger.exception("Macro data error")
        raise HTTPException(status_code=500, detail=str(e))


# ── Forecasting ───────────────────────────────────────────────────────────────

@app.post("/api/forecast")
def forecast(req: ForecastRequest):
    """Run a Prophet forecast for a single ticker."""
    try:
        result = run_forecast(
            req.ticker,
            periods        = req.periods,
            history_period = req.history_period,
        )
        if result.error:
            raise HTTPException(status_code=422, detail=result.error)
        return {
            "ticker":          result.ticker,
            "label":           result.label,
            "history_period":  result.history_period,
            "forecast_days":   result.forecast_days,
            "currency":        result.currency,
            "last_actual":     result.last_actual,
            "fc_end_value":    result.fc_end_value,
            "fc_pct_change":   result.fc_pct_change,
            "trend_direction": result.trend_direction,
            # Full arrays for charting
            "hist_dates":      result.hist_dates,
            "hist_values":     result.hist_values,
            "fc_dates":        result.fc_dates,
            "fc_yhat":         result.fc_yhat,
            "fc_lower":        result.fc_lower,
            "fc_upper":        result.fc_upper,
            "trend_dates":     result.trend_dates,
            "trend_values":    result.trend_values,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Forecast error")
        raise HTTPException(status_code=500, detail=str(e))


# ── Daily briefing ────────────────────────────────────────────────────────────

@app.post("/api/briefing/generate")
def briefing_generate():
    """Generate today's strategic briefing (6 areas in parallel)."""
    try:
        today = _date.today()
        generate_briefing(today)
        data  = load_briefing(today)
        return data
    except Exception as e:
        logger.exception("Briefing generate error")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/briefing/{date}")
def briefing_get(date: str):
    """Load a saved briefing by date (YYYY-MM-DD)."""
    try:
        d    = _date.fromisoformat(date)
        data = load_briefing(d)
        if data is None:
            raise HTTPException(status_code=404, detail="No briefing for this date.")
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/briefing/deck")
def briefing_deck(req: BriefingDeckRequest):
    """Build a PPTX deck from a saved briefing."""
    try:
        d    = _date.fromisoformat(req.date)
        data = load_briefing(d)
        if data is None:
            raise HTTPException(status_code=404, detail="No briefing for this date.")
        spec      = briefing_to_deck_spec(data)
        deck_info = store_deck(spec)
        return deck_info
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Briefing deck error")
        raise HTTPException(status_code=500, detail=str(e))


# ── Deck download ─────────────────────────────────────────────────────────────

@app.get("/api/deck/{deck_id}")
def deck_download(deck_id: str):
    """Stream a generated PPTX file for download."""
    deck = get_deck(deck_id)
    if deck is None:
        raise HTTPException(status_code=404, detail="Deck not found (may have expired — regenerate).")
    return Response(
        content     = deck["bytes"],
        media_type  = "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers     = {"Content-Disposition": f'attachment; filename="{deck["filename"]}"'},
    )


# ── Voice transcription ───────────────────────────────────────────────────────

@app.post("/api/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
):
    """Transcribe audio via Groq Whisper. Accepts WAV, MP3, WebM, OGG, FLAC, M4A."""
    try:
        audio_bytes = await file.read()
        text        = transcribe(audio_bytes, file.filename or "audio.wav")
        return {"text": text}
    except Exception as e:
        logger.exception("Transcription error")
        raise HTTPException(status_code=500, detail=str(e))
