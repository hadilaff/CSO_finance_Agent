from __future__ import annotations

import json
import logging
import time

from config import CHAT_MODEL, get_groq_client
from deck import store_deck
from forecasting import run_forecast, FORECASTABLE_TICKERS
from market_data import (
    fetch_market_data,
    fetch_macro_data,
    get_ticker_info,
    PRESET_WATCHLIST,
    PRESET_MACRO,
)
from rag import search as rag_search_fn
from search import web_search as web_search_fn

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a strategic intelligence assistant for a Chief Strategy Officer (CSO) of an international financial center.

You have FIVE tools:
- rag_search: call this for ANY question about internal documents, "our" organization, milestones, strategy, reports, initiatives, performance, KPIs, licensed entities, licensed firms, registration numbers, fintech, or benchmarking.
- web_search: call this for competitor activity, regulatory news, or anything requiring live external context.
- market_data: call this for ANY question about prices, rates, market performance, equity indices, FX, commodities, crypto, ETFs, or time series charts. Examples: "show me S&P 500 over 6 months", "how has EUR/USD moved this year?", "compare gold and bitcoin YTD", "what is the US 10Y yield?".
- macro_data: call this for macroeconomic indicators from FRED — inflation (CPI), unemployment, interest rates, yield spreads, VIX, dollar index.
- forecast_market: call this for ANY question about future prices, forecasts, projections, predictions, or expected direction. Examples: "forecast gold for the next 30 days", "where will EUR/USD be in 60 days?", "what is the outlook for Bitcoin?", "predict S&P 500 trend". Always prefer this over market_data when the user is asking about the future.

When the user asks for a deck, slides, or presentation:
- Call rag_search (and web_search if needed) to gather the content.
- Then respond with a brief summary of what you found — the deck will be built automatically.
- Do NOT output any JSON, tool calls, or code in your response.

