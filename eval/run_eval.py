"""Evaluation harness (M4) - Section 7 of the guide.

    python -m eval.run_eval --configs minilm:section:900:6 bge:section:900:6 minilm:fixed:900:6

For each configuration: builds (or reuses) its own Chroma collection from the
Source Register, runs every question through the same LangGraph workflow the
API uses, and computes the six required metrics. Writes per-question results,
summary.json and a markdown report comparing configurations.

Method (disclosed): automatic exact-match scoring.
  answer correctness   expected answer_type AND every must_contain string present (numbers exact)
  citation accuracy    a citation matches an expected doc_id#section (prefix match on section);
                       automatic proxy - the team also spot-checks cited pages by hand (see report)
  abstention accuracy  (expected not_found) == (returned not_found), over all questions
  tool correctness     every expected tool output field equals the actual value
  retrieval hit rate   an expected source appears in the top-k retrieved chunks (retrieval questions)
  latency / cost       p50, p95 latency; mean LLM calls and tokens per question
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import date
from pathlib import Path

from data.db import init_db, one
from data.loader import load_dir
from graph.workflow import run_question
from ingestion.pipeline import bootstrap
from shared.config import RetrievalConfig, settings

HERE = Path(__file__).parent


def _src_match(cite: str, expected: str) -> bool:
    cd, _, cs = cite.partition("#")
    ed, _, es = expected.partition("#")
    return cd == ed and (not es or cs == es or cs.startswith(es + "."))


def score(item: dict, resp: dict, audit: dict) -> dict:
    ans = resp["answer"].lower()
    type_ok = resp["answer_type"] == item["expected_answer_type"]
    contains_ok = all(s.lower() in ans for s in item["must_contain"])
    cites = [f"{c['doc_id']}#{c['section']}" for c in resp["citations"]]
    retrieved = [f"{r['doc_id']}#{r['section']}" for r in audit.get("sources_retrieved", [])]
    exp_src = item["expected_sources"]
    out = {"id": item["id"], "category": item["category"], "answer_type": resp["answer_type"],
           "expected_type": item["expected_answer_type"], "answer_correct": type_ok and contains_ok,
           "abstention_correct": (item["expected_answer_type"] == "not_found") == (resp["answer_type"] == "not_found"),
           "latency_ms": audit["latency_ms"], "llm_calls": audit["llm_calls"], "tokens": audit["tokens"],
           "answer": resp["answer"], "citations": cites, "trace_id": resp["trace_id"]}
    if exp_src:
        out["citation_correct"] = any(_src_match(c, e) for c in cites for e in exp_src)
        if audit.get("sources_retrieved"):
            out["retrieval_hit"] = any(_src_match(r, e) for r in retrieved for e in exp_src)
    if item["expected_tool_outputs"]:
        actual = {t["tool"]: t["output"] for t in resp["tools_invoked"]}
        out["tool_correct"] = all(t in actual and all(actual[t].get(k) == v for k, v in exp.items())
                                  for t, exp in item["expected_tool_outputs"].items())
    return out


def _rate(rows: list[dict], key: str) -> float | None:
    vals = [r[key] for r in rows if key in r]
    return round(sum(vals) / len(vals), 3) if vals else None


def summarise(rows: list[dict], cfg: RetrievalConfig) -> dict:
    lat = sorted(r["latency_ms"] for r in rows)
    p95 = lat[min(len(lat) - 1, round(0.95 * (len(lat) - 1)))]
    return {"config": cfg.label, "n": len(rows),
            "answer_correctness": _rate(rows, "answer_correct"), "citation_accuracy": _rate(rows, "citation_correct"),
            "abstention_accuracy": _rate(rows, "abstention_correct"), "tool_correctness": _rate(rows, "tool_correct"),
            "retrieval_hit_rate": _rate(rows, "retrieval_hit"), "latency_p50_ms": statistics.median(lat),
            "latency_p95_ms": p95, "llm_calls_mean": round(statistics.mean(r["llm_calls"] for r in rows), 2),
            "tokens_mean": round(statistics.mean(r["tokens"] for r in rows), 1)}


def ensure_seeded() -> None:
    init_db()
    if not one("SELECT 1 AS x FROM students WHERE student_id = 'S1001'"):
        if not (settings.students_dir / "students.csv").exists():
            from data.generate_students import generate
            generate(settings.students_dir, 30, 42, 10)
        load_dir(settings.students_dir)


def run(eval_set: Path, configs: list[RetrievalConfig], out: Path) -> list[dict]:
    ensure_seeded()
    items = [json.loads(l) for l in eval_set.read_text().splitlines() if l.strip()]
    out.mkdir(parents=True, exist_ok=True)
    summaries = []
    for cfg in configs:
        t0 = time.time()
        print(f"[{cfg.label}] indexing: {bootstrap(settings.register_csv, cfg)} ({time.time() - t0:.1f}s)")
        rows = []
        for it in items:
            resp, audit = run_question(it["question"], it["student_id"], date.fromisoformat(it["as_of_date"]), cfg)
            rows.append(score(it, resp, audit))
        (out / f"results_{cfg.label.replace('/', '_')}.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        s = summarise(rows, cfg)
        s["failures"] = [f"{r['id']} ({r['category']}): expected {r['expected_type']}, got {r['answer_type']} - "
                         f"{r['answer'][:110]}" for r in rows if not r["answer_correct"]]
        summaries.append(s)
        print(json.dumps({k: v for k, v in s.items() if k != "failures"}, indent=1))
    (out / "summary.json").write_text(json.dumps(summaries, indent=2))
    (out / "report.md").write_text(report(summaries, items))
    return summaries


def report(summaries: list[dict], items: list[dict]) -> str:
    metrics = ["answer_correctness", "citation_accuracy", "abstention_accuracy", "tool_correctness",
               "retrieval_hit_rate", "latency_p50_ms", "latency_p95_ms", "llm_calls_mean", "tokens_mean"]
    lines = ["# Evaluation report", "",
             f"Model: `{'mock' if settings.mock_llm else settings.llm_model}`. Questions: {len(items)} "
             f"({', '.join(f'{c}: {n}' for c, n in sorted(_count(items).items()))}).", "",
             "Method: automatic exact match (see eval/run_eval.py docstring). Citation accuracy is an automatic "
             "proxy; spot-check the cited page for each retrieved_fact answer and record any disagreement here.", "",
             "| metric | " + " | ".join(s["config"] for s in summaries) + " |",
             "|---|" + "---|" * len(summaries)]
    for m in metrics:
        lines.append(f"| {m} | " + " | ".join(str(s[m]) for s in summaries) + " |")
    best = max(summaries, key=lambda s: ((s["answer_correctness"] or 0), (s["retrieval_hit_rate"] or 0),
                                         -s["latency_p50_ms"]))
    lines += ["", f"Chosen configuration: **{best['config']}** (highest answer correctness, then retrieval "
                  "hit rate, then lower latency).", "", "## Failures"]
    for s in summaries:
        lines.append(f"\n**{s['config']}**")
        lines += [f"- {f}" for f in s["failures"]] or ["- none"]
    return "\n".join(lines) + "\n"


def _count(items):
    out = {}
    for i in items:
        out[i["category"]] = out.get(i["category"], 0) + 1
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", default=str(HERE / "eval_set.jsonl"))
    ap.add_argument("--configs", nargs="+", default=["minilm:section:900:6", "bge:section:900:6",
                                                     "minilm:fixed:900:6"])
    ap.add_argument("--out", default=str(HERE / "results"))
    a = ap.parse_args()
    run(Path(a.set), [RetrievalConfig.parse(c) for c in a.configs], Path(a.out))


if __name__ == "__main__":
    main()
