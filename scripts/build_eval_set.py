"""构建评测集：从现有语料采样片段，用 LLM 按片段出题，落库为标注用例。

用法：
    uv run python scripts/build_eval_set.py --dry-run            # 只看采样与生成结果，不写库
    uv run python scripts/build_eval_set.py --count 50           # 写入 50 条单片段用例
    uv run python scripts/build_eval_set.py --count 300 --multihop 30 --workers 6

设计见 src/eval_builder.py 顶部说明；要点是 ground truth 就是题目来源的切片，
因此不需要人工写期望引用，人工只需事后筛掉质量差的题。

并发与落库（2026-09-15 改进）：
- 出题是**一次一条 LLM 调用**，串行跑 300 条约需 4 小时（实测 43s/条，中转链路慢）。
  加 --workers 后并发出题（openai SDK 底层 httpx 线程安全），实测 6 并发可压到 ~20 分钟。
- 改为**边生成边落库**：中断不再丢已完成的题（原实现全部攒在内存里，最后统一写）。
- 写库仍在主线程串行执行（future 完成后写），避免并发 INSERT 打满连接池。
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def _gen_one(row: dict, llm, multi: bool):
    """出题并吞掉异常，返回 (row, case|None, err|None)。供并发调用。"""
    try:
        case = generate_multihop_case([row["a"], row["b"]], llm) if multi else generate_case(row, llm)
        return row, case, None
    except Exception as exc:  # 单条失败不该中断整批
        return row, None, f"{type(exc).__name__}"


def _generate_batch(rows: list[dict], llm, ns, *, multi: bool = False) -> tuple[int, int, int]:
    """并发出题 + 边出边落库。返回 (新增, 跳过, 已落库)。"""
    if not rows:
        return 0, 0, 0
    created = skipped = written = 0
    total = len(rows)

    def handle(row: dict, case, err) -> None:
        nonlocal created, skipped, written
        if case is None:
            skipped += 1
            label = f"{row.get('doc_name', '?')}:{row.get('chunk_index', '?')}"
            print(f"  · 跳过 [{label}] {err or '模型判定不适合出题'}", flush=True)
            return
        created += 1
        if not ns.dry_run:
            add_case(case["question"], case["expected_refs"], case["reference_answer"], origin=case["origin"])
            written += 1
        print(f"  ✓ {created + skipped}/{total}  {case['expected_refs']}  {case['question'][:52]}", flush=True)

    if ns.workers > 1 and total > 1:
        with ThreadPoolExecutor(max_workers=ns.workers) as pool:
            futures = [pool.submit(_gen_one, row, llm, multi) for row in rows]
            for fut in as_completed(futures):
                row, case, err = fut.result()
                handle(row, case, err)
    else:
        for row in rows:
            _r, case, err = _gen_one(row, llm, multi)
            handle(row, case, err)
    return created, skipped, written


def main() -> None:
    parser = argparse.ArgumentParser(description="从语料自动构建评测集")
    parser.add_argument("--count", type=int, default=50, help="单片段用例数量")
    parser.add_argument("--multihop", type=int, default=6, help="跨片段用例数量")
    parser.add_argument("--per-doc-cap", type=int, default=None, help="每篇文档最多取多少个片段")
    parser.add_argument("--seed", type=int, default=20260914)
    parser.add_argument("--workers", type=int, default=1, help="出题并发数（>1 时多线程调 LLM）")
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
    print(f"采样出 {len(single_rows)} 块用于单片段出题；workers={ns.workers}\n")

    total_created = total_skipped = total_written = 0
    c, s, w = _generate_batch(single_rows, llm, ns)
    total_created += c
    total_skipped += s
    total_written += w

    # 跨片段用例：同一文档内相距 ≥50 块的两处，逼出「多跳整合」
    if ns.multihop > 0:
        by_doc: dict[str, list[dict]] = {}
        for row in chunks:
            by_doc.setdefault(row["doc_name"], []).append(row)
        pairs: list[dict] = []
        for bucket in by_doc.values():
            ordered = sorted(bucket, key=lambda r: r["chunk_index"])
            for i in range(0, len(ordered) - 1, max(1, len(ordered) // 3)):
                for j in range(i + 1, len(ordered)):
                    if ordered[j]["chunk_index"] - ordered[i]["chunk_index"] >= 50:
                        pairs.append({"a": ordered[i], "b": ordered[j],
                                      "doc_name": ordered[i]["doc_name"],
                                      "chunk_index": ordered[i]["chunk_index"]})
                        break
        pairs = pairs[: ns.multihop]
        print(f"\n跨片段出题 {len(pairs)} 组")
        c, s, w = _generate_batch(pairs, llm, ns, multi=True)
        total_created += c
        total_skipped += s
        total_written += w

    print()
    if ns.dry_run:
        print(f"（dry-run）将写入 {total_created} 条，跳过 {total_skipped} 条")
        return

    print(f"已写入 {total_written} 条（跳过 {total_skipped} 条）；评测集现有 {len(load_cases())} 条")


if __name__ == "__main__":
    main()
