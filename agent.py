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

You have TWO tools:
- rag_search: call this for ANY question about internal documents, "our" organization, milestones, strategy, reports, initiatives, performance, KPIs, licensed entities, licensed firms, registration numbers, fintech, or benchmarking.
- web_search: call this for competitor activity, regulatory news, market data, or anything external.

When the user asks for a deck, slides, or presentation:
- Call rag_search (and web_search if needed) to gather the content.
- Then respond with a brief summary of what you found — the deck will be built automatically.
- Do NOT output any JSON, tool calls, or code in your response.

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
- Do not answer from memory when tools should be used."""


# ---------- Tool definitions (Groq/OpenAI format) — rag_search + web_search only ----------
# generate_deck is handled automatically by the agent when deck intent is detected.

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
    "rag_search": _exec_rag,
    "web_search":  _exec_web,
}


# ---------- Retry wrapper ----------

MAX_TOOL_ROUNDS = 6


def _chat_with_retry(client, messages, tool_choice: str = "auto", max_retries: int = 3, base_delay: float = 3.0, any_tools_ran: bool = False):
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
                    logger.warning("Tool call generation failed, answering from existing tool results.")
                    return client.chat.completions.create(
                        model=CHAT_MODEL,
                        messages=messages,
                        temperature=0.0,
                    )
                logger.warning("Tool call generation failed with no tool results — refusing to answer.")
                from types import SimpleNamespace
                fake_msg = SimpleNamespace(
                    tool_calls=None,
                    content="I was unable to search the documents for this question. Please try rephrasing it.",
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


# ---------- Deck builder (fallback when model fails to chain generate_deck) ----------

_DECK_BUILDER_PROMPT = """You are a McKinsey-style deck builder. Given a user request and retrieved document chunks, produce a JSON deck spec.

Rules:
- Use ONLY facts from the provided chunks. Never invent numbers, names, or dates.
- Every slide title must be an ACTION TITLE (a takeaway sentence, not a topic label).
  GOOD: "Two initiatives at risk threaten Q3 2026 targets"
  BAD:  "Risk Summary"
- Include a mix of slide types: bullets, table, chart where data supports it.
- For charts: use "bar" for comparisons, "column" for progress/budget, "pie" for composition.
- Keep bullets to 3-5 per slide, short and parallel.
- Typical structure: Executive Summary (bullets) → Portfolio Status (table) → At-Risk Items (bullets) → Budget Utilization (chart) → Next Steps (bullets)
- source field: cite the document filename and page, e.g. "initiative_status_report_q2_2026.pdf, p.1"

Return ONLY a valid JSON object — no prose, no code fences:
{
  "title": "deck title",
  "subtitle": "optional subtitle",
  "filename": "output_filename_no_extension",
  "slides": [
    {"type": "bullets", "title": "action title", "lead_in": "optional framing sentence", "bullets": ["..."], "source": "file.pdf, p.1"},
    {"type": "table", "title": "action title", "headers": ["Col1","Col2"], "rows": [["a","b"]], "source": "file.pdf, p.2"},
    {"type": "chart", "title": "action title", "categories": ["A","B"], "series": [{"name": "Series", "values": [1,2]}], "chart_type": "bar", "source": "file.pdf, p.2"}
  ]
}"""


def _build_deck_from_rag(client, user_message: str, rag_results: list[dict]) -> dict:
    """Ask Groq to structure RAG chunks into a rich deck spec, then build the PPTX."""
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
            temperature=0.0,
        )
        import re as _re
        raw = (resp.choices[0].message.content or "").strip()
        raw = _re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=_re.M).strip()
        spec = json.loads(raw)
        return _exec_deck(**spec)
    except Exception as e:
        logger.warning("Deck builder LLM call failed (%s) — using simple fallback", e)
        bullets = [r["text"][:200] for r in rag_results[:5]]
        sources = ", ".join({r["source"] for r in rag_results})
        spec = {
            "title": user_message[:80],
            "slides": [{"type": "bullets", "title": "Key findings", "bullets": bullets, "source": sources}],
        }
        return _exec_deck(**spec)


# ---------- Agent loop ----------

def run_agent(user_message: str, history: list[dict]) -> dict:
    client = get_groq_client()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history:
        role = "user" if turn["role"] == "user" else "assistant"
        messages.append({"role": role, "content": turn["text"]})
    messages.append({"role": "user", "content": user_message})

    tool_trace: list[dict] = []
    has_rag_results = False
    any_tools_ran = False

    # Detect deck intent upfront — handle via dedicated flow to avoid
    # generate_deck tool call failures (complex schema confuses the model)
    deck_keywords = ("deck", "slides", "presentation", "ppt", "powerpoint")
    is_deck_request = any(kw in user_message.lower() for kw in deck_keywords)

    for _ in range(MAX_TOOL_ROUNDS):
        response = _chat_with_retry(client, messages, any_tools_ran=any_tools_ran)
        msg = response.choices[0].message

        if not msg.tool_calls:
            answer = (msg.content or "_(no answer)_").strip()
            import re as _re
            answer = _re.sub(
                r'\[(?!Doc:|Web:)([^\]]+?\.(?:pdf|docx|pptx|txt|md)[^\]]*)\]',
                r'[Doc: \1]',
                answer,
                flags=_re.IGNORECASE,
            )
            # Guard: if no tools ran at all and this isn't a deck request,
            # the model answered from memory — replace with a safe refusal.
            if not any_tools_ran and not is_deck_request:
                logger.warning("Model answered without calling any tools — refusing to prevent hallucination.")
                answer = "I was unable to search the documents for this question. Please try rephrasing it."
            # If user asked for a deck but model never called generate_deck,
            # build it automatically from the RAG results we already have.
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

            if name == "rag_search":
                has_rag_results = True

            any_tools_ran = True
            tool_trace.append({"name": name, "args": args, "result": result})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

            # If user asked for a deck and we now have RAG results, build it now
            # instead of waiting for the model to call generate_deck (unreliable)
            deck_called = any(tc["name"] == "generate_deck" for tc in tool_trace)
            if is_deck_request and has_rag_results and not deck_called:
                rag_results = []
                for tc in tool_trace:
                    if tc["name"] == "rag_search":
                        rag_results.extend(tc["result"].get("results", []))
                if rag_results:
                    deck_result = _build_deck_from_rag(client, user_message, rag_results)
                    tool_trace.append({"name": "generate_deck", "args": {}, "result": deck_result})
                    # Don't append to messages — this ends the loop on next iteration
                    break

    return {
        "answer": "I exceeded the tool-call budget. Try rephrasing or narrowing the question.",
        "tool_calls": tool_trace,
    }
