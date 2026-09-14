"""关键词通道的逐例影响分析。

背景：全量 n=63 上关键词通道整体是负向的（ΔMRR −0.117），但在人工 8 例上是正向的。
本报告假设「关键词只应在查询含结构化/字面定位线索时启用」，本脚本用来验证：
按查询是否含结构化线索切分，分别统计关键词通道的开/关差异，并给出逐例 ΔMRR 分布。

用法:
  uv run python scripts/analyze_keywords_channel.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.evaluation as ev  # noqa: E402

K = 5
BASE = ["routing"]  # 路由实测为零影响，等价于纯向量
KW = ["routing", "keywords"]

# 结构化 / 字面定位线索：页码、法条号、图表编号、网址、代码与代号
STRUCT_PATTERNS = [
    r"第[0-9一二三四五六七八九十百千零]+[页条章节款项]",
    r"[0-9]+\s*页",
    r"(table|figure|fig)\.?\s*[0-9]+",
    r"https?://",
    r"\b[\w-]+\.(?:com|org|net|cn|io)\b",
    r"arXiv:",
    r"\b[A-Za-z][A-Za-z0-9]*-[A-Za-z0-9]+\b",
    r"\bIndex\s*[0-9]",
    r"`[^`]+`",
]
STRUCT_RE = re.compile("|".join(STRUCT_PATTERNS), re.IGNORECASE)


def has_struct(question: str) -> bool:
    return bool(STRUCT_RE.search(question))


def aggregate(rows: list[dict], title: str) -> None:
    n = len(rows) or 1
    print(f"\n=== {title} (n={len(rows)}) ===")
    print(f"  {'配置':<12}{'hit@5':<10}{'MRR'}")
    for label, key in (("vector", "base"), ("+keywords", "kw")):
        hit = sum(r[key]["hit"] for r in rows) / n
        mrr = sum(r[key]["mrr"] for r in rows) / n
        print(f"  {label:<12}{hit:<10.3f}{mrr:.4f}")
    print(f"  ΔMRR = {sum(r['d_mrr'] for r in rows) / n:+.4f}")


def main() -> None:
    cases = ev.load_cases()
    per: list[dict] = []
    for case in cases:
        base = ev.retrieval_metrics(ev.pipeline_runner(case["question"], K, BASE), case["expected"], K)
        kw = ev.retrieval_metrics(ev.pipeline_runner(case["question"], K, KW), case["expected"], K)
        per.append({
            **case,
            "base": base,
            "kw": kw,
            "d_mrr": round(kw["mrr"] - base["mrr"], 4),
            "d_hit": int(kw["hit"]) - int(base["hit"]),
        })

    aggregate([r for r in per if has_struct(r["question"])], "含结构化线索")
    aggregate([r for r in per if not has_struct(r["question"])], "无结构化线索")

    win = [r for r in per if r["d_mrr"] > 0]
    lose = [r for r in per if r["d_mrr"] < 0]
    same = [r for r in per if r["d_mrr"] == 0]
    print(f"\n=== 逐例 ΔMRR 分布 (n={len(per)}) ===")
    print(f"  变好 {len(win)}　变差 {len(lose)}　不变 {len(same)}")
    print(f"  变好 id: {[r['id'] for r in win]}")
    print(f"  变差 id: {[r['id'] for r in lose]}")

    print(f"\n=== 关键词通道拖累最重的 10 例 (K={K}) ===")
    for r in sorted(per, key=lambda x: x["d_mrr"])[:10]:
        flag = "命中→未命中" if r["d_hit"] < 0 else ("未命中→命中" if r["d_hit"] > 0 else "")
        print(f"  #{r['id']:<3} ΔMRR={r['d_mrr']:+.4f}  {flag:<12} {r['question'][:40]}")

    print("\n=== 关键词通道改善的例 ===")
    for r in sorted(win, key=lambda x: -x["d_mrr"]):
        flag = "未命中→命中" if r["d_hit"] > 0 else ""
        print(f"  #{r['id']:<3} ΔMRR={r['d_mrr']:+.4f}  {flag:<12} {r['question'][:40]}")


if __name__ == "__main__":
    main()
