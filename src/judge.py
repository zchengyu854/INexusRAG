"""答案级评测：LLM 判官（忠实度 / 正确性）+ 结果落库。

检索级指标（Hit@K/MRR）只能说明「资料找没找到」，说明不了「回答有没有胡说」。
这里补答案级指标，其中**忠实度直接量化幻觉**：把答案拆成原子论断，逐条判定能否被
检索到的来源支撑，得分 = 被支撑的论断数 / 总论断数。

两个刻意的设计：
1. 判官走结构化输出（复用 llm.tool_call 的 function calling），不解析自由文本——
   让模型直接返回 claims 数组，比"输出 JSON 文本再正则"稳得多。
2. 结果连未支撑的论断原文一起落库：判官本身是有噪声的，保留明细才能事后复核，
   也才能用人工标注去校准它（一致性低于阈值时它的分数就不该被当成结论）。
"""
from __future__ import annotations

from typing import Any

from src.storage.database import connection

# 判官输出里最多保留的未支撑论断数（避免长答案把结果表撑爆）
_MAX_UNSUPPORTED_KEPT = 10

_TABLE = """
CREATE TABLE IF NOT EXISTS eval_answer_results (
    id SERIAL PRIMARY KEY,
    run_label TEXT NOT NULL,
    case_id INTEGER NOT NULL,
    config TEXT NOT NULL,
    faithfulness REAL,
    correctness REAL,
    claim_count INTEGER,
    unsupported_count INTEGER,
    unsupported_claims TEXT,
    answer TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

_FAITHFULNESS_TOOL: dict = {
    "name": "judge_faithfulness",
    "description": "把答案拆成原子论断，逐条判定能否由给定来源支撑",
    "parameters": {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "description": "答案里的原子论断（一句话一个，不要合并）",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string", "description": "论断原文"},
                        "supported": {
                            "type": "boolean",
                            "description": "该论断能否由给定来源支撑（来源未提及即 false）",
                        },
                        "reason": {"type": "string", "description": "判定依据，简短"},
                    },
                    "required": ["claim", "supported"],
                },
            }
        },
        "required": ["claims"],
    },
}

_CORRECTNESS_TOOL: dict = {
    "name": "judge_correctness",
    "description": "把答案与参考答案对比后判分",
    "parameters": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "description": "consistent（一致）| partial（部分一致）| contradictory（矛盾）| irrelevant（无关）",
            },
            "score": {"type": "number", "description": "0~1，1 表示与参考答案一致，0 表示无关或矛盾"},
            "reason": {"type": "string", "description": "判定依据，简短"},
        },
        "required": ["verdict", "score"],
    },
}


def ensure_table() -> None:
    with connection() as conn:
        conn.execute(_TABLE)


def score_faithfulness(claims: list[dict] | None) -> dict:
    """纯函数：论断列表 → 忠实度得分与未支撑明细。

    没有任何论断时得分为 None（无法判定），而不是 0 或 1——把「判不了」和
    「全都不支撑」区分开，否则空答案会被误判成完美或不忠实。
    """
    rows = [c for c in (claims or []) if isinstance(c, dict) and c.get("claim")]
    total = len(rows)
    unsupported = [str(c["claim"]) for c in rows if not c.get("supported")]
    return {
        "score": round((total - len(unsupported)) / total, 4) if total else None,
        "claim_count": total,
        "unsupported_count": len(unsupported),
        "unsupported_claims": unsupported[:_MAX_UNSUPPORTED_KEPT],
    }


def _format_sources(sources: list[dict]) -> str:
    return "\n\n".join(
        f"[Source {i + 1}] {s.get('doc_name')} / chunk {s.get('chunk_index')}\n{(s.get('text') or '')[:1200]}"
        for i, s in enumerate(sources or [])
    )


def judge_faithfulness(
    question: str,
    answer: str,
    sources: list[dict],
    llm: Any | None = None,
) -> dict | None:
    """判定答案是否忠于检索来源；判官不可用/输出异常时返回 None（不拖垮整个评测）。"""
    if not answer.strip():
        return None
    llm = llm or _default_llm()
    if llm is None or not getattr(llm, "enabled", False):
        return None
    prompt = (
        "你在评测一个检索问答系统的输出。请把下面的【回答】拆成原子论断，"
        "并逐条判定该论断能否由【来源】支撑。来源里没有提到的内容一律判为不支持；"
        "不要用你自己的先验知识去补全。\n"
        "只提取「关于知识库内容的事实性陈述」作为论断：向用户的澄清提问、"
        "对自身局限的说明（如「无法确定」「资料里没有」）、以及格式性文字都不要算作论断——"
        "它们不是对知识库的断言，算进来会冤枉扣分。\n\n"
        f"【问题】\n{question}\n\n"
        f"【来源】\n{_format_sources(sources) or '(无来源)'}\n\n"
        f"【回答】\n{answer}"
    )
    try:
        data = llm.tool_call(prompt, _FAITHFULNESS_TOOL)
    except Exception:
        return None
    result = score_faithfulness(data.get("claims"))
    result["claims"] = data.get("claims") or []
    return result


def judge_correctness(
    question: str,
    answer: str,
    reference_answer: str | None,
    llm: Any | None = None,
) -> dict | None:
    """与参考答案比对判分；缺参考答案时返回 None。"""
    if not reference_answer or not answer.strip():
        return None
    llm = llm or _default_llm()
    if llm is None or not getattr(llm, "enabled", False):
        return None
    prompt = (
        "你在评测一个检索问答系统的输出。请对比【参考答案】给【回答】判分：\n"
        "- consistent：关键事实一致（措辞不同不影响）\n"
        "- partial：部分正确，但有遗漏或含未提及的额外内容\n"
        "- contradictory：与参考答案冲突\n"
        "- irrelevant：没有回答该问题\n"
        "score 取 0~1，关键事实（数字、名称）错误要显著扣分。\n\n"
        f"【问题】\n{question}\n\n"
        f"【参考答案】\n{reference_answer}\n\n"
        f"【回答】\n{answer}"
    )
    try:
        data = llm.tool_call(prompt, _CORRECTNESS_TOOL)
    except Exception:
        return None
    try:
        score = float(data.get("score"))
    except (TypeError, ValueError):
        return None
    return {
        "score": max(0.0, min(1.0, round(score, 4))),
        "verdict": str(data.get("verdict") or ""),
        "reason": str(data.get("reason") or ""),
    }


def _default_llm() -> Any | None:
    try:
        from src.llm.client import get_llm

        return get_llm()
    except Exception:
        return None


def generate_answer(
    question: str,
    top_k: int = 5,
    features: list[str] | None = None,
    mode: str = "pipeline",
    max_steps: int = 6,
    llm: Any | None = None,
) -> dict:
    """跑完整问答链路（检索 + 生成），返回 {answer, sources}。

    答案级评测必须评「端到端输出」，所以这里复现的是 /api/query 的核心两步，
    不引入 routes 层（避免评测脚本依赖 HTTP 与 FastAPI）。
    """
    from src.retrieval import multi_query_search

    llm = llm or _default_llm()
    sources: list[dict] = []
    if mode == "agent":
        try:
            from src.agent import run_agent

            out = run_agent(question, top_k=top_k, features=features, max_steps=max_steps)
            if out is not None:
                sources = out["results"]
        except Exception:
            sources = []
    if not sources:
        sources = multi_query_search(question, top_k=top_k, features=features)
    if not sources:
        return {"answer": "未检索到相关内容。", "sources": []}
    answer = llm.generate(question, sources) if llm is not None else ""
    return {"answer": answer, "sources": sources}


def save_result(
    run_label: str,
    case_id: int,
    config: str,
    faithfulness: dict | None,
    correctness: dict | None,
    answer: str,
) -> None:
    ensure_table()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO eval_answer_results
                (run_label, case_id, config, faithfulness, correctness,
                 claim_count, unsupported_count, unsupported_claims, answer)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                run_label,
                case_id,
                config,
                (faithfulness or {}).get("score"),
                (correctness or {}).get("score"),
                (faithfulness or {}).get("claim_count"),
                (faithfulness or {}).get("unsupported_count"),
                " | ".join((faithfulness or {}).get("unsupported_claims") or []) or None,
                answer[:4000],
            ],
        )


def load_results(run_label: str | None = None) -> list[dict]:
    ensure_table()
    with connection() as conn:
        if run_label:
            return list(conn.execute(
                "SELECT * FROM eval_answer_results WHERE run_label = %s ORDER BY config, case_id",
                [run_label],
            ))
        return list(conn.execute("SELECT * FROM eval_answer_results ORDER BY id"))
