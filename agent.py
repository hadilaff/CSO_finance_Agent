"""Groq agent loop with rag_search + web_search + generate_deck tool calling."""
from __future__ import annotations

import json
import logging
import time

from config import CHAT_MODEL, get_groq_client
from deck import store_deck
from rag import search as rag_search_fn
from search import web_search as web_search_fn

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a strategic intelligence assistant for a Chief Strategy Officer (CSO) of an international financial center.

You have THREE tools you MUST use before answering:
- rag_search: call this for ANY question about internal documents, "our" organization, milestones, strategy, reports, initiatives, performance, or benchmarking.
- web_search: call this for competitor activity, regulatory news, market data, or anything external.
- generate_deck: call this ONLY when the user explicitly asks for a deck, slides, presentation, PPT, or PowerPoint. Always gather content with rag_search/web_search FIRST, then build the deck from those results.

After getting tool results, answer following these rules:
- Answer ONLY what was specifically asked. Respect these definitions:
  * "milestones" or "achievements" = things already accomplished or signed off
  * "at risk" or "issues" = initiatives flagged as delayed or behind schedule
  * "initiatives" = all ongoing work
  Do NOT mix these categories unless the user asks for a full overview.
- If tool results are returned, you MUST use them — even if the match seems indirect. Extract whatever relevant facts are present.
- Only say "No relevant documents found" if the tool literally returned an empty results list.
- Use the exact wording and status from the source. Never upgrade a status.
- 1-2 sentence conclusion first, then up to 5 bullets.
- Cite every fact inline: [Doc: filename, p.N] for internal, [Web: domain] for web.
- Do not answer from memory when tools should be used.

DECK RULES (McKinsey-style):
- Every bullet/table/chart value MUST come from tool results. Never invent figures.
- ACTION TITLES: every slide title is a takeaway sentence, not a topic label.
- After generate_deck returns, tell the user the deck is ready — do not repeat slide content."""


# ---------- Tool definitions (Groq/OpenAI format) ----------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "rag_search",
            "description": "Search the CSO's uploaded internal documents. Returns relevant text chunks with source filenames and page numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query — use specific terms."}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the live web for external intelligence: competitor activity, regulatory updates, market news, capital flows.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The web search query."}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_deck",
            "description": "Create a PowerPoint (.pptx) deck. Use ONLY after gathering facts via rag_search/web_search.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "subtitle": {"type": "string"},
                    "filename": {"type": "string"},
                    "slides": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "description": "bullets, table, chart, or title"},
                                "title": {"type": "string"},
                                "lead_in": {"type": "string"},
                                "source": {"type": "string"},
                                "bullets": {"type": "array", "items": {"type": "string"}},
                                "headers": {"type": "array", "items": {"type": "string"}},
                                "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                                "categories": {"type": "array", "items": {"type": "string"}},
                                "series": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                            "values": {"type": "array", "items": {"type": "number"}},
                                        },
                                        "required": ["name", "values"],
                                    },
                                },
                                "chart_type": {"type": "string"},
                            },
                            "required": ["type", "title"],
                        },
                    },
                },
                "required": ["title", "slides"],
            },
        },
    },
]


# ---------- Tool execution ----------

def _exec_rag(query: str) -> dict:
    hits = rag_search_fn(query, k=6)
    if not hits:
        return {"results": [], "note": "No documents indexed or no matches found."}
    return {
        "results": [
            {
                "source": h["source"],
                "page": h.get("page"),
                "score": h["score"],
                "text": h["text"][:1200],  # increased from 800 to avoid mid-sentence truncation
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
                "title": h["title"],
                "url": h["url"],
                "snippet": h["content"][:600],
            }
            for h in hits
        ]
    }


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


TOOL_HANDLERS = {
    "rag_search":    _exec_rag,
    "web_search":    _exec_web,
    "generate_deck": _exec_deck,
}


# ---------- Retry wrapper ----------

MAX_TOOL_ROUNDS = 6


def _chat_with_retry(client, messages, tool_choice: str = "required", max_retries: int = 3, base_delay: float = 5.0):
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
                if tool_choice != "auto":
                    logger.warning("Tool call generation failed with tool_choice=%s, retrying with auto.", tool_choice)
                    return _chat_with_retry(client, messages, tool_choice="auto", max_retries=1)
                logger.warning("Tool call generation failed, calling without tools to get final answer.")
                # Pass full message history so model can use already-retrieved tool results
                return client.chat.completions.create(
                    model=CHAT_MODEL,
                    messages=messages,
                    temperature=0.0,
                )
            is_retryable = any(c in err_str for c in ("503", "502", "429", "rate_limit", "UNAVAILABLE"))
            if not is_retryable:
                raise
            last_exc = e
            wait = base_delay * attempt if "429" in err_str else base_delay * (2 ** (attempt - 1))
            logger.warning("Groq attempt %d/%d failed. Retrying in %.0fs…", attempt, max_retries, wait)
            time.sleep(wait)
    raise RuntimeError(f"Groq chat failed after {max_retries} retries. Last error: {last_exc}")


# ---------- Agent loop ----------

def run_agent(user_message: str, history: list[dict]) -> dict:
    client = get_groq_client()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history:
        role = "user" if turn["role"] == "user" else "assistant"
        messages.append({"role": role, "content": turn["text"]})
    messages.append({"role": "user", "content": user_message})

    tool_trace: list[dict] = []
    first_round = True

    for _ in range(MAX_TOOL_ROUNDS):
        # Force tool use on the first round so the model always searches before answering.
        # After the first tool result is returned, switch to auto.
        tc_mode = "required" if first_round else "auto"
        response = _chat_with_retry(client, messages, tool_choice=tc_mode)
        first_round = False
        msg = response.choices[0].message

        if not msg.tool_calls:
            answer = (msg.content or "_(no answer)_").strip()
            # Normalize bare citations [filename, p.N] → [Doc: filename, p.N]
            import re as _re
            answer = _re.sub(
                r'\[(?!Doc:|Web:)([^\]]+?\.(?:pdf|docx|pptx|txt|md)[^\]]*)\]',
                r'[Doc: \1]',
                answer,
                flags=_re.IGNORECASE,
            )
            return {"answer": answer, "tool_calls": tool_trace}

        # Append assistant message with tool calls
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })

        # Execute tools and feed results back
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            handler = TOOL_HANDLERS.get(name)
            result: dict = handler(**args) if handler else {"error": f"Unknown tool: {name}"}
            if handler:
                try:
                    result = handler(**args)
                except Exception as e:
                    result = {"error": str(e)}

            tool_trace.append({"name": name, "args": args, "result": result})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

    return {
        "answer": "I exceeded the tool-call budget. Try rephrasing or narrowing the question.",
        "tool_calls": tool_trace,
    }
