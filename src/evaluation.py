"""评测层：评测集 + 检索级指标（Hit@K / MRR）+ 特性消融执行器。

用法:
  uv run python -m src.evaluation                          # 默认消融矩阵
  uv run python -m src.evaluation --k 5                    # 指定 K
  uv run python -m src.evaluation --agent                  # 附带 agent 行 + 成本
  uv run python -m src.evaluation add "问题" 'RAG.pdf:0|fastapi_readme.md:3'
  uv run python -m src.evaluation list
  uv run python -m src.evaluation seed-multihop                 # 种多跳评测例（幂等）
LLM 判官（答案级评估）后置，检索级指标先支撑消融。
"""
from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from typing import Any

from src.storage.database import connection

_TABLE = """
CREATE TABLE IF NOT EXISTS eval_cases (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    expected_refs TEXT NOT NULL,
    reference_answer TEXT
)
"""

# runner(question, top_k, features) → list[dict] 或 {"results": [...], "cost": {...}}
AblationRunner = Callable[[str, int, list[str] | None], Any]


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


def load_cases(conn: Any | None = None) -> list[dict]:
    """评测例列表。expected 为 'doc_name:chunk_index' 集合，expected_refs 保留原始串供 API 回显。

    传入 conn 时复用调用方事务：批量改写引用的脚本必须在同一事务内读到自己的写入，
    否则后一篇文档会基于旧值重写、覆盖前一篇的结果。
    """
    if conn is None:
        ensure_table()
        with connection() as own:
            return load_cases(own)
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


def update_expected_refs(case_id: int, expected_refs: str, conn: Any | None = None) -> None:
    """改写某条评测例的引用；传入 conn 时并入调用方事务。"""
    if conn is not None:
        conn.execute("UPDATE eval_cases SET expected_refs = %s WHERE id = %s", [expected_refs, case_id])
        return
    with connection() as own:
        own.execute("UPDATE eval_cases SET expected_refs = %s WHERE id = %s", [expected_refs, case_id])


