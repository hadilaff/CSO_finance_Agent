"""Chat-free retrieval check: hits the embedding endpoint only, no Gemini chat calls.

Reads the RAG-flagged rows from eval/rag_eval_set.csv (those with expected_sources set),
calls rag.search at k=3, 5, 8 for each, and reports Hit@k per row plus an
aggregate Hit@k sweep. Lets you verify retrieval quality (e.g. after changing
the PDF parser) without burning chat-model daily quota.

Usage:
    python eval/check_retrieval.py
    python eval/check_retrieval.py --ks 3,5,10
    python eval/check_retrieval.py --show-chunks  # print the top-k chunk text
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag import search as rag_search  # noqa: E402

CSV_PATH = ROOT / "eval" / "rag_eval_set.csv"


def _split(field: str) -> list[str]:
    if not field:
        return []
    return [x.strip() for x in field.split("|") if x.strip()]


def _hits_for(expected_sources: list[str], expected_pages: list[str],
              results: list[dict]) -> int:
    pages = expected_pages or [""] * len(expected_sources)
    n = 0
    for src, page in zip(expected_sources, pages):
        for r in results:
            r_src = (r.get("source") or "").lower()
            r_page = str(r.get("page") or "").strip()
            if src.lower() in r_src and (not page or page == r_page):
                n += 1
                break
    return n


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ks", type=str, default="3,5,8",
                        help="Comma-separated k values to test (default 3,5,8).")
    parser.add_argument("--ids", type=str, default=None,
                        help="Comma-separated row IDs to test (default: all RAG rows).")
    parser.add_argument("--show-chunks", action="store_true",
                        help="Print the top-k chunk text for each query.")
    args = parser.parse_args()

    ks = [int(x) for x in args.ks.split(",")]
    k_max = max(ks)

    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    # Only rows that expect at least one source (i.e. RAG rows)
    rag_rows = [r for r in rows if _split(r["expected_sources"])]
    if args.ids:
        wanted = {x.strip() for x in args.ids.split(",")}
        rag_rows = [r for r in rag_rows if r["id"] in wanted]

    print(f"Checking {len(rag_rows)} RAG rows at k = {ks}")
    print()

    per_k_totals = {k: 0 for k in ks}
    per_k_possible = 0

    for row in rag_rows:
        qid = row["id"]
        q = row["question"]
        expected_srcs = _split(row["expected_sources"])
        expected_pages = _split(row["expected_pages"])
        per_k_possible += len(expected_srcs)

        results = rag_search(q, k=k_max)
        row_hits = {k: _hits_for(expected_srcs, expected_pages, results[:k]) for k in ks}
        for k, h in row_hits.items():
            per_k_totals[k] += h

        flags = " ".join(f"k{k}={h}/{len(expected_srcs)}" for k, h in row_hits.items())
        print(f"  {qid}  {flags}  | {q[:60]}")

        if args.show_chunks:
            for i, r in enumerate(results[:k_max], 1):
                print(f"    [{i}] score={r['score']} {r['source']} p.{r['page']}")
                print(f"        {r['text'][:200].replace(chr(10), ' ')}")
            print()

    print("\n========== AGGREGATE Hit@k ==========")
    for k in ks:
        if per_k_possible:
            rate = per_k_totals[k] / per_k_possible
            print(f"  Hit@{k}: {per_k_totals[k]}/{per_k_possible}  ({rate:.1%})")


if __name__ == "__main__":
    main()
