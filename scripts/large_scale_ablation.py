"""大规模确定性消融：评测集扩容后复测全部通道结论，并**单独量化门控本身的贡献**。

与 rerun_deterministic_ablation.py 的区别：
1. 不写死样本量，子集标签按实际条数生成（`--origin` 语义）；
2. 新增「关键词(裸)」配置——用 monkeypatch 把 `_gate_keyword_rows` 还原为恒等函数，
   从而把「门控带来的增量」和「关键词通道本身的增量」分开测量（此前只能比门控前后两次运行）；
3. 输出逐例胜负、结构化切分、以及两轮一致性校验。

用法:
  uv run python scripts/large_scale_ablation.py                 # 全量 + 两轮
  uv run python scripts/large_scale_ablation.py --rounds 1      # 只跑一轮（省时间）
  uv run python scripts/large_scale_ablation.py --origin manual # 只看人工子集
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.evaluation import load_cases, retrieval_metrics  # noqa: E402
from src.retrieval import multi_query_search  # noqa: E402
from scripts.analyze_keywords_channel import has_struct  # noqa: E402

K = 5

# (标签, features, 是否绕过门控)
CONFIGS: list[tuple[str, list[str], bool]] = [
    ("none(纯向量)", [], False),
    ("keywords(门控)", ["routing", "keywords"], False),
    ("keywords(裸)", ["routing", "keywords"], True),
    ("+rewrite", ["routing", "keywords", "rewrite"], False),
]


def _metrics_for(case: dict, features: list[str], ungated: bool) -> dict:
    if ungated:
        with patch("src.retrieval._gate_keyword_rows", lambda rows, terms: rows):
            rows = multi_query_search(case["question"], top_k=K, features=features)
    else:
        rows = multi_query_search(case["question"], top_k=K, features=features)
    return retrieval_metrics(rows, case["expected"], K)


def run_round(cases: list[dict], verbose: bool = True) -> dict[int, dict[str, dict]]:
    out: dict[int, dict[str, dict]] = {}
    for i, case in enumerate(cases, 1):
        per = {label: _metrics_for(case, feats, un) for label, feats, un in CONFIGS}
        out[case["id"]] = per
        if verbose and (i % 25 == 0 or i == len(cases)):
            print(f"  {i}/{len(cases)}", flush=True)
    return out


def _agg(cases: list[dict], per: dict, label: str) -> tuple[float, float]:
    n = len(cases) or 1
    return (
        sum(per[c["id"]][label]["hit"] for c in cases) / n,
        sum(per[c["id"]][label]["mrr"] for c in cases) / n,
    )


def _delta(cases: list[dict], per: dict, lo: str, hi: str) -> float:
    n = len(cases) or 1
    return sum(per[c["id"]][hi]["mrr"] - per[c["id"]][lo]["mrr"] for c in cases) / n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--origin", choices=["all", "manual", "generated"], default="all")
    ns = ap.parse_args()

    cases = load_cases(origin=None if ns.origin == "all" else ns.origin)
    n_manual = sum(1 for c in cases if c["origin"] == "manual")
    print(f"评测集 n={len(cases)}（manual={n_manual}，generated={len(cases) - n_manual}）K={K}")
    print(f"分辨率：1 例 = {1 / (len(cases) or 1):.4f} hit@5\n")

    rounds = []
    for r in range(1, ns.rounds + 1):
        print(f"--- 第 {r} 轮 ---")
        rounds.append(run_round(cases))

    if len(rounds) > 1:
        mismatch = [(cid, lab) for cid in rounds[0] for lab, _f, _u in CONFIGS
                    if rounds[0][cid][lab] != rounds[1][cid][lab]]
        print(f"\n两轮一致性: {'完全一致' if not mismatch else f'不一致 {len(mismatch)} 处'}\n")

    per = rounds[0]
    subsets = {"全量": cases}
    if n_manual:
        subsets["仅人工"] = [c for c in cases if c["origin"] == "manual"]
    gen = [c for c in cases if c["origin"] == "generated"]
    if gen:
        subsets["仅自动"] = gen

    print("=== 消融矩阵（每格 hit@5 / MRR） ===")
    print(f"{'配置':<18}" + "".join(f"{name + f'(n={len(sub)})':<20}" for name, sub in subsets.items()))
    for label, _f, _u in CONFIGS:
        line = f"{label:<18}"
        for _name, sub in subsets.items():
            hit, mrr = _agg(sub, per, label)
            line += f"{hit:.3f} / {mrr:.4f}      "
        print(line)

    print("\n=== 通道增量（ΔMRR） ===")
    for name, sub in subsets.items():
        d_kw_gated = _delta(sub, per, "none(纯向量)", "keywords(门控)")
        d_kw_bare = _delta(sub, per, "none(纯向量)", "keywords(裸)")
        d_gate = _delta(sub, per, "keywords(裸)", "keywords(门控)")
        d_rw = _delta(sub, per, "keywords(门控)", "+rewrite")
        print(f"  {name:<10} 关键词(裸) {d_kw_bare:+.4f} | 门控增益 {d_gate:+.4f} | "
              f"关键词(门控)合计 {d_kw_gated:+.4f} | 改写 {d_rw:+.4f}")

    print("\n=== 逐例胜负（门控后 vs 纯向量 / 门控 vs 裸通道） ===")
    for title, lo, hi in (("关键词(门控) vs 纯向量", "none(纯向量)", "keywords(门控)"),
                          ("门控 vs 裸关键词", "keywords(裸)", "keywords(门控)")):
        deltas = [(c, round(per[c["id"]][hi]["mrr"] - per[c["id"]][lo]["mrr"], 4))
                  for c in cases]
        win = [c["id"] for c, d in deltas if d > 0]
        lose = [c["id"] for c, d in deltas if d < 0]
        same = [c["id"] for c, d in deltas if d == 0]
        print(f"  [{title}] 变好 {len(win)} / 变差 {len(lose)} / 不变 {len(same)}")
        if lose:
            print(f"    变差 id（前 20）: {lose[:20]}")

    print("\n=== 结构化线索切分（关键词门控 vs 纯向量） ===")
    for title, pred in (("含结构化线索", has_struct), ("无结构化线索", lambda q: not has_struct(q))):
        sub = [c for c in cases if pred(c["question"])]
        if not sub:
            continue
        print(f"  {title:<12} n={len(sub):<4} ΔMRR={_delta(sub, per, 'none(纯向量)', 'keywords(门控)'):+.4f}"
              f"   （裸通道 {_delta(sub, per, 'none(纯向量)', 'keywords(裸)'):+.4f}）")


if __name__ == "__main__":
    main()
