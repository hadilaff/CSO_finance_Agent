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


def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Return a list of {title, url, content, score} hits from Tavily."""
    client = _get_client()
    resp = client.search(
        query=query,
        max_results=max_results,
        search_depth="advanced",
        include_answer=False,
    )
    return [
        {
            "title": r.get("title", "") or "",
            "url": r.get("url", "") or "",
            "content": r.get("content", "") or "",
            "score": r.get("score", 0),
        }
        for r in resp.get("results", [])
    ]
