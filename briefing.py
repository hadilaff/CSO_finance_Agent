"""Daily Strategic Briefing — direct search + summarize per area.

Skips the iterative agent loop so each area stays within Groq free-tier TPM
limits (8000 tok/min/key). One web/rag fetch + one Groq summarize per area.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date as _date, datetime
from pathlib import Path

from config import (
    CHAT_MODEL,
    PROJECT_DIR,
    get_groq_client,
    groq_pool_size,
    rotate_groq_client,
)
from rag import search as rag_search_fn
from search import web_search as web_search_fn

BRIEFING_DIR = PROJECT_DIR / "briefings"
BRIEFING_DIR.mkdir(exist_ok=True)


# The 6 Daily Intelligence Areas from the assessment (Section 3).
# `tools` controls whether each area pulls from web, rag, or both.
DAILY_AREAS = [
    {
        "key": "overnight",
        "title": "Overnight Intelligence",
        "icon": "🌙",
        "tools": ["web"],
        "query": (
            "Most important developments across global financial centers in the last "
            "24 hours: DIFC Dubai, ADGM Abu Dhabi, MAS Singapore, HKMA Hong Kong, "
            "City of London, New York."
        ),
    },
    {
        "key": "market_signals",
        "title": "Market Signals",
        "icon": "📈",
        "tools": ["web"],
        "query": "Latest global capital flows, investor sentiment, and emerging market trends today.",
    },
    {
        "key": "competitor_moves",
        "title": "Competitor Moves",
        "icon": "🎯",
        "tools": ["web"],
        "query": (
            "Recent strategic moves, partnerships, and announcements by competing "
            "international financial centers (DIFC, ADGM, MAS Singapore, HKMA, "
            "City of London) in the past week."
        ),
    },
    {
        "key": "regulatory",
        "title": "Regulatory Shifts",
        "icon": "⚖️",
        "tools": ["web"],
        "query": (
            "New regulatory and policy changes affecting international financial "
            "centers, asset managers, fintech, and digital asset businesses."
        ),
    },
    {
        "key": "performance",
        "title": "Performance Alerts",
        "icon": "📊",
        "tools": ["rag"],
        "query": "Initiatives behind plan, off-track KPIs, performance issues, leadership attention needed.",
    },
    {
        "key": "risks",
        "title": "Risk Indicators",
        "icon": "⚠️",
        "tools": ["rag", "web"],
        "query": (
            "Risks flagged in our internal documents, and external regulatory, "
            "geopolitical, and market risks to monitor."
        ),
    },
]


BRIEFING_SYSTEM_PROMPT = (
    "You are a strategic intelligence assistant for a Chief Strategy Officer (CSO) "
    "of an international financial center. Write a short briefing on the area below "
    "using ONLY the provided sources. Format:\n"
    "1) One- or two-sentence conclusion first (no bullet, no heading).\n"
    "2) Up to 5 short bullets, each starting with '- '.\n"
    "3) Cite every fact inline: [Web: domain] for web sources, [Doc: filename] for "
    "documents. Use the exact citation labels shown next to each source.\n"
    "If sources are empty or irrelevant, reply exactly: 'No relevant data found.' "
    "Do not invent facts, domains, or document names."
)


# ---------- storage ----------

def _briefing_path(d: _date) -> Path:
    return BRIEFING_DIR / f"{d.isoformat()}.json"


def load_briefing(d: _date) -> dict | None:
    p = _briefing_path(d)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_briefing(d: _date, briefing: dict) -> None:
    _briefing_path(d).write_text(
        json.dumps(briefing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_briefings() -> list[str]:
    return sorted((p.stem for p in BRIEFING_DIR.glob("*.json")), reverse=True)


# ---------- gather sources ----------

def _domain_of(url: str) -> str:
    try:
        return url.split("/")[2].replace("www.", "")
    except Exception:
        return url or "unknown"


def _gather_web(query: str, k: int = 3) -> list[dict]:
    try:
        hits = web_search_fn(query, max_results=k)
    except Exception:
        return []
    out = []
    for h in hits:
        out.append({
            "label": f"[Web: {_domain_of(h.get('url', ''))}]",
            "title": h.get("title", ""),
            "snippet": (h.get("content") or "")[:400],
        })
    return out


def _gather_rag(query: str, k: int = 3) -> list[dict]:
    try:
        hits = rag_search_fn(query, k=k)
    except Exception:
        return []
    out = []
    for h in hits:
        page = h.get("page")
        page_str = f", p.{page}" if page else ""
        out.append({
            "label": f"[Doc: {h['source']}{page_str}]",
            "title": h["source"],
            "snippet": (h.get("text") or "")[:400],
        })
    return out


# ---------- summarize ----------

def _groq_summarize(user_msg: str, max_retries: int = 3) -> str:
    client = get_groq_client()
    effective = max(max_retries, groq_pool_size() + 1)
    last_exc: Exception | None = None
    for attempt in range(1, effective + 1):
        try:
            resp = client.chat.completions.create(
                model=CHAT_MODEL,
                messages=[
                    {"role": "system", "content": BRIEFING_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.0,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            err = str(e)
            retryable = any(c in err for c in ("429", "rate_limit", "413", "503", "502", "UNAVAILABLE"))
            if not retryable:
                raise
            last_exc = e
            if groq_pool_size() > 1:
                rotate_groq_client()
                client = get_groq_client()
            time.sleep(2.0 * attempt)
    raise RuntimeError(f"Groq summarize failed after {effective} retries: {last_exc}")


def _summarize_area(area_title: str, query: str, sources: list[dict]) -> str:
    if not sources:
        return "No relevant data found."
    sources_block = "\n\n".join(
        f"{s['label']} {s['title']}\n{s['snippet']}" for s in sources
    )
    user_msg = (
        f"Area: {area_title}\n"
        f"Query: {query}\n\n"
        f"Sources:\n{sources_block}"
    )
    return _groq_summarize(user_msg)


# ---------- generate ----------

def generate_briefing(d: _date | None = None, progress=None) -> dict:
    """Run all 6 daily-area briefings and cache to disk.

    progress: optional callable(i, total, area_title) called as each area completes.
    """
    if d is None:
        d = _date.today()

    sections: list[dict] = []
    total = len(DAILY_AREAS)
    for i, area in enumerate(DAILY_AREAS, start=1):
        try:
            sources: list[dict] = []
            tool_calls: list[dict] = []
            if "rag" in area["tools"]:
                rag_src = _gather_rag(area["query"])
                sources.extend(rag_src)
                tool_calls.append({
                    "name": "rag_search",
                    "args": {"query": area["query"]},
                    "result": {"count": len(rag_src)},
                })
            if "web" in area["tools"]:
                web_src = _gather_web(area["query"])
                sources.extend(web_src)
                tool_calls.append({
                    "name": "web_search",
                    "args": {"query": area["query"]},
                    "result": {"count": len(web_src)},
                })
            answer = _summarize_area(area["title"], area["query"], sources)
            sections.append({
                "key": area["key"],
                "title": area["title"],
                "icon": area["icon"],
                "answer": answer,
                "tool_calls": tool_calls,
            })
        except Exception as e:
            sections.append({
                "key": area["key"],
                "title": area["title"],
                "icon": area["icon"],
                "answer": f":warning: Failed to generate this section: {e}",
                "tool_calls": [],
            })
        if progress:
            progress(i, total, area["title"])

    briefing = {
        "date": d.isoformat(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sections": sections,
    }
    save_briefing(d, briefing)
    return briefing


# ---------- deck conversion ----------

_BULLET_RE = re.compile(r"^\s*(?:[-•*]|\d+\.)\s+(.*)")


def _extract_bullets(answer: str) -> tuple[str, list[str]]:
    """Split an agent answer into (lead_in, bullets) for slide rendering."""
    lead_lines: list[str] = []
    bullets: list[str] = []
    for line in answer.splitlines():
        m = _BULLET_RE.match(line)
        if m:
            bullets.append(m.group(1).strip())
        elif not bullets and line.strip():
            lead_lines.append(line.strip())
    lead_in = " ".join(lead_lines).strip()
    if not bullets:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", answer) if s.strip()]
        bullets = sentences[:5] or [answer[:400]]
        lead_in = ""
    return lead_in, bullets[:5]


def briefing_to_deck_spec(briefing: dict) -> dict:
    slides: list[dict] = []
    for s in briefing["sections"]:
        lead_in, bullets = _extract_bullets(s["answer"])
        slides.append({
            "type": "bullets",
            "title": f"{s['icon']}  {s['title']}",
            "lead_in": lead_in or None,
            "bullets": bullets,
            "source": f"Daily Briefing {briefing['date']} — internal RAG + web search",
        })
    return {
        "title": f"Strategic Briefing — {briefing['date']}",
        "subtitle": "Daily Intelligence Areas",
        "filename": f"briefing_{briefing['date']}",
        "slides": slides,
    }
