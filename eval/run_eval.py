"""Evaluation harness for the RAG/Web agent.

Loads eval/rag_eval_set.csv, runs each question through run_agent, and computes:
  - Tool-routing accuracy: did the agent call the expected tool(s)?
  - Retrieval Hit@k: did rag_search surface the expected source + page?
  - Citation validity: are every [Doc: file, p.N] / [Web: domain] cite real?
  - Must-contain coverage: do key facts appear verbatim in the answer?
  - LLM-as-judge: correctness / faithfulness / focus scored 1-5 by Gemini.

Usage:
    python eval/run_eval.py              # full run
    python eval/run_eval.py --limit 3    # smoke test
    python eval/run_eval.py --no-judge   # skip LLM judge (no extra Gemini calls)
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import run_agent  # noqa: E402
from config import CHAT_MODEL, get_groq_client  # noqa: E402

logger = logging.getLogger(__name__)

EVAL_DIR = Path(__file__).parent
CSV_PATH = EVAL_DIR / "rag_eval_set.csv"
RESULTS_PATH = EVAL_DIR / "results.json"

CITE_DOC_RE = re.compile(r"\[Doc:\s*([^,\]]+?)\s*,\s*p\.?\s*([\d\-,\s]+)\s*\]", re.I)
CITE_WEB_RE = re.compile(r"\[Web:\s*([^\]]+?)\s*\]", re.I)


# ---------- Helpers ----------

def _split(field: str) -> list[str]:
    if not field:
        return []
    return [x.strip() for x in field.split("|") if x.strip()]


def _load_rows() -> list[dict]:
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# ---------- Metrics ----------

def routing_score(expected: list[str], actual: list[str]) -> dict:
    """Jaccard between expected vs actually-called tool names."""
    exp = {t for t in expected if t and t != "none"}
    act = set(actual)
    if not exp and not act:
        return {"score": 1.0, "matched": True}
    if not exp:
        return {"score": 0.0, "matched": False, "extra": sorted(act)}
    union = exp | act
    return {
        "score": round(len(exp & act) / len(union), 3) if union else 0.0,
        "matched": exp == act,
        "missing": sorted(exp - act),
        "extra": sorted(act - exp),
    }


def retrieval_hit(expected_sources: list[str], expected_pages: list[str],
                  rag_results: list[dict]) -> dict:
    """Per expected (source, page), did the top-k chunks include it?"""
    if not expected_sources:
        return {"applicable": False}
    pages = expected_pages or [""] * len(expected_sources)
    hits = []
    for src, page in zip(expected_sources, pages):
        found = False
        for r in rag_results:
            r_src = (r.get("source") or "").lower()
            r_page = str(r.get("page") or "").strip()
            if src.lower() in r_src and (not page or page == r_page):
                found = True
                break
        hits.append({"source": src, "page": page, "hit": found})
    n_hit = sum(1 for h in hits if h["hit"])
    return {
        "applicable": True,
        "hit_rate": round(n_hit / len(hits), 3),
        "details": hits,
    }


def citation_check(answer: str, tool_calls: list[dict]) -> dict:
    """Every [Doc:..]/[Web:..] cited in the answer must trace back to a tool result."""
    rag_sources: set[str] = set()
    web_domains: set[str] = set()
    for tc in tool_calls:
        if tc["name"] == "rag_search":
            for r in (tc.get("result") or {}).get("results", []):
                if r.get("source"):
                    rag_sources.add(r["source"].lower())
        elif tc["name"] == "web_search":
            for r in (tc.get("result") or {}).get("results", []):
                m = re.search(r"https?://([^/]+)", r.get("url", ""))
                if m:
                    web_domains.add(m.group(1).lower().removeprefix("www."))

    doc_cites = CITE_DOC_RE.findall(answer)  # [(filename, pages), ...]
    web_cites = CITE_WEB_RE.findall(answer)

    invalid_docs = [
        c[0] for c in doc_cites
        if not any(c[0].lower() in s for s in rag_sources)
    ]
    invalid_webs = []
    for w in web_cites:
        domain = w.lower().removeprefix("www.").strip()
        # accept partial match either direction (e.g. "ft.com" vs "www.ft.com/section")
        if not any(domain in d or d in domain for d in web_domains):
            invalid_webs.append(w)

    total = len(doc_cites) + len(web_cites)
    invalid = len(invalid_docs) + len(invalid_webs)
    return {
        "total_citations": total,
        "invalid_citations": invalid,
        "valid_rate": 1.0 if total == 0 else round((total - invalid) / total, 3),
        "invalid_doc_cites": invalid_docs,
        "invalid_web_cites": invalid_webs,
    }


def must_contain_check(answer: str, must_contain: list[str]) -> dict:
    if not must_contain:
        return {"applicable": False}
    a = answer.lower()
    hits = [(s, s.lower() in a) for s in must_contain]
    n = sum(1 for _, h in hits if h)
    return {
        "applicable": True,
        "coverage": round(n / len(must_contain), 3),
        "missing": [s for s, h in hits if not h],
    }


JUDGE_PROMPT = """You are an evaluation judge for a strategic-intelligence assistant for a Chief Strategy Officer.