After getting tool results, answer following these rules:
- Answer ONLY what was specifically asked.
- If tool results are returned, you MUST use them — even if the match seems indirect.
- Only say "No relevant documents found" if the tool literally returned an empty results list.
- Use the exact wording and numbers from the source. Never upgrade a status or invent figures.
- 1-2 sentence conclusion first, then up to 5 bullets.
- Cite every fact inline: [Doc: filename, p.N] for internal docs, [Web: domain] for web, [Market: ticker] for market data, [Macro: series_id] for FRED data, [Forecast: ticker] for forecast results.
- Do not answer from memory when tools should be used.
- For market_data and macro_data results: always mention the period, the latest value, and the % change over the period.
- For forecast_market results: always state the last actual price, the forecasted end value, the % change, the confidence interval bounds, and the trend direction (upward/flat/downward)."""


# ── Tool schemas ─────────────────────────────────────────────────────────────

# Flat ticker list for the enum (keeps the schema small)
_ALL_TICKERS = [t for g in PRESET_WATCHLIST.values() for t in g]
_ALL_MACRO   = list(PRESET_MACRO.keys())

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "rag_search",
            "description": (
                "Search internal uploaded documents (strategy reports, board memos, KPI reports, HR docs, "
                "insurance policies, project requirements). "
                "For insurance/assurance questions, call MULTIPLE TIMES with different French keyword variants."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query in the language of the document."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the live web for external intelligence: competitor moves, regulatory updates, market news.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The web search query."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "market_data",
            "description": (
                "Fetch historical price / rate time series for equities, FX, commodities, crypto, and ETFs via Yahoo Finance. "
                "Use for any question about market performance, price trends, or comparisons over time. "
                f"Available preset tickers: {', '.join(_ALL_TICKERS[:30])} (and more). "
                "You can also pass any valid Yahoo Finance ticker (e.g. 'AAPL', 'MSFT', '^VIX')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of Yahoo Finance tickers. E.g. ['^GSPC', 'EURUSD=X', 'GC=F'].",
                    },
                    "period": {
                        "type": "string",
                        "enum": ["1d", "5d", "1mo", "3mo", "6mo", "ytd", "1y", "2y", "5y", "max"],
                        "description": "Look-back window. Default: '3mo'.",
                    },
                },
                "required": ["tickers"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "macro_data",
            "description": (
                "Fetch macroeconomic time series from the FRED database (Federal Reserve). "
                "Use for inflation (CPI), unemployment, interest rates, yield spreads, VIX, dollar index. "
                f"Available series: {', '.join(f'{k} ({v})' for k, v in list(PRESET_MACRO.items())[:6])}."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "series_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": f"FRED series IDs. Presets: {', '.join(_ALL_MACRO)}.",
                    },
                    "period": {
                        "type": "string",
                        "enum": ["1mo", "3mo", "6mo", "1y", "2y", "5y"],
                        "description": "Look-back window. Default: '1y'.",
                    },
                },
                "required": ["series_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forecast_market",
            "description": (
                "Forecast future prices for a financial instrument using a Prophet time series model. "
                "Use this for ANY question about future prices, forecasts, projections, predictions, or outlook. "
                "The model is trained on historical daily prices and returns a point forecast with confidence bands and trend direction. "
                f"Supported tickers: {', '.join(f'{t} ({l})' for t, l in list(FORECASTABLE_TICKERS.items())[:10])} (and more). "
                "You can also try any valid Yahoo Finance ticker."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Yahoo Finance ticker to forecast. E.g. 'GC=F' for Gold, 'BTC-USD' for Bitcoin, '^GSPC' for S&P 500.",
                    },
                    "periods": {
                        "type": "integer",
                        "description": "Number of calendar days to forecast ahead. Default: 30. Max recommended: 90.",
                    },
                    "history_period": {
                        "type": "string",
                        "enum": ["6mo", "1y", "2y", "5y"],
                        "description": "How much historical data to train on. More history = better seasonality. Default: '2y'.",
                    },
                },
                "required": ["ticker"],
            },
        },
    },
]


# ── Tool handlers ─────────────────────────────────────────────────────────────

def _exec_rag(query: str) -> dict:
    hits = rag_search_fn(query, k=12)
    if not hits:
        return {"results": [], "note": "No documents indexed or no matches found."}
    return {
        "results": [
            {
                "source": h["source"],
                "page":   h.get("page"),
                "score":  h["score"],
                "text":   h["text"][:1200],
            }
            for h in hits
        ]
    }


def _exec_web(query: str) -> dict:
    try:
        hits = web_search_fn(query, max_results=3)
    except Exception as e:
        return {"error": f"Web search failed: {e}"}
    return {
        "results": [
            {
                "title":   h["title"],
                "url":     h["url"],
                "snippet": h["content"][:600],
            }
            for h in hits
        ]
    }


def _exec_market(tickers: list[str], period: str = "3mo") -> dict:
    result = fetch_market_data(tickers, period=period)
    return result.to_agent_dict()


def _exec_macro(series_ids: list[str], period: str = "1y") -> dict:
    result = fetch_macro_data(series_ids, period=period)
    return result.to_agent_dict()


def _exec_deck(title: str, slides: list, subtitle: str | None = None,
               filename: str | None = None, **_extra) -> dict:
    spec = {"title": title, "slides": slides}
    if subtitle:
        spec["subtitle"] = subtitle
    if filename:
        spec["filename"] = filename
    try:
        return store_deck(spec)
    except Exception as e:
        return {"error": f"Deck generation failed: {e}"}


def _exec_forecast(
    ticker: str,
    periods: int = 30,
    history_period: str = "2y",
) -> dict:
    result = run_forecast(ticker, periods=periods, history_period=history_period)
    return result.to_agent_dict()


TOOL_HANDLERS = {
    "rag_search":      _exec_rag,
    "web_search":      _exec_web,
    "market_data":     _exec_market,
    "macro_data":      _exec_macro,
    "forecast_market": _exec_forecast,
}


# ── Retry wrapper ─────────────────────────────────────────────────────────────

MAX_TOOL_ROUNDS = 6


def _chat_with_retry(
    client, messages,
    tool_choice: str = "auto",
    max_retries: int = 3,
    base_delay: float = 3.0,
    any_tools_ran: bool = False,
):
    """Groq chat with retry on rate-limit and tool-generation errors."""
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            return client.chat.completions.create(
                model=CHAT_MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice=tool_choice,
                temperature=0.0,
            )
        except Exception as e:
            err_str = str(e)
            if "tool_use_failed" in err_str or "Failed to call a function" in err_str:
                if attempt < max_retries:
                    logger.warning("Tool call generation failed (attempt %d), retrying…", attempt)
                    time.sleep(1.0)
                    continue
                if any_tools_ran:
                    logger.warning("Tool generation failed — answering from existing results.")
                    return client.chat.completions.create(
                        model=CHAT_MODEL,
                        messages=messages,
                        temperature=0.0,
                    )
                logger.warning("Tool generation failed with no results — refusing.")
                from types import SimpleNamespace
                fake_msg = SimpleNamespace(
                    tool_calls=None,
                    content="I was unable to search for this question. Please try rephrasing it.",
                )
                return SimpleNamespace(choices=[SimpleNamespace(message=fake_msg)])
            is_retryable = any(c in err_str for c in ("503", "502", "429", "rate_limit", "UNAVAILABLE"))
            if not is_retryable:
                raise
            last_exc = e
            wait = base_delay * attempt if "429" in err_str else base_delay * (2 ** (attempt - 1))
            logger.warning("Groq attempt %d/%d failed. Retrying in %.0fs…", attempt, max_retries, wait)
            time.sleep(wait)
    raise RuntimeError(f"Groq chat failed after {max_retries} retries. Last error: {last_exc}")


# ── Deck builder ──────────────────────────────────────────────────────────────

_DECK_BUILDER_PROMPT = """You are a McKinsey-style deck builder. Given a user request and retrieved document chunks, produce a JSON deck spec.

