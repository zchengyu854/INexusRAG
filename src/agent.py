"""Agentic 检索编排层：ReAct 循环 + 工具集 + 预算守卫 + 静默降级。

用法:
    from src.agent import run_agent
    out = run_agent("问题", top_k=5)     # 返回 None 表示不可用/无证据，调用方退回单轮

与另两条范式的关系（见 docs/agentic-rag-design.md §13）：三范式是同一个循环的特例，
区别只在「步数」与「工具选择」——传统 RAG 是跑 1 步就收敛，Graph RAG 是 1 步但选了图谱工具，
Agentic 是按需跑 N 步。因此这里不需要路由器：每一步的工具选择本身就是路由决策。

设计约束（沿用仓库既有铁律）：
- 依赖单向：本模块只惰性 import retrieval / graph / llm / ingestion，不被它们反向引用。
- 只编排不重造：检索能力全部复用现有函数，本模块只做「query → embedding/terms」的适配。
- 失败静默降级：任一致命错误都返回 None，绝不把异常抛给调用方。
- 硬预算：步数 / LLM 调用数 / 时间三重上限，另有「连续两步无新增证据」的收敛判据。
"""
from __future__ import annotations

from collections.abc import Callable

import time
from typing import Any

# 每步观测回灌给模型的文本长度上限（存摘要而非原文，避免上下文膨胀）
_OBSERVE_CHARS = 120
_SUMMARY_CHARS = 160
_MAX_SUMMARY_ROWS = 6
# 连续几步没有新增证据就判定边际收益为 0，强制收敛
_STAGNANT_LIMIT = 2

_SYSTEM_PROMPT = (
    "你是知识库检索代理。只负责收集足够证据，不要撰写最终答案。\n\n"
    "规则：\n"
    "1. 每步只调用一个工具。\n"
    "2. 证据已经够回答问题时，立刻调用 answer，不要为了完整而反复搜索。\n"
    "3. 若本步没有新证据，必须换角度：改写查询、收窄子问题，或改用图谱。"
    "禁止重复已经用过的 query。\n"
    "4. 多跳问题预期会搜多次，并拼接不同文档里的片段。\n"
    "5. 思考文字要短，使用用户提问的语言。"
)


TOOL_SCHEMAS: dict[str, dict] = {
    "search_knowledge": {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": (
                "Hybrid vector + keyword search over the knowledge base. "
                "Best for factual or descriptive questions. Call it again with reworded "
                "queries to cover different aspects."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query; may be reworded or narrowed"},
                },
                "required": ["query"],
            },
        },
    },
    "search_graph": {
        "type": "function",
        "function": {
            "name": "search_graph",
            "description": (
                "Multi-hop search along the entity-relation graph. Use it when the answer "
                "requires linking clues that live far apart in different documents."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query used to anchor entities"},
                },
                "required": ["query"],
            },
        },
    },
    "answer": {
        "type": "function",
        "function": {
            "name": "answer",
            "description": "Stop searching: the collected evidence is sufficient.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Brief reason for stopping"},
                },
                "required": [],
            },
        },
    },
}


def _tool_search_knowledge(query: str, top_k: int, filters: dict | None) -> list[dict]:
    """主力召回：向量 + 关键词 + 文档路由 + 法条精确通道 + 相关性过滤（复用检索层全部基础装置）。

    与管线模式同一套改写/过滤逻辑：agent 拿到的"no results"是真实的无证据信号，
    会驱动它换角度重查，而不是把噪声当成证据继续推进。
    """
    if not query:
        return []
    from src.ingestion.embedder import get_embedder
    from src.retrieval import (
        _relevance_filter,
        inject_ref_channel,
        rewrite_query,
        search_terms,
        two_stage_search,
    )

    rewritten = rewrite_query(query)
    vector = get_embedder().encode([rewritten])[0]
    rows = two_stage_search(
        vector,
        top_k=top_k,
        terms=search_terms(rewritten),
        filters=filters,
        use_routing=True,
    )
    rows = inject_ref_channel(rewritten, rows, top_k)
    return _relevance_filter(rows, rewritten)


def _tool_search_graph(query: str, top_k: int, filters: dict | None) -> list[dict]:
    """多跳关系召回：实体锚点 → ≤2 跳（复用 graph_channel，跳数由底层写死）。"""
    if not query:
        return []
    from src.graph import graph_channel
    from src.ingestion.embedder import get_embedder

    vector = get_embedder().encode([query])[0]
    return graph_channel(vector, top_k=max(top_k * 5, 25), filters=filters)


# answer 不是真正的检索工具，由 run_agent 直接识别为终止信号，故不在此表
TOOL_IMPL: dict[str, Any] = {
    "search_knowledge": _tool_search_knowledge,
    "search_graph": _tool_search_graph,
}


def _active_tools(features: list[str] | None) -> list[str]:
    """agent 模式下 features 的语义是「允许 Agent 使用的工具子集」。

    P0 约定：None = 全部工具；显式传时 search_knowledge 恒可用，
    search_graph 仅在包含 graph 时挂载。其余 feature 不影响工具可用性。
    """
    if features is None:
        return ["search_knowledge", "search_graph", "answer"]
    tools = ["search_knowledge"]
    if "graph" in set(features):
        tools.append("search_graph")
    tools.append("answer")
    return tools


