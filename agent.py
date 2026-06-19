"""Groq agent loop with rag_search + web_search tool calling."""
from __future__ import annotations

import json
import time
import logging

from config import CHAT_MODEL, get_groq_client, groq_pool_size, rotate_groq_client
from deck import store_deck
from rag import search as rag_search_fn
from search import web_search as web_search_fn

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a strategic intelligence assistant for a Chief Strategy Officer (CSO) of an international financial center.

You have THREE tools:
- rag_search: call this for ANY question about internal documents, "our" organization, milestones, strategy, reports, initiatives, or performance.
- web_search: call this for competitor activity, regulatory news, market data, or anything external.
- generate_deck: call this when the user asks for a deck, slides, presentation, PPT, or PowerPoint. ALWAYS gather content with rag_search / web_search FIRST, then build the deck strictly from those tool results.

After getting tool results, answer following these rules:
- Answer ONLY what was specifically asked. If asked about milestones, report only milestones — not KPIs, metrics, or related topics unless asked.
- Use the exact wording from the source documents. Do not paraphrase status — if a document says "draft circulated, final due July 2026", do not say "completed".
- 1-2 sentence conclusion first, then up to 5 bullets.
- Cite every fact inline: [Doc: filename, p.N] for internal, [Web: domain] for web.
- If a tool returns no results, say "No relevant documents found" — never invent facts or document names.
- Do not answer from memory when tools should be used.

DECK RULES (McKinsey-style — when using generate_deck):
- Every bullet, table row, and chart value MUST come directly from a rag_search or web_search result. Never invent figures, owners, dates, or document names.
- ACTION TITLES: every slide "title" is a takeaway sentence stating the insight, not a topic label.
  - GOOD: "Budget utilization on track at 62% with two initiatives behind plan"
  - BAD:  "Budget Utilization Snapshot"
