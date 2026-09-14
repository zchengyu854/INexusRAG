"""构建评测集：从现有语料采样片段，用 LLM 按片段出题，落库为标注用例。

用法：
    uv run python scripts/build_eval_set.py --dry-run            # 只看采样与生成结果，不写库
    uv run python scripts/build_eval_set.py --count 50           # 写入 50 条单片段用例
    uv run python scripts/build_eval_set.py --count 40 --multihop 8

设计见 src/eval_builder.py 顶部说明；要点是 ground truth 就是题目来源的切片，
因此不需要人工写期望引用，人工只需事后筛掉质量差的题。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.eval_builder import generate_case, generate_multihop_case, sample_chunks
from src.evaluation import add_case, ensure_table, load_cases
from src.llm.client import get_llm
from src.storage.database import connection


def _load_chunks() -> list[dict]:
    """只取未删除文档的切片；带上 doc_name 与下标，便于生成 expected_refs。"""
    with connection() as conn:
        return list(conn.execute(
            """
            SELECT c.doc_name, c.chunk_index, c.text
              FROM chunks c
              JOIN documents d ON d.id = c.document_id
             WHERE d.deleted_at IS NULL
             ORDER BY c.doc_name, c.chunk_index
            """
        ))


def _existing_refs(cases: list[dict]) -> set[str]:
    refs: set[str] = set()
    for case in cases:
        refs.update(case["expected"])
    return refs


def main() -> None:
    parser = argparse.ArgumentParser(description="从语料自动构建评测集")
    parser.add_argument("--count", type=int, default=50, help="单片段用例数量")
    parser.add_argument("--multihop", type=int, default=6, help="跨片段用例数量")
    parser.add_argument("--per-doc-cap", type=int, default=None, help="每篇文档最多取多少个片段")
    parser.add_argument("--seed", type=int, default=20260914)
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写库")
    ns = parser.parse_args()

    ensure_table()
    llm = get_llm()
    if not llm.enabled:
        print("LLM 不可用：本脚本需要模型根据片段出题，请先配置 provider")
        return

    chunks = _load_chunks()
    existing = _existing_refs(load_cases())
    print(f"候选切片 {len(chunks)} 块；已有用例引用 {len(existing)} 处")

    single_rows = sample_chunks(
        chunks, ns.count, used_refs=existing, per_doc_cap=ns.per_doc_cap, seed=ns.seed
    )
    print(f"采样出 {len(single_rows)} 块用于单片段出题\n")

    created: list[dict] = []
    skipped = 0
    for row in single_rows:
        try:
            case = generate_case(row, llm)
        except Exception as exc:
            print(f"  [{row['doc_name']}:{row['chunk_index']}] 生成失败：{type(exc).__name__}")
            skipped += 1
            continue
        if case is None:
            skipped += 1
            continue
        created.append(case)
        print(f"  ✓ {case['expected_refs']}  {case['question'][:56]}", flush=True)

    # 跨片段用例：同一文档内相距 ≥50 块的两处，逼出「多跳整合」
    if ns.multihop > 0:
        by_doc: dict[str, list[dict]] = {}
        for row in chunks:
            by_doc.setdefault(row["doc_name"], []).append(row)
        pairs: list[list[dict]] = []
        for bucket in by_doc.values():
            ordered = sorted(bucket, key=lambda r: r["chunk_index"])
            for i in range(0, len(ordered) - 1, max(1, len(ordered) // 3)):
                for j in range(i + 1, len(ordered)):
                    if ordered[j]["chunk_index"] - ordered[i]["chunk_index"] >= 50:
                        pairs.append([ordered[i], ordered[j]])
                        break
        pairs = pairs[: ns.multihop]
        print(f"\n跨片段出题 {len(pairs)} 组")
        for pair in pairs:
            try:
                case = generate_multihop_case(pair, llm)
            except Exception as exc:
                print(f"  跨片段生成失败：{type(exc).__name__}")
                skipped += 1
                continue
            if case is None:
                skipped += 1
                continue
            created.append(case)
            print(f"  ✓ {case['expected_refs']}  {case['question'][:56]}", flush=True)

    print()
    if ns.dry_run:
        print(f"（dry-run）将写入 {len(created)} 条，跳过 {skipped} 条")
        return

    for case in created:
        add_case(case["question"], case["expected_refs"], case["reference_answer"], origin=case["origin"])
    total = len(load_cases())
    print(f"已写入 {len(created)} 条（跳过 {skipped} 条）；评测集现有 {total} 条")


if __name__ == "__main__":
    main()
