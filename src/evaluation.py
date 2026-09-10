"""评测层：评测集 + 检索级指标（Hit@K / MRR）+ 特性消融执行器。

用法:
  uv run python -m src.evaluation                          # 默认消融矩阵
  uv run python -m src.evaluation --k 5                    # 指定 K
  uv run python -m src.evaluation add "问题" 'RAG.pdf:0|fastapi_readme.md:3'
  uv run python -m src.evaluation list
LLM 判官（答案级评估）后置，检索级指标先支撑消融。
"""
from __future__ import annotations

import argparse
import json

from src.storage.database import connection

_TABLE = """
CREATE TABLE IF NOT EXISTS eval_cases (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    expected_refs TEXT NOT NULL,
    reference_answer TEXT
)
"""


def ensure_table() -> None:
    with connection() as conn:
        conn.execute(_TABLE)


def add_case(question: str, expected_refs: str, reference_answer: str | None = None) -> int:
    ensure_table()
    with connection() as conn:
        row = conn.execute(
            "INSERT INTO eval_cases (question, expected_refs, reference_answer) VALUES (%s, %s, %s) RETURNING id",
            [question, expected_refs, reference_answer],
        ).fetchone()
    return int(row["id"])


def load_cases() -> list[dict]:
    ensure_table()
    with connection() as conn:
        rows = list(conn.execute("SELECT id, question, expected_refs FROM eval_cases ORDER BY id"))
    return [
        {"id": r["id"], "question": r["question"], "expected": set(filter(None, r["expected_refs"].split("|")))}
        for r in rows
    ]


def retrieval_metrics(results: list[dict], expected: set[str], k: int) -> dict:
    """Hit@K 与 MRR（expected 为 'doc_name:chunk_index' 集合，与检索结果同源格式）。"""
    ids = [f"{r['doc_name']}:{r['chunk_index']}" for r in results[:k]]
    ranks = [i for i, cid in enumerate(ids, 1) if cid in expected]
    hit = bool(ranks)
    return {"hit": hit, "mrr": 1.0 / ranks[0] if ranks else 0.0}


def run_ablation(configs: list[tuple[str, list[str] | None]], top_k: int = 5) -> list[dict]:
    """对每个评测例跑一组 features 配置，输出平均指标行。"""
    from src.retrieval import multi_query_search

    cases = load_cases()
    rows = []
    for label, features in configs:
        hits, mrrs = 0, 0.0
        for case in cases:
            m = retrieval_metrics(multi_query_search(case["question"], top_k, features=features), case["expected"], top_k)
            hits += m["hit"]
            mrrs += m["mrr"]
        n = len(cases) or 1
        rows.append({"label": label, "hit@k": round(hits / n, 3), "mrr": round(mrrs / n, 4)})
    return rows


def main() -> None:
    from src.retrieval import ALL_FEATURES

    parser = argparse.ArgumentParser(description="检索消融评测")
    parser.add_argument("cmd", nargs="?", default="run", choices=["run", "add", "list"])
    parser.add_argument("extra", nargs="*", default=[])
    parser.add_argument("--k", type=int, default=5)
    ns = parser.parse_args()

    if ns.cmd == "add":
        question, refs = ns.extra[0], ns.extra[1]
        print(f"eval case #{add_case(question, refs)}: {question}")
        return
    if ns.cmd == "list":
        for c in load_cases():
            print(c["id"], c["question"], "→", c["expected"])
        return

    import os as _os
    strategy = _os.getenv("RERANK_STRATEGY", "rrf")
    configs = [
        ("none(纯向量)", []),
        ("default(路由+关键词+规划)", None),
        (f"all(+rerank:{strategy})", list(ALL_FEATURES)),
    ]
    ensure_table()
    if not load_cases():
        print("eval_cases 为空：先 `python -m src.evaluation add \"问题\" \"doc:idx|doc:idx\"`")
        return
    print(f"K={ns.k}")
    for row in run_ablation(configs, top_k=ns.k):
        print(f"{row['label']:<18} hit@{ns.k}={row['hit@k']:<8} mrr={row['mrr']}")


if __name__ == "__main__":
    main()