- LEAD-IN: provide a short "lead_in" (one sentence, italic gray) that frames the slide. Optional but encouraged.
- SOURCE: provide a "source" string for every content slide, e.g. "Initiative Status Report Q2 2026, p.1-2" or "tavily.com, ft.com, 16 Jun 2026".
- ONE IDEA PER SLIDE. Keep bullets to 3-5, short and parallel.
- Slide types: "bullets" (title + bullet list), "table" (headers + rows of strings), "chart" (categories + numeric series with chart_type bar/column/line/pie).
- Typical structure for a status report: Executive Summary (bullets), Portfolio Summary (table), Completed Milestones (bullets), Budget Utilization (chart), KPIs (table), Risks & Mitigation (bullets), Next Steps (bullets).
- After generate_deck returns, tell the user the deck is ready to download — do not repeat the slide content."""


# ---------- Tool definitions (Groq/OpenAI format) ----------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "rag_search",
            "description": (
                "Search the CSO's uploaded internal documents (institutional knowledge). "
                "Returns the most relevant text chunks with source filenames and page numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query. Use specific terms; rephrase for better recall if needed.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the live web for external intelligence: competitor activity, regulatory updates, "
                "market news, capital flows. Returns titles, URLs, and snippets."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The web search query.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_deck",
            "description": (
                "Create a PowerPoint (.pptx) deck from a structured spec. Use ONLY after gathering "
                "facts via rag_search / web_search. The UI shows the user a download button when this returns."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title":    {"type": "string", "description": "Deck title (cover slide)."},
                    "subtitle": {"type": "string", "description": "Optional cover subtitle (e.g. reporting period)."},
                    "filename": {"type": "string", "description": "Optional output filename (without extension)."},
                    "slides": {
                        "type": "array",
                        "description": "Ordered list of content slides after the cover.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type":  {"type": "string", "enum": ["bullets", "table", "chart", "title"]},
                                "title": {"type": "string", "description": "Action title — a takeaway sentence, not a topic label."},
                                "lead_in":    {"type": "string", "description": "Optional one-sentence framing shown italic below the title."},
                                "source":     {"type": "string", "description": "Source line shown at the bottom of the slide (document + page, or domain + date)."},
                                "subtitle":   {"type": "string"},
                                "bullets":    {"type": "array", "items": {"type": "string"}},
                                "headers":    {"type": "array", "items": {"type": "string"}},
                                "rows": {
                                    "type": "array",
                                    "items": {"type": "array", "items": {"type": "string"}}
                                },
                                "categories": {"type": "array", "items": {"type": "string"}},
                                "series": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "name":   {"type": "string"},
                                            "values": {"type": "array", "items": {"type": "number"}}
                                        },
                                        "required": ["name", "values"]
                                    }
                                },
                                "chart_type": {"type": "string", "enum": ["bar", "column", "hbar", "line", "pie"]}
                            },
                            "required": ["type", "title"]
                        }
                    }
                },
                "required": ["title", "slides"]
            }
        }
    },
]


# ---------- Tool execution ----------

def _exec_rag(query: str) -> dict:
    hits = rag_search_fn(query, k=5)
    if not hits:
        return {"results": [], "note": "No documents indexed or no matches found."}
    return {
        "results": [
            {
                "source": h["source"],
                "page": h.get("page"),
                "score": h["score"],
                "text": h["text"][:1500],
            }
            for h in hits
        ]
    }


def _exec_web(query: str) -> dict:
    try:
        hits = web_search_fn(query, max_results=5)
    except Exception as e:
        return {"error": f"Web search failed: {e}"}
    return {
        "results": [
            {
                "title": h["title"],
                "url": h["url"],
                "snippet": h["content"][:1500],
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


FALLBACK_SYSTEM_PROMPT = (
    "You are a strategic intelligence assistant. The tool-calling system is temporarily "
    "unavailable, so you must answer the user's last question directly from the conversation "
    "context only. Do NOT attempt to call any tools. If you don't have enough grounded "
    "information to answer, say so honestly and ask the user to rephrase or upload "
    "relevant documents."
)


def _strip_tools_from_messages(messages: list[dict]) -> list[dict]:
    """Return a clean message list with no tool calls/results and a relaxed system prompt.

    Used as a fallback when the model emits malformed tool args and we need to recover
    with a plain-text answer instead of erroring out to the user.
    """
    cleaned: list[dict] = [{"role": "system", "content": FALLBACK_SYSTEM_PROMPT}]
    for m in messages:
        role = m.get("role")
        if role == "system" or role == "tool":
            continue
        if role == "assistant" and m.get("tool_calls"):
            continue  # skip assistant turns that were tool-call-only
        cleaned.append({"role": role, "content": m.get("content", "")})
    return cleaned


def _chat_with_retry(client, messages, max_retries=3, base_delay=5.0):
    """Call Groq chat completions with retry on rate-limit errors.

    On 429, rotates to the next API key in the pool (if multiple are configured)
    and retries immediately. Falls back to a no-tools answer if tool generation
    keeps failing.
    """
    last_exc = None
    # When a pool of keys is available, give each key a chance before sleeping.
    effective_max = max(max_retries, groq_pool_size() + 1)
    for attempt in range(1, effective_max + 1):
        try:
            return client.chat.completions.create(
                model=CHAT_MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.0,
            )
        except Exception as e:
            err_str = str(e)
            # Tool generation failed — retry without tools AND with a relaxed system
            # prompt, otherwise the model keeps emitting tool calls into the void.
            if "tool_use_failed" in err_str or "Failed to call a function" in err_str:
                logger.warning("Tool call malformed, retrying without tools: %s", err_str[:120])
                return client.chat.completions.create(
                    model=CHAT_MODEL,
                    messages=_strip_tools_from_messages(messages),
                    temperature=0.0,
                )
            is_retryable = any(
                code in err_str for code in ("503", "502", "429", "rate_limit", "UNAVAILABLE")
            )
            if not is_retryable:
                raise
            last_exc = e
            # On rate-limit, rotate to next key in the pool and retry immediately.
            if ("429" in err_str or "rate_limit" in err_str) and groq_pool_size() > 1:
                new_idx = rotate_groq_client()
                client = get_groq_client()
                logger.warning(
                    "Rate limit on key — rotating to Groq key #%d and retrying immediately (attempt %d/%d).",
                    new_idx, attempt, effective_max,
                )
                continue
            wait = base_delay * attempt if "429" in err_str else base_delay * (2 ** (attempt - 1))
            logger.warning(
                "Groq attempt %d/%d failed (%s). Retrying in %.0fs…",
                attempt, effective_max, err_str[:120], wait,
            )
            time.sleep(wait)
    raise RuntimeError(
        f"Groq chat failed after {effective_max} retries. Last error: {last_exc}"
    )


# ---------- Agent loop ----------

def run_agent(user_message: str, history: list[dict]) -> dict:
    """Run one agent turn.

    Args:
        user_message: The new user question.
        history: Prior turns as [{"role": "user"|"assistant", "text": "..."}, ...].

    Returns:
        {"answer": str, "tool_calls": [{"name", "args", "result"}, ...]}
    """
    client = get_groq_client()

    # Build message list in OpenAI/Groq format
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history:
        role = "user" if turn["role"] == "user" else "assistant"
        messages.append({"role": role, "content": turn["text"]})
    messages.append({"role": "user", "content": user_message})

    tool_trace: list[dict] = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = _chat_with_retry(client, messages)
        msg = response.choices[0].message

        # No tool calls → final answer
        if not msg.tool_calls:
            return {
                "answer": msg.content.strip() if msg.content else "_(no answer)_",
                "tool_calls": tool_trace,
            }

        # Append assistant message with tool calls
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
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
            if handler is None:
                result: dict = {"error": f"Unknown tool: {name}"}
            else:
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
        "answer": (
            "I exceeded the tool-call budget without producing a final answer. "
            "Try rephrasing or narrowing the question."
        ),
        "tool_calls": tool_trace,
    }
