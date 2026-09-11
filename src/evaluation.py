"""评测层：评测集 + 检索级指标（Hit@K / MRR）+ 特性消融执行器。

用法:
  uv run python -m src.evaluation                          # 默认消融矩阵
  uv run python -m src.evaluation --k 5                    # 指定 K
  uv run python -m src.evaluation add "问题" 'RAG.pdf:0|fastapi_readme.md:3'
  uv run python -m src.evaluation list
  uv run python -m src.evaluation seed-multihop                 # 种多跳评测例（幂等）
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
    """评测例列表。expected 为 'doc_name:chunk_index' 集合，expected_refs 保留原始串供 API 回显。"""
    ensure_table()
    with connection() as conn:
        rows = list(conn.execute(
            "SELECT id, question, expected_refs, reference_answer FROM eval_cases ORDER BY id"
        ))
    return [
        {
            "id": r["id"],
            "question": r["question"],
            "expected_refs": r["expected_refs"] or "",
            "reference_answer": r["reference_answer"],
            "expected": set(filter(None, (r["expected_refs"] or "").split("|"))),
        }
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


# 多跳评测例：答案需要拼接同一文档中相距较远的两块内容。
# 基于真实语料编写：RAG.pdf 实为 ReCite 论文（faithful citation，490 块），fastapi_readme.md 为 FastAPI README。
# ponytail: refs 按当前切块校准，重新切块/换语料后需重新核对索引。
_MULTIHOP_CASES: list[tuple[str, str]] = [
    (
        "ReCite 框架的 CiteLocator 是什么模块、起什么作用？消融实验中把它去掉后，Overall-Strictly F1 大约下降多少？",
        "RAG.pdf:155|RAG.pdf:156|RAG.pdf:277|RAG.pdf:295",
    ),
    (
        "论文提出的 8 类引用意图分类体系 CAP-8 指什么？主实验里 ReCite-SFT(CAP-8) 达到的 Strict F1 是多少？",
        "RAG.pdf:117|RAG.pdf:244|RAG.pdf:246",
    ),
    (
        "QueryPlanner 的训练数据基于多少高密度段落构建？消融实验中移除 QueryPlanner 后 Overall-Strictly F1 会降到多少？",
        "RAG.pdf:150|RAG.pdf:277|RAG.pdf:297",
    ),
    (
        "ReCite 框架的核心设计思路与传统的基于相似度的引用检索有什么区别？它最终 Overall F1 是多少，与次优基线差多少？",
        "RAG.pdf:31|RAG.pdf:58|RAG.pdf:248",
    ),
    (
        "FastAPI 应用如何在本地创建并启动一个最小示例？fastapi[standard] 安装里哪个依赖专门用来运行本地服务器？",
        "fastapi_readme.md:40|fastapi_readme.md:64|fastapi_readme.md:164",
    ),
    (
        "FastAPI 自动生成的两套交互式文档分别在哪个网址访问？",
        "fastapi_readme.md:52|fastapi_readme.md:70",
    ),
]


def seed_multihop_cases() -> int:
    """幂等插入多跳评测例（表对 question 无唯一约束，先查存在再插）。返回新增条数。"""
    ensure_table()
    with connection() as conn:
        existing = {r["question"] for r in conn.execute("SELECT question FROM eval_cases")}
    added = 0
    for question, refs in _MULTIHOP_CASES:
        if question in existing:
            continue
        add_case(question, refs)
        added += 1
    return added


def main() -> None:
    from src.retrieval import ALL_FEATURES, _DEFAULT_FEATURES

    parser = argparse.ArgumentParser(description="检索消融评测")
    parser.add_argument("cmd", nargs="?", default="run", choices=["run", "add", "list", "seed-multihop"])
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

    if ns.cmd == "seed-multihop":
        print(f"新增 {seed_multihop_cases()} 条多跳评测例（已有则跳过）")
        return
    import os as _os
    strategy = _os.getenv("RERANK_STRATEGY", "rrf")
    configs = [
        ("none(纯向量)", []),
        ("default(路由+关键词+规划)", None),
        ("+graph", list(_DEFAULT_FEATURES) + ["graph"]),
        ("+graph+rerank", list(_DEFAULT_FEATURES) + ["graph", "rerank"]),
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
