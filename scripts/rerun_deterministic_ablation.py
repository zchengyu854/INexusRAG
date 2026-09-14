"""确定性消融复测：n=63，分 origin 子集，两轮可复现性检查 + 逐例归因。

背景：instrument 修复（rrf_merge 不再把关键词命中数/图谱跳数分当余弦，
见 _stamp_cosine/_stamp_non_vector）改变了 _relevance_filter 阈值闸门的行为，
§9 的全部测量需要在修复后的仪器上重跑。本脚本就是那次复测的可复现入口。

用法:
  uv run python scripts/rerun_deterministic_ablation.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.evaluation import load_cases, retrieval_metrics  # noqa: E402
from src.retrieval import multi_query_search  # noqa: E402

K = 5
CONFIGS: list[tuple[str, list[str]]] = [
    ("none(纯向量)", []),
    ("routing", ["routing"]),
    ("keywords", ["keywords"]),
    ("routing+keywords", ["routing", "keywords"]),
    ("routing+keywords+rewrite", ["routing", "keywords", "rewrite"]),
]

# 结构化/字面定位线索（与 scripts/analyze_keywords_channel.py 同一判定口径）
from scripts.analyze_keywords_channel import STRUCT_RE, has_struct  # noqa: E402


def run_round(cases: list[dict]) -> dict[int, dict[str, dict]]:
    """逐例逐配置跑一遍，返回 {case_id: {config_label: metrics}}。"""
    out: dict[int, dict[str, dict]] = {}
    for case in cases:
        per: dict[str, dict] = {}
        for label, features in CONFIGS:
            rows = multi_query_search(case["question"], top_k=K, features=features)
            per[label] = retrieval_metrics(rows, case["expected"], K)
        out[case["id"]] = per
        print(f"  #{case['id']:<3} " + "  ".join(
            f"{label}:{'✓' if per[label]['hit'] else '✗'}{per[label]['mrr']:.2f}"
            for label, _ in CONFIGS
        ), flush=True)
    return out


def agg(rows: list[tuple[dict, dict]], label: str) -> str:
    """rows: [(case, per_config_metrics)] → 'hit / mrr'。"""
    n = len(rows) or 1
    hit = sum(per[label]["hit"] for _, per in rows) / n
    mrr = sum(per[label]["mrr"] for _, per in rows) / n
    return f"{hit:.3f} / {mrr:.4f}"


def delta(rows: list[tuple[dict, dict]], lo: str, hi: str) -> float:
    n = len(rows) or 1
    return sum(per[hi]["mrr"] - per[lo]["mrr"] for _, per in rows) / n


def per_case_delta(rows: list[tuple[dict, dict]], lo: str, hi: str) -> list[tuple[dict, float]]:
    return [(case, round(per[hi]["mrr"] - per[lo]["mrr"], 4)) for case, per in rows]


def main() -> None:
    cases = load_cases()
    print(f"评测集 n={len(cases)}（manual={sum(1 for c in cases if c['origin'] == 'manual')}，"
          f"generated={sum(1 for c in cases if c['origin'] == 'generated')}）K={K}")

    rounds = []
    for r in (1, 2):
        print(f"\n--- 第 {r} 轮 ---")
        rounds.append(run_round(cases))

    # 可复现性：两轮逐例逐配置比对
    mismatch = [
        (cid, label)
        for cid in rounds[0]
        for label, _ in CONFIGS
        if rounds[0][cid][label] != rounds[1][cid][label]
    ]
    print(f"\n两轮一致性: {'完全一致' if not mismatch else f'不一致 {mismatch}'}")

    per = rounds[0]
    subsets = {
        "全量 n=63": cases,
        "仅人工 n=8": [c for c in cases if c["origin"] == "manual"],
        "仅自动 n=55": [c for c in cases if c["origin"] == "generated"],
    }
    print("\n=== 确定性消融（复测，每格 hit@5 / MRR）===")
    header = f"{'配置':<26}" + "".join(f"{name:<16}" for name in subsets)
    print(header)
    for label, _ in CONFIGS:
        line = f"{label:<26}"
        for name, sub in subsets.items():
            rows = [(c, per[c["id"]]) for c in sub]
            line += f"{agg(rows, label):<16}"
        print(line)

    kw_rows = [(c, per[c["id"]]) for c in cases]
    rw_rows = kw_rows

    print("\n=== 关键词通道（routing+keywords vs routing）===")
    print(f"ΔMRR: 全量 {delta(kw_rows, 'routing', 'routing+keywords'):+.4f}"
          f"  人工 {delta([x for x in kw_rows if x[0]['origin'] == 'manual'], 'routing', 'routing+keywords'):+.4f}"
          f"  自动 {delta([x for x in kw_rows if x[0]['origin'] == 'generated'], 'routing', 'routing+keywords'):+.4f}")
    for title, lo, hi in (("关键词", "routing", "routing+keywords"), ("改写", "routing+keywords", "routing+keywords+rewrite")):
        deltas = per_case_delta(rw_rows, lo, hi)
        win = [c["id"] for c, d in deltas if d > 0]
        lose = [c["id"] for c, d in deltas if d < 0]
        same = [c["id"] for c, d in deltas if d == 0]
        print(f"\n[{title}] 逐例: 变好 {len(win)} / 变差 {len(lose)} / 不变 {len(same)}")
        print(f"  变好 id: {win}")
        print(f"  变差 id: {lose}")
        struct = [(c, d) for c, d in deltas if has_struct(c["question"])]
        plain = [(c, d) for c, d in deltas if not has_struct(c["question"])]
        print(f"  含结构化线索 n={len(struct)} ΔMRR={sum(d for _, d in struct) / (len(struct) or 1):+.4f}"
              f" | 无 n={len(plain)} ΔMRR={sum(d for _, d in plain) / (len(plain) or 1):+.4f}")

    # 人工子集逐例（报告留一法用）
    print("\n=== 人工子集逐例 ΔMRR ===")
    for case in cases:
        if case["origin"] != "manual":
            continue
        p = per[case["id"]]
        d_kw = round(p["routing+keywords"]["mrr"] - p["routing"]["mrr"], 4)
        d_rw = round(p["routing+keywords+rewrite"]["mrr"] - p["routing+keywords"]["mrr"], 4)
        print(f"  #{case['id']:<3} kw={d_kw:+.4f} rewrite={d_rw:+.4f}  {case['question'][:36]}")


if __name__ == "__main__":
    main()
