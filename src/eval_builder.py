"""评测集自动构建：从现有语料采样片段 → 让 LLM 据片段出题 → 落成标注用例。

为什么需要它：8 条人工用例的分辨率是「1 例翻转 = 0.125 hit@5」，任何小于 0.1 的差异
都不可判读（详见 docs/eval-report-2026-09-14.md）。要判断某个开关有没有用，评测集
至少需要几十条量级。

做法与取舍：
- **答案有据可查**：每道题的 ground truth 就是它来源的切片，不需要人写期望引用。
- **中文提问**：语料中英混杂，但用户提问是中文，评测集按真实用法出题（跨语种检索本身就是考点）。
- **过滤残片**：目录、纯标题、过短片段不适合出题，采样阶段先过滤；生成阶段再让模型
  用 `suitable=false` 兜一次（双重保险）。
- **不泄露答案**：提示词明确要求问题不得照抄片段句子，且不得出现"根据上文"这类指代。
- **来源可区分**：落库时标 `origin='generated'`，人工用例仍是 `manual`，便于只统计人工子集。
"""
from __future__ import annotations

import random
import re
from typing import Any, Callable

# 目录页特征：点线引导符 / 「目录」「Contents」独占行
_TOC = re.compile(r"(\.{4,}|…{3,})|^\s*(目\s*录|contents|table of contents)\s*$", re.IGNORECASE | re.MULTILINE)

GEN_TOOL: dict = {
    "name": "make_question",
    "description": "根据给定片段生成一道「必须依靠该片段才能回答」的问题，并写出参考答案",
    "parameters": {
        "type": "object",
        "properties": {
            "suitable": {
                "type": "boolean",
                "description": "该片段是否适合出题；若是目录、残缺句、纯符号/表格线，填 false",
            },
            "question": {
                "type": "string",
                "description": "中文提问。要具体到关键实体；不得照抄片段中的整句，"
                "不得出现「根据上文」「这段文字」这类指代",
            },
            "reference_answer": {
                "type": "string",
                "description": "仅依据该片段写出的简短参考答案（1~3 句）",
            },
        },
        "required": ["suitable"],
    },
}

MULTIHOP_TOOL: dict = {
    "name": "make_multihop_question",
    "description": "根据两个不同片段生成一道需要同时用到两者才能回答的问题",
    "parameters": {
        "type": "object",
        "properties": {
            "suitable": {"type": "boolean", "description": "两个片段是否适合出一道跨片段问题"},
            "question": {
                "type": "string",
                "description": "中文提问，答案必须同时依赖两个片段（比如对比、求和、因果串联）",
            },
            "reference_answer": {"type": "string", "description": "依据两个片段写出的简短参考答案"},
        },
        "required": ["suitable"],
    },
}

_TOOL = GEN_TOOL
_MULTIHOP_TOOL = MULTIHOP_TOOL


def is_suitable_chunk(text: str, min_chars: int = 120, max_chars: int = 3000) -> bool:
    """采样前的机械过滤：太短（标题/残句）、太长、目录页都不适合出题。"""
    body = (text or "").strip()
    if len(body) < min_chars or len(body) > max_chars:
        return False
    if _TOC.search(body):
        return False
    return True


def build_ref(doc_name: str, chunk_index: int) -> str:
    return f"{doc_name}:{chunk_index}"


def sample_chunks(
    rows: list[dict],
    count: int,
    used_refs: set[str] | None = None,
    per_doc_cap: int | None = None,
    seed: int = 20260914,
    text_getter: Callable[[dict], str] = lambda row: row.get("text", ""),
) -> list[dict]:
    """按文档分层采样切片，避免大文档（如法条 1064 块）挤占全部名额。

    rows 形态：[{"doc_name": ..., "chunk_index": ..., "text": ...}]
    """
    used = used_refs or set()
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        ref = build_ref(row["doc_name"], row["chunk_index"])
        if ref in used or not is_suitable_chunk(text_getter(row)):
            continue
        grouped.setdefault(row["doc_name"], []).append(row)

    rng = random.Random(seed)
    for bucket in grouped.values():
        rng.shuffle(bucket)

    cap = per_doc_cap if per_doc_cap is not None else max(1, -(-count // max(1, len(grouped))) + 2)
    picked: list[dict] = []
    # 轮转取，保证各文档均衡，而不是先取满一篇再下一篇
    round_index = 0
    while len(picked) < count:
        progressed = False
        for doc_name, bucket in grouped.items():
            if round_index >= min(cap, len(bucket)):
                continue
            picked.append(bucket[round_index])
            progressed = True
            if len(picked) >= count:
                break
        if not progressed:
            break
        round_index += 1
    return picked


def _format_snippet(row: dict) -> str:
    return f"[{build_ref(row['doc_name'], row['chunk_index'])}]\n{row.get('text', '')[:1800]}"


def generate_case(
    row: dict,
    llm: Any,
    question_tool: dict | None = None,
) -> dict | None:
    """单片段出题。模型判定不适合或输出残缺时返回 None。"""
    tool = question_tool or _TOOL
    prompt = (
        "你在为一个检索问答系统构建评测集。请根据下面的知识库片段出一道题：\n"
        "- 题目必须**只能**依靠该片段回答；\n"
        "- 用中文提问，指向尽可能具体（包含关键实体/数字/名称）；\n"
        "- 不要把片段里的句子原样搬进问题，否则等于泄露答案；\n"
        "- 不要出现「根据上文」「这段文字」这类指代。\n\n"
        f"【片段】\n{_format_snippet(row)}"
    )
    data = llm.tool_call(prompt, tool)
    if not data.get("suitable"):
        return None
    question = str(data.get("question") or "").strip()
    if len(question) < 6:
        return None
    return {
        "question": question,
        "expected_refs": build_ref(row["doc_name"], row["chunk_index"]),
        "reference_answer": str(data.get("reference_answer") or "").strip() or None,
        "origin": "generated",
    }


def generate_multihop_case(rows: list[dict], llm: Any) -> dict | None:
    """跨片段出题：要求答案同时依赖两个片段。"""
    if len(rows) < 2:
        return None
    prompt = (
        "你在为一个检索问答系统构建评测集。下面是**同一文档中相距较远**的两个片段，"
        "请出一道必须同时用到这两个片段才能完整回答的问题（例如对比、串联因果、汇总两处结论）。\n"
        "- 用中文提问，不要照抄原文句子，不要出现「根据上文」这类指代。\n\n"
        + "\n\n".join(f"【片段 {i + 1}】\n{_format_snippet(row)}" for i, row in enumerate(rows[:2]))
    )
    data = llm.tool_call(prompt, _MULTIHOP_TOOL)
    if not data.get("suitable"):
        return None
    question = str(data.get("question") or "").strip()
    if len(question) < 6:
        return None
    return {
        "question": question,
        "expected_refs": "|".join(build_ref(row["doc_name"], row["chunk_index"]) for row in rows[:2]),
        "reference_answer": str(data.get("reference_answer") or "").strip() or None,
        "origin": "generated",
    }