class Budget:
    """硬预算：LLM 调用数 + 墙钟时间，任一超限即 exhausted。"""

    def __init__(self, max_llm_calls: int, max_seconds: float) -> None:
        self.max_llm_calls = max(1, max_llm_calls)
        self.max_seconds = max_seconds
        self.llm_calls = 0
        self.deadline = time.monotonic() + max_seconds
        self.started = time.monotonic()

    def spend(self) -> None:
        self.llm_calls += 1

    def exhausted(self) -> bool:
        return self.llm_calls >= self.max_llm_calls or time.monotonic() >= self.deadline

    def snapshot(self) -> dict:
        return {
            "max_steps_llm_calls": self.max_llm_calls,
            "max_seconds": self.max_seconds,
            "llm_calls": self.llm_calls,
            "elapsed_ms": round((time.monotonic() - self.started) * 1000, 1),
        }


class EvidenceStore:
    """累积去重证据：按 chunk_id 归并，保留首次出现的行与历史最高分。"""

    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}

    def add(self, rows: list[dict] | None) -> int:
        """并入一批检索结果，返回**新增**块数（用于边际收益判据）。"""
        added = 0
        for row in rows or ():
            key = row.get("chunk_id")
            if not key:
                continue
            if key in self._rows:
                kept = self._rows[key]
                if float(row.get("score") or 0) > float(kept.get("score") or 0):
                    kept["score"] = row["score"]
                continue
            self._rows[key] = dict(row)
            added += 1
        return added

    @property
    def size(self) -> int:
        return len(self._rows)

    def ranked(self, top_k: int) -> list[dict]:
        rows = sorted(self._rows.values(), key=lambda r: float(r.get("score") or 0), reverse=True)
        return rows[:top_k]

    def summary(self) -> str:
        """已收集证据的摘要，回灌给模型用于下一步决策。"""
        rows = self.ranked(_MAX_SUMMARY_ROWS)
        if not rows:
            return ""
        return "\n".join(
            f"- {r.get('doc_name')}#{r.get('chunk_index')}: {_snip(r.get('text'), _SUMMARY_CHARS)}"
            for r in rows
        )


def _snip(text: str | None, chars: int) -> str:
    return " ".join((text or "").split())[:chars]


def _summarize(rows: list[dict]) -> str:
    """单步观测摘要：让模型知道这步拿到了什么（够不够、要不要换角度）。"""
    if not rows:
        return "no results"
    head = " | ".join(
        f"{r.get('doc_name')}#{r.get('chunk_index')}: {_snip(r.get('text'), _OBSERVE_CHARS)}"
        for r in rows[:3]
    )
    return f"{len(rows)} chunks; {head}"


def _messages(question: str, steps: list[dict], evidence: str) -> list[dict]:
    """构造本轮 ReAct 输入：问题 + 已收集证据 + 历史步骤（含观测），实现反思-改写循环。"""
    parts = [f"Question: {question}"]
    if evidence:
        parts.append(f"Evidence collected so far:\n{evidence}")
    else:
        parts.append("Evidence collected so far: none yet.")
    if steps:
        lines = []
        for step in steps:
            line = f"Step {step['step']}: {step['tool']}"
            query = (step.get("args") or {}).get("query")
            if query:
                line += f' query="{query}"'
            if step.get("observation"):
                line += f" -> {step['observation']}"
            if step.get("error"):
                line += f" [failed: {step['error']}]"
            lines.append(line)
        parts.append("Steps taken:\n" + "\n".join(lines))
    parts.append("Choose the next tool.")
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _trace_step(step: int, thought: str | None, tool: str, args: dict) -> dict:
    return {
        "step": step,
        "thought": thought or None,
        "tool": tool,
        "args": dict(args or {}),
        "observation": None,
        "new_chunks": 0,
        "error": None,
        "latency_ms": 0.0,
    }


def _degrade_reason(termination: str, steps: list[dict]) -> str:
    """把「为什么没产出结果」翻译成一句可读原因，供检视面板直接展示。

    此前 run_agent 只返回 None，调用方与界面都无从判断降级原因：同样的提示文案背后
    可能是 LLM 挂了、模型一步就收敛、或检索确实没命中，排查只能靠手工重放。

    注意 termination 为 answered 时有两种截然不同的情况：模型一步就收敛（根本没检索），
    与「检索过但没命中」。因此要看实际步骤里有没有检索动作，不能只看终止原因。
    """
    if termination == "error":
        last_error = (steps[-1].get("args") or {}).get("error") if steps else None
        return f"Agent 调用大模型失败：{last_error}" if last_error else "Agent 调用大模型失败"
    searches = [step for step in steps if step.get("tool") not in (None, "answer")]
    if not searches:
        return "大模型一步即收敛，未收集到任何证据"
    failures = [step["error"] for step in searches if step.get("error")]
    if failures and len(failures) == len(searches):
        return f"检索工具全部失败：{failures[0]}"
    if failures:
        return f"部分检索失败且未命中证据：{failures[0]}"
    return "检索未命中任何证据（知识库可能缺少相关内容）"


