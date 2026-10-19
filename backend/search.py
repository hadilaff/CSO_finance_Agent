"""Tavily web search wrapper."""
from __future__ import annotations

from config import TAVILY_API_KEY

_client = None


def _get_client():
    global _client
    if _client is None:
        if not TAVILY_API_KEY:
            raise RuntimeError(
                "TAVILY_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        from tavily import TavilyClient
        _client = TavilyClient(api_key=TAVILY_API_KEY)
    return _client


def web_search(
    query: str,
    max_results: int = 5,
    topic: str = "general",
    time_range: str | None = None,
) -> list[dict]:
    """Return a list of {title, url, content, score} hits from Tavily.

    topic: "general" or "news" (news weights recent journalism heavier).
    time_range: "day", "week", "month", "year" — restricts result freshness.
    """
    client = _get_client()
    kwargs = {
        "query": query,
        "max_results": max_results,
        "search_depth": "advanced",
        "include_answer": False,
        "topic": topic,
    }
    if time_range:
        kwargs["time_range"] = time_range
    resp = client.search(**kwargs)
    return [
        {
            "title": r.get("title", "") or "",
            "url": r.get("url", "") or "",
            "content": r.get("content", "") or "",
            "score": r.get("score", 0),
        }
        for r in resp.get("results", [])
    ]
