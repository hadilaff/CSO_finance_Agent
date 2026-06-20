"""Dump stored chunks for one source file (no embedding API calls).

Usage:
    python eval/inspect_chunks.py                                # list all sources
    python eval/inspect_chunks.py board_strategy_memo_q2_2026.pdf
    python eval/inspect_chunks.py board_strategy_memo_q2_2026.pdf --grep "Digital Asset"
    python eval/inspect_chunks.py board_strategy_memo_q2_2026.pdf --page 1
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import chromadb  # noqa: E402
from chromadb.config import Settings  # noqa: E402

from config import CHROMA_DIR  # noqa: E402
from rag import COLLECTION_NAME  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", nargs="?", default=None,
                        help="Filename to inspect (omit to list all indexed sources).")
    parser.add_argument("--page", type=int, default=None, help="Filter to one page.")
    parser.add_argument("--grep", type=str, default=None,
                        help="Only show chunks containing this substring (case-insensitive).")
    parser.add_argument("--full", action="store_true", help="Print full chunk text (default truncates).")
    args = parser.parse_args()

    client = chromadb.PersistentClient(
        path=str(CHROMA_DIR),
        settings=Settings(anonymized_telemetry=False),
    )
    try:
        coll = client.get_collection(COLLECTION_NAME)
    except Exception:
        print(f"Collection '{COLLECTION_NAME}' not found in {CHROMA_DIR}. Run eval/reindex.py first.")
        return

    if not args.source:
        all_data = coll.get(include=["metadatas"])
        sources = sorted({m["source"] for m in all_data["metadatas"] if m and "source" in m})
        print(f"Collection has {coll.count()} chunks across {len(sources)} sources:")
        for s in sources:
            n = sum(1 for m in all_data["metadatas"] if (m or {}).get("source") == s)
            print(f"  {s}  ({n} chunks)")
        return

    data = coll.get(where={"source": args.source})
    ids = data["ids"]
    docs = data["documents"]
    metas = data["metadatas"]

    rows = list(zip(ids, docs, metas))
    if args.page is not None:
        rows = [(i, d, m) for i, d, m in rows if (m or {}).get("page") == args.page]
    if args.grep:
        needle = args.grep.lower()
        rows = [(i, d, m) for i, d, m in rows if needle in (d or "").lower()]

    print(f"Source: {args.source} — {len(rows)} chunks shown")
    print()
    for cid, doc, meta in rows:
        page = (meta or {}).get("page")
        print(f"=== {cid}  page={page}  len={len(doc)} ===")
        if args.full:
            print(doc)
        else:
            print(doc[:800] + ("…" if len(doc) > 800 else ""))
        print()


if __name__ == "__main__":
    main()
