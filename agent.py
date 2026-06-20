"""Gemini agent loop with rag_search + web_search + generate_deck tool calling."""
from __future__ import annotations

import logging
import time

from google.genai import types as gtypes

from config import (
    CHAT_MODEL,
    gemini_pool_size,
    get_gemini_client,
    rotate_gemini_client,
)
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


# ---------- Tool declarations (Gemini format) ----------

_RAG_DECL = gtypes.FunctionDeclaration(
    name="rag_search",
    description=(
        "Search the CSO's uploaded internal documents (institutional knowledge). "
        "Returns the most relevant text chunks with source filenames and page numbers."
    ),
    parameters=gtypes.Schema(
        type=gtypes.Type.OBJECT,
        properties={
            "query": gtypes.Schema(
                type=gtypes.Type.STRING,
                description="The search query. Use specific terms; rephrase for better recall if needed.",
            ),
        },
        required=["query"],
    ),
)

_WEB_DECL = gtypes.FunctionDeclaration(
    name="web_search",
    description=(
        "Search the live web for external intelligence: competitor activity, regulatory updates, "
        "market news, capital flows. Returns titles, URLs, and snippets."
    ),
    parameters=gtypes.Schema(
        type=gtypes.Type.OBJECT,
        properties={
            "query": gtypes.Schema(
                type=gtypes.Type.STRING,
                description="The web search query.",
            ),
        },
        required=["query"],
    ),
)

_DECK_DECL = gtypes.FunctionDeclaration(
    name="generate_deck",
    description=(
        "Create a PowerPoint (.pptx) deck from a structured spec. Use ONLY after gathering "
        "facts via rag_search / web_search. The UI shows the user a download button when this returns."
    ),
    parameters=gtypes.Schema(
        type=gtypes.Type.OBJECT,
        properties={
            "title":    gtypes.Schema(type=gtypes.Type.STRING, description="Deck title (cover slide)."),
            "subtitle": gtypes.Schema(type=gtypes.Type.STRING, description="Optional cover subtitle."),
            "filename": gtypes.Schema(type=gtypes.Type.STRING, description="Optional output filename (without extension)."),
            "slides": gtypes.Schema(
                type=gtypes.Type.ARRAY,
                description="Ordered list of content slides after the cover.",
                items=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "type":     gtypes.Schema(type=gtypes.Type.STRING, description="One of: bullets, table, chart, title."),
                        "title":    gtypes.Schema(type=gtypes.Type.STRING, description="Action title — a takeaway sentence."),
                        "lead_in":  gtypes.Schema(type=gtypes.Type.STRING, description="Optional one-sentence framing."),
                        "source":   gtypes.Schema(type=gtypes.Type.STRING, description="Source line shown at bottom (document + page or domain + date)."),
                        "subtitle": gtypes.Schema(type=gtypes.Type.STRING),
                        "bullets":  gtypes.Schema(type=gtypes.Type.ARRAY, items=gtypes.Schema(type=gtypes.Type.STRING)),
                        "headers":  gtypes.Schema(type=gtypes.Type.ARRAY, items=gtypes.Schema(type=gtypes.Type.STRING)),
                        "rows": gtypes.Schema(
                            type=gtypes.Type.ARRAY,
                            items=gtypes.Schema(
                                type=gtypes.Type.ARRAY,
                                items=gtypes.Schema(type=gtypes.Type.STRING),
                            ),
                        ),
                        "categories": gtypes.Schema(type=gtypes.Type.ARRAY, items=gtypes.Schema(type=gtypes.Type.STRING)),
                        "series": gtypes.Schema(
                            type=gtypes.Type.ARRAY,
                            items=gtypes.Schema(
                                type=gtypes.Type.OBJECT,
                                properties={
                                    "name":   gtypes.Schema(type=gtypes.Type.STRING),
                                    "values": gtypes.Schema(type=gtypes.Type.ARRAY, items=gtypes.Schema(type=gtypes.Type.NUMBER)),
                                },
                                required=["name", "values"],
                            ),
                        ),
                        "chart_type": gtypes.Schema(type=gtypes.Type.STRING, description="bar, column, hbar, line, or pie."),
                    },
                    required=["type", "title"],
                ),
            ),
        },
        required=["title", "slides"],
    ),
)