QUESTION:
{question}

REFERENCE ANSWER (ground truth):
{ground_truth}

CANDIDATE ANSWER TO GRADE:
---
{answer}
---

Score on three axes (integers 1-5, 5 best):
- correctness: factual alignment with the reference (5 = all key facts correct; 1 = mostly wrong or fabricated)
- faithfulness: stays grounded, no invented numbers/dates/document names (5 = perfectly grounded)
- focus: answers ONLY what was asked, no unrelated padding (5 = laser focused)

Reply with ONLY a JSON object, no prose, no code fences:
{{"correctness": <int>, "faithfulness": <int>, "focus": <int>, "reason": "one short sentence"}}
"""


def llm_judge(question: str, ground_truth: str, answer: str) -> dict:
    if not ground_truth.strip():
        return {"applicable": False}
    client = get_groq_client()
    prompt = JUDGE_PROMPT.format(question=question, ground_truth=ground_truth, answer=answer)
    try:
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        text = (resp.choices[0].message.content or "").strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.M).strip()
        data = json.loads(text)
        data["applicable"] = True
        return data
    except Exception as e:
        return {"applicable": True, "error": str(e)}


# ---------- Main loop ----------

def _is_quota_error(msg: str) -> bool:
    return any(k in msg for k in ("429", "RESOURCE_EXHAUSTED", "quota"))


def evaluate(
    rows: list[dict],
    use_judge: bool = True,
    delay: float = 0.0,
    quota_wait: float = 65.0,
    already: dict[str, dict] | None = None,
) -> list[dict]:
    """Run each row through the agent and score it.

    delay        — seconds to sleep between rows (pace under free-tier RPM).
    quota_wait   — on a 429 / RESOURCE_EXHAUSTED, sleep this long and retry the row once.
    already      — {id: prior_row_result} to skip rows that already succeeded (--resume).
    """
    out: list[dict] = []
    for i, row in enumerate(rows, 1):
        qid = row["id"]
        q = row["question"]

        if already and qid in already and "error" not in already[qid]:
            out.append(already[qid])
            print(f"[{i}/{len(rows)}] {qid}: (resumed from cache)")
            continue

        if i > 1 and delay > 0:
            time.sleep(delay)

        print(f"[{i}/{len(rows)}] {qid}: {q[:80]}")
        t0 = time.time()
        try:
            result = run_agent(q, history=[])
        except Exception as e:
            err = str(e)
            if _is_quota_error(err):
                print(f"  ! quota hit; sleeping {quota_wait:.0f}s and retrying once")
                time.sleep(quota_wait)
                try:
                    result = run_agent(q, history=[])
                except Exception as e2:
                    print(f"  ! agent error after retry: {e2}")
                    out.append({"id": qid, "question": q, "error": str(e2)})
                    continue
            else:
                print(f"  ! agent error: {err}")
                out.append({"id": qid, "question": q, "error": err})
                continue
        elapsed = round(time.time() - t0, 2)

        answer = result["answer"]
        tool_calls = result["tool_calls"]
        called = [tc["name"] for tc in tool_calls]
        rag_results: list[dict] = []
        for tc in tool_calls:
            if tc["name"] == "rag_search":
                rag_results.extend((tc.get("result") or {}).get("results", []))

        row_out = {
            "id": qid,
            "question": q,
            "answer": answer,
            "elapsed_s": elapsed,
            "tools_called": called,
            "routing": routing_score(_split(row["expected_tools"]), called),
            "retrieval": retrieval_hit(
                _split(row["expected_sources"]),
                _split(row["expected_pages"]),
                rag_results,
            ),
            "citations": citation_check(answer, tool_calls),
            "must_contain": must_contain_check(answer, _split(row["must_contain"])),
            "judge": llm_judge(q, row.get("ground_truth", ""), answer) if use_judge else {"applicable": False, "skipped": True},
        }
        # one-line console summary
        r = row_out["routing"]
        ret = row_out["retrieval"]
        cit = row_out["citations"]
        j = row_out["judge"]
        print(
            f"  routing={'OK' if r['matched'] else 'MISS'}({r['score']}) "
            f"retrieval={ret.get('hit_rate', '-')} "
            f"cites={cit['total_citations'] - cit['invalid_citations']}/{cit['total_citations']} "
            f"judge={(j.get('correctness'), j.get('faithfulness'), j.get('focus')) if j.get('applicable') and 'error' not in j else '-'} "
            f"({elapsed}s)"
        )
        out.append(row_out)
    return out


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def summarize(results: list[dict]) -> dict:
    ok = [r for r in results if "error" not in r]
    return {
        "n": len(results),
        "errors": len(results) - len(ok),
        "routing_match_rate": _avg([1.0 if r["routing"].get("matched") else 0.0 for r in ok]),
        "routing_jaccard_avg": _avg([r["routing"].get("score") for r in ok]),
        "retrieval_hit_rate_avg": _avg([
            r["retrieval"]["hit_rate"] for r in ok if r["retrieval"].get("applicable")
        ]),
        "citation_valid_rate_avg": _avg([
            r["citations"]["valid_rate"] for r in ok if r["citations"]["total_citations"] > 0
        ]),
        "must_contain_coverage_avg": _avg([
            r["must_contain"]["coverage"] for r in ok if r["must_contain"].get("applicable")
        ]),
        "judge_correctness_avg": _avg([
            r["judge"].get("correctness") for r in ok
            if r["judge"].get("applicable") and "error" not in r["judge"]
        ]),
        "judge_faithfulness_avg": _avg([
            r["judge"].get("faithfulness") for r in ok
            if r["judge"].get("applicable") and "error" not in r["judge"]
        ]),
        "judge_focus_avg": _avg([
            r["judge"].get("focus") for r in ok
            if r["judge"].get("applicable") and "error" not in r["judge"]
        ]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N rows (smoke test).")
    parser.add_argument("--no-judge", action="store_true", help="Skip the LLM-as-judge step.")
    parser.add_argument("--ids", type=str, default=None, help="Comma-separated row IDs to run (e.g. R01,W01).")
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds between rows (default 2 for Groq).")
    parser.add_argument("--quota-wait", type=float, default=65.0, help="Sleep on 429 then retry the row once (default 65s).")
    parser.add_argument("--resume", action="store_true", help="Skip rows already succeeded in eval/results.json.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    rows = _load_rows()
    if args.ids:
        wanted = {x.strip() for x in args.ids.split(",")}
        rows = [r for r in rows if r["id"] in wanted]
    if args.limit:
        rows = rows[: args.limit]

    already: dict[str, dict] = {}
    if args.resume and RESULTS_PATH.exists():
        prior = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
        already = {r["id"]: r for r in prior.get("results", [])}
        ok = sum(1 for r in already.values() if "error" not in r)
        print(f"Resume: {ok} prior successful rows will be reused.")

    print(f"Loaded {len(rows)} evaluation rows from {CSV_PATH.name}")
    results = evaluate(
        rows,
        use_judge=not args.no_judge,
        delay=args.delay,
        quota_wait=args.quota_wait,
        already=already if args.resume else None,
    )
    summary = summarize(results)

    RESULTS_PATH.write_text(
        json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\n========== SUMMARY ==========")
    for k, v in summary.items():
        print(f"  {k:30s} {v}")
    print(f"\nFull per-row results: {RESULTS_PATH}")


if __name__ == "__main__":
    main()