Rules:
- Use ONLY facts from the provided chunks. Never invent numbers, names, or dates.
- Every slide title must be an ACTION TITLE (a takeaway sentence, not a topic label).
  GOOD: "Two initiatives at risk threaten Q3 2026 targets"
  BAD:  "Risk Summary"
- Include a mix of slide types: bullets, table, chart where data supports it.
- Keep bullets to 3-5 per slide, short and parallel.
- source field: cite the document filename and page, e.g. "report_q2_2026.pdf, p.1"

Return ONLY a valid JSON object — no prose, no code fences:
{
  "title": "deck title",
  "subtitle": "optional subtitle",
  "filename": "output_filename_no_extension",
  "slides": [
    {"type": "bullets", "title": "action title", "lead_in": "optional framing sentence", "bullets": ["..."], "source": "file.pdf, p.1"},
    {"type": "table",   "title": "action title", "headers": ["Col1","Col2"], "rows": [["a","b"]], "source": "file.pdf, p.2"},
    {"type": "chart",   "title": "action title", "categories": ["A","B"], "series": [{"name": "S", "values": [1,2]}], "chart_type": "bar", "source": "file.pdf, p.2"}
  ]
}"""


def _build_deck_from_rag(client, user_message: str, rag_results: list[dict]) -> dict:
    sources_block = "\n\n".join(
        f"[{r['source']}, p.{r.get('page', '?')}]\n{r['text'][:600]}"
        for r in rag_results[:8]
    )
    prompt = (
        f"User request: {user_message}\n\n"
        f"Retrieved document chunks:\n{sources_block}\n\n"
        "Build a McKinsey-style deck spec as JSON."
    )
    try:
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": _DECK_BUILDER_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        import re as _re
        raw = (resp.choices[0].message.content or "").strip()
        raw = _re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=_re.M).strip()
        spec = json.loads(raw)
        return _exec_deck(**spec)
    except Exception as e:
        logger.warning("Deck builder failed (%s) — using simple fallback", e)
        bullets = [r["text"][:200] for r in rag_results[:5]]
        sources = ", ".join({r["source"] for r in rag_results})
        spec = {
            "title": user_message[:80],
            "slides": [{"type": "bullets", "title": "Key findings", "bullets": bullets, "source": sources}],
        }
        return _exec_deck(**spec)


# ── Agent loop ────────────────────────────────────────────────────────────────

def run_agent(user_message: str, history: list[dict]) -> dict:
    client = get_groq_client()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history:
        role = "user" if turn["role"] == "user" else "assistant"
        messages.append({"role": role, "content": turn["text"]})
    messages.append({"role": "user", "content": user_message})

    tool_trace: list[dict] = []
    has_rag_results  = False
    any_tools_ran    = False

    deck_keywords     = ("deck", "slides", "presentation", "ppt", "powerpoint")
    market_keywords   = ("price", "chart", "plot", "market", "stock", "equity", "index",
                         "forex", "fx", "currency", "rate", "commodity", "gold", "oil",
                         "crypto", "bitcoin", "etf", "yield", "inflation", "vix",
                         "performance", "return", "trend", "s&p", "nasdaq", "dow",
                         "eur", "usd", "gbp", "jpy", "compare", "ytd", "1y", "6mo")
    forecast_keywords = ("forecast", "predict", "projection", "outlook", "future",
                         "next 30", "next 60", "next 90", "where will", "expected",
                         "will it", "going to", "estimate")

    is_deck_request     = any(kw in user_message.lower() for kw in deck_keywords)
    is_market_request   = any(kw in user_message.lower() for kw in market_keywords)
    is_forecast_request = any(kw in user_message.lower() for kw in forecast_keywords)

    for _ in range(MAX_TOOL_ROUNDS):
        response = _chat_with_retry(client, messages, any_tools_ran=any_tools_ran)
        msg = response.choices[0].message

        if not msg.tool_calls:
            answer = (msg.content or "_(no answer)_").strip()
            import re as _re
            answer = _re.sub(
                r'\[(?!Doc:|Web:|Market:|Macro:)([^\]]+?\.(?:pdf|docx|pptx|txt|md)[^\]]*)\]',
                r'[Doc: \1]',
                answer,
                flags=_re.IGNORECASE,
            )
            # Hallucination guard — only bypass for market/deck requests which
            # may legitimately answer without calling a search tool
            if not any_tools_ran and not is_deck_request and not is_market_request and not is_forecast_request:
                logger.warning("Model answered without tools — refusing to prevent hallucination.")
                answer = "I was unable to search the documents for this question. Please try rephrasing it."

            # Auto-build deck from accumulated RAG results if model didn't call generate_deck
            deck_called = any(tc["name"] == "generate_deck" for tc in tool_trace)
            if has_rag_results and not deck_called and is_deck_request:
                rag_results = []
                for tc in tool_trace:
                    if tc["name"] == "rag_search":
                        rag_results.extend(tc["result"].get("results", []))
                if rag_results:
                    deck_result = _build_deck_from_rag(client, user_message, rag_results)
                    tool_trace.append({"name": "generate_deck", "args": {}, "result": deck_result})
                    answer = "Your deck is ready to download."

            return {"answer": answer, "tool_calls": tool_trace}

        # Append assistant turn with tool calls
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id":   tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })

        # Execute each tool call and feed results back
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            handler = TOOL_HANDLERS.get(name)
            try:
                result = handler(**args) if handler else {"error": f"Unknown tool: {name}"}
            except Exception as e:
                result = {"error": str(e)}

            if name == "rag_search":
                has_rag_results = True

            any_tools_ran = True
            tool_trace.append({"name": name, "args": args, "result": result})
            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      json.dumps(result),
            })

        # Auto-trigger deck build as soon as we have RAG results
        deck_called = any(tc["name"] == "generate_deck" for tc in tool_trace)
        if is_deck_request and has_rag_results and not deck_called:
            rag_results = []
            for tc in tool_trace:
                if tc["name"] == "rag_search":
                    rag_results.extend(tc["result"].get("results", []))
            if rag_results:
                deck_result = _build_deck_from_rag(client, user_message, rag_results)
                tool_trace.append({"name": "generate_deck", "args": {}, "result": deck_result})
                break

    return {
        "answer": "I exceeded the tool-call budget. Try rephrasing or narrowing the question.",
        "tool_calls": tool_trace,
    }