TOOLS = [gtypes.Tool(function_declarations=[_RAG_DECL, _WEB_DECL, _DECK_DECL])]


# ---------- Tool execution ----------

def _exec_rag(query: str) -> dict:
    hits = rag_search_fn(query, k=3)
    if not hits:
        return {"results": [], "note": "No documents indexed or no matches found."}
    return {
        "results": [
            {
                "source": h["source"],
                "page": h.get("page"),
                "score": h["score"],
                "text": h["text"][:600],
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


def _generate_with_retry(client, contents, config, max_retries: int = 3):
    """Call Gemini generate_content with retry on rate-limit / unavailable errors."""
    last_exc: Exception | None = None
    effective_max = max(max_retries, gemini_pool_size() + 1)
    for attempt in range(1, effective_max + 1):
        try:
            return client.models.generate_content(
                model=CHAT_MODEL,
                contents=contents,
                config=config,
            )
        except Exception as e:
            err_str = str(e)
            is_retryable = any(
                code in err_str
                for code in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "502")
            )
            if not is_retryable:
                raise
            last_exc = e
            if gemini_pool_size() > 1:
                new_idx = rotate_gemini_client()
                client = get_gemini_client()
                logger.warning(
                    "Rate limit on key — rotating to Gemini key #%d and retrying (attempt %d/%d).",
                    new_idx, attempt, effective_max,
                )
                continue
            wait = min(2 * attempt, 30)
            logger.warning(
                "Gemini attempt %d/%d failed (%s). Retrying in %.0fs…",
                attempt, effective_max, err_str[:120], wait,
            )
            time.sleep(wait)
    raise RuntimeError(
        f"Gemini chat failed after {effective_max} retries. Last error: {last_exc}"
    )


# ---------- Agent loop ----------

def _to_content(role: str, text: str) -> gtypes.Content:
    return gtypes.Content(role=role, parts=[gtypes.Part(text=text)])


def run_agent(user_message: str, history: list[dict]) -> dict:
    """Run one agent turn.

    Args:
        user_message: The new user question.
        history: Prior turns as [{"role": "user"|"assistant", "text": "..."}, ...].

    Returns:
        {"answer": str, "tool_calls": [{"name", "args", "result"}, ...]}
    """
    client = get_gemini_client()

    contents: list[gtypes.Content] = []
    for turn in history:
        role = "user" if turn["role"] == "user" else "model"
        contents.append(_to_content(role, turn["text"]))
    contents.append(_to_content("user", user_message))

    config = gtypes.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=TOOLS,
        temperature=0.0,
    )

    tool_trace: list[dict] = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = _generate_with_retry(client, contents, config)
        if not response.candidates:
            return {"answer": "_(no answer)_", "tool_calls": tool_trace}

        model_content = response.candidates[0].content
        parts = model_content.parts or []

        function_calls = [p.function_call for p in parts if p.function_call]
        text_chunks = [p.text for p in parts if p.text]

        # No tool calls → final answer
        if not function_calls:
            answer = "\n".join(text_chunks).strip()
            return {
                "answer": answer or "_(no answer)_",
                "tool_calls": tool_trace,
            }

        # Append the model's response (which contains the tool calls) to history
        contents.append(model_content)

        # Execute each function call and feed results back
        response_parts: list[gtypes.Part] = []
        for fc in function_calls:
            name = fc.name
            args = dict(fc.args) if fc.args else {}

            handler = TOOL_HANDLERS.get(name)
            if handler is None:
                result: dict = {"error": f"Unknown tool: {name}"}
            else:
                try:
                    result = handler(**args)
                except Exception as e:
                    result = {"error": str(e)}

            tool_trace.append({"name": name, "args": args, "result": result})
            response_parts.append(
                gtypes.Part.from_function_response(name=name, response=result)
            )

        contents.append(gtypes.Content(role="user", parts=response_parts))

    return {
        "answer": (
            "I exceeded the tool-call budget without producing a final answer. "
            "Try rephrasing or narrowing the question."
        ),
        "tool_calls": tool_trace,
    }