def remap_expected_refs(refs: str, doc_name: str, mapping: dict[int, int]) -> str:
    """把 expected_refs 里指定文档的 chunk_index 按下标映射重写（去重保序）。

    存量去重会重排 chunk_index；被删掉的重复切片内容仍存在于保留块中，
    因此把旧下标映射到保留块的新下标，评测口径就不会因为清理而失效。
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in (refs or "").split("|"):
        ref = raw.strip()
        if not ref:
            continue
        name, sep, index = ref.rpartition(":")
        if sep and name == doc_name and index.isdigit():
            index = str(mapping.get(int(index), int(index)))
            ref = f"{name}:{index}"
        if ref not in seen:
            seen.add(ref)
            out.append(ref)
    return "|".join(out)


def retrieval_metrics(results: list[dict], expected: set[str], k: int) -> dict:
    """Hit@K 与 MRR（expected 为 'doc_name:chunk_index' 集合，与检索结果同源格式）。"""
    ids = [f"{r['doc_name']}:{r['chunk_index']}" for r in results[:k]]
    ranks = [i for i, cid in enumerate(ids, 1) if cid in expected]
    hit = bool(ranks)
    return {"hit": hit, "mrr": 1.0 / ranks[0] if ranks else 0.0}


def _normalize_runner_out(out: Any) -> tuple[list[dict], dict | None]:
    """兼容 list 结果与 {results, cost} 包装。"""
    if isinstance(out, dict) and "results" in out:
        cost = out.get("cost")
        return list(out["results"] or []), cost if isinstance(cost, dict) else None
    return list(out or []), None


def pipeline_runner(question: str, top_k: int, features: list[str] | None) -> list[dict]:
    from src.retrieval import multi_query_search

    return multi_query_search(question, top_k, features=features)


def agent_runner(
    question: str,
    top_k: int,
    features: list[str] | None,
    *,
    max_steps: int = 6,
) -> dict:
    """Agent 评测 runner：返回 results + cost（步数 / LLM 调用 / 延迟）。"""
    from src.agent import run_agent

    t0 = time.perf_counter()
    out = run_agent(question, top_k=top_k, features=features, max_steps=max_steps)
    latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    if out is None:
        return {
            "results": [],
            "cost": {
                "steps": 0,
                "llm_calls": 0,
                "latency_ms": latency_ms,
                "fallback": True,
            },
        }
    trace = out.get("trace") or {}
    budget = trace.get("budget") or {}
    return {
        "results": out.get("results") or [],
        "cost": {
            "steps": len(trace.get("steps") or []),
            "llm_calls": int(budget.get("llm_calls") or 0),
            "latency_ms": latency_ms,
            "fallback": False,
            "termination": trace.get("termination"),
        },
    }


def run_ablation(
    configs: list[tuple],
    top_k: int = 5,
) -> list[dict]:
    """对每个评测例跑一组配置，输出平均指标行。

    configs 项为 (label, features) 或 (label, features, runner)。
    runner 缺省为 multi_query_search；可返回 list 或 {"results", "cost"}。
    """
    cases = load_cases()
    rows = []
    for item in configs:
        if len(item) == 2:
            label, features = item
            runner: AblationRunner = pipeline_runner
        else:
            label, features, runner = item
        hits, mrrs = 0, 0.0
        steps_sum = llm_sum = 0
        lat_sum = 0.0
        cost_n = 0
        n = len(cases) or 1
        for index, case in enumerate(cases):
            results, cost = _normalize_runner_out(runner(case["question"], top_k, features))
            m = retrieval_metrics(results, case["expected"], top_k)
            hits += m["hit"]
            mrrs += m["mrr"]
            if cost is not None:
                cost_n += 1
                steps_sum += int(cost.get("steps") or 0)
                llm_sum += int(cost.get("llm_calls") or 0)
                lat_sum += float(cost.get("latency_ms") or 0.0)
            # 逐 case 进度：避免长消融时以为卡住
            if cost is not None:
                print(
                    f"  [{label}] {index + 1}/{n} hit={int(m['hit'])} steps={cost.get('steps', 0)}",
                    flush=True,
                )
            else:
                print(f"  [{label}] {index + 1}/{n} hit={int(m['hit'])}", flush=True)
        row: dict = {
            "label": label,
            "hit@k": round(hits / n, 3),
            "mrr": round(mrrs / n, 4),
        }
        if cost_n:
            row["avg_steps"] = round(steps_sum / cost_n, 2)
            row["avg_llm_calls"] = round(llm_sum / cost_n, 2)
            row["avg_latency_ms"] = round(lat_sum / cost_n, 1)
        rows.append(row)
    return rows


def default_eval_configs(*, include_agent: bool = False, agent_steps: int = 6) -> list[tuple]:
    """默认消融矩阵；include_agent 时追加 agent 行（同口径 Hit@K + 成本）。"""
    import os as _os

    from src.retrieval import ALL_FEATURES, _DEFAULT_FEATURES

    strategy = _os.getenv("RERANK_STRATEGY", "rrf")
    configs: list[tuple] = [
        ("none(纯向量)", []),
        ("default(含改写)", None),
        # rewrite 消融对照：默认集只去掉改写，其余不变——差值即改写通道的增益
        ("default-改写(关)", [f for f in _DEFAULT_FEATURES if f != "rewrite"]),
        ("+graph", list(_DEFAULT_FEATURES) + ["graph"]),
        ("+graph+rerank", list(_DEFAULT_FEATURES) + ["graph", "rerank"]),
        (f"all(+rerank:{strategy})", list(ALL_FEATURES)),
    ]
    if include_agent:
        def _agent(q: str, k: int, f: list[str] | None, steps: int = agent_steps) -> dict:
            return agent_runner(q, k, f, max_steps=steps)

        configs.append((f"agent(steps={agent_steps})", None, _agent))
        configs.append((f"agent+graph(steps={agent_steps})", ["graph"], _agent))
    return configs


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
    parser = argparse.ArgumentParser(description="检索消融评测")
    parser.add_argument("cmd", nargs="?", default="run", choices=["run", "add", "list", "seed-multihop"])
    parser.add_argument("extra", nargs="*", default=[])
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--agent", action="store_true", help="追加 agent 消融行并输出成本列")
    parser.add_argument("--agent-steps", type=int, default=6)
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

    ensure_table()
    if not load_cases():
        print("eval_cases 为空：先 `python -m src.evaluation add \"问题\" \"doc:idx|doc:idx\"`")
        return
    print(f"K={ns.k}" + ("  (+agent)" if ns.agent else ""))
    for row in run_ablation(
        default_eval_configs(include_agent=ns.agent, agent_steps=ns.agent_steps),
        top_k=ns.k,
    ):
        line = f"{row['label']:<28} hit@{ns.k}={row['hit@k']:<8} mrr={row['mrr']}"
        if "avg_steps" in row:
            line += (
                f"  steps={row['avg_steps']:<5} llm={row['avg_llm_calls']:<5}"
                f"  lat_ms={row['avg_latency_ms']}"
            )
        print(line)


if __name__ == "__main__":
    main()