def run_agent(
    question: str,
    top_k: int = 5,
    filters: dict | None = None,
    max_steps: int = 6,
    features: list[str] | None = None,
    max_llm_calls: int | None = None,
    max_seconds: float = 45.0,
    rerank_strategy: str | None = None,
    on_step: Callable[[dict], None] | None = None,
    degrade: dict | None = None,
) -> dict | None:
    """Agentic 检索：自主多轮，最多 max_steps 步。

    返回 {"results": [...], "trace": {...}}；**任一致命失败或无证据一律返回 None**，
    由调用方退回 multi_query_search。不在此处生成回答——生成统一由 routes 负责，
    这样 [Source N] 引用、figures、落库、history 处理只有一份逻辑。

    degrade 为可选出参：返回 None 时写入 {"reason": "..."}，说明降级原因（界面据此
    给出具体提示，而不是"常见原因有几种"）。与 retrieval.two_stage_search 的 stats
    出参同一套路，不传时行为与改动前完全一致。

    rerank：features 显式包含 "rerank" 时，对整个循环累积的证据池做一次终排
    （只在收尾排一次，不是每步都排，避免重排开销乘以步数）。features=None 保持
    旧行为不重排——与管线模式 None=默认集（无 rerank）的语义一致。

    trace 结构：{"steps": [...], "termination": ..., "budget": {...}, "evidence_chunks": int}
    termination: answered | budget | max_steps | stagnant | error
    """
    from src.llm.client import get_llm

    llm = get_llm()
    if not llm.enabled:
        if degrade is not None:
            degrade["reason"] = "LLM 未配置：缺少可用的 API Key 或 provider"
        return None

    tool_names = _active_tools(features)
    schemas = [TOOL_SCHEMAS[name] for name in tool_names]
    # 只暴露本次允许的检索工具：模型若选了未挂载的工具，按终止处理，绝不越权执行
    impl = {name: TOOL_IMPL[name] for name in tool_names if name in TOOL_IMPL}
    budget = Budget(max_llm_calls or max_steps, max_seconds)
    scratch = EvidenceStore()
    steps: list[dict] = []
    termination = "max_steps"
    stagnant = 0

    for step in range(1, max_steps + 1):
        if budget.exhausted():
            termination = "budget"
            break
        try:
            budget.spend()
            action = llm.chat_with_tools(_messages(question, steps, scratch.summary()), schemas)
        except Exception as exc:
            # LLM 中途挂掉：不整体失败，用已收集的证据收敛
            record = _trace_step(step, None, "answer", {"error": str(exc)})
            steps.append(record)
            if on_step is not None:
                on_step(record)
            termination = "error"
            break

        name = action.get("tool") or "answer"
        args = action.get("args") or {}
        record = _trace_step(step, action.get("thought"), name, args)

        if name == "answer" or name not in impl:
            steps.append(record)
            if on_step is not None:
                on_step(record)
            termination = "answered"
            break

        started = time.perf_counter()
        try:
            rows = impl[name](query=args.get("query", ""), top_k=top_k, filters=filters)
        except Exception as exc:
            # 工具失败不致命：记一步 error，让模型下一步换工具或换角度
            record["error"] = str(exc)
            record["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
            steps.append(record)
            if on_step is not None:
                on_step(record)
            continue

        new_chunks = scratch.add(rows)
        record["new_chunks"] = new_chunks
        record["observation"] = _summarize(rows)
        record["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        steps.append(record)
        if on_step is not None:
            on_step(record)

        # 边际收益为 0：连续两步没拿到新证据，强制收敛，避免模型空转烧预算
        stagnant = stagnant + 1 if new_chunks == 0 else 0
        if stagnant >= _STAGNANT_LIMIT:
            termination = "stagnant"
            break

    results = scratch.ranked(top_k)
    rerank_used = False
    effective_strategy: str | None = None
    if features is not None and "rerank" in set(features) and scratch.size > 0:
        import os

        from src.rerank import rerank as _rerank

        effective_strategy = (rerank_strategy or os.getenv("RERANK_STRATEGY", "rrf")).lower()
        try:
            candidates = scratch.ranked(max(top_k * 5, 25))
            results = _rerank(question, candidates, top_k, strategy=effective_strategy)
            rerank_used = True
        except Exception:
            # 重排失败不致命：退回 RRF 序，agent 整体仍静默降级
            results = scratch.ranked(top_k)
    if not results:
        if degrade is not None:
            degrade["reason"] = _degrade_reason(termination, steps)
        return None
    return {
        "results": results,
        "trace": {
            "steps": steps,
            "termination": termination,
            "budget": budget.snapshot(),
            "evidence_chunks": scratch.size,
            "tools": tool_names,
            "rerank": effective_strategy if rerank_used else None,
        },
    }
