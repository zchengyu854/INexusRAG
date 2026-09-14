"""存量切片去重：删除内容完全相同的重复切片、重排 chunk_index、改写评测引用。

背景：源文档可能自带多份相同内容（例如把同一部法律粘贴了三遍），入库后同一内容
会有多份切片。它们既浪费 embedding 与存储，又会在检索时互相稀释 RRF 名次。

用法：
    uv run python scripts/dedupe_chunks.py                  # dry-run，只报告将要做什么
    uv run python scripts/dedupe_chunks.py --apply           # 真正执行
    uv run python scripts/dedupe_chunks.py --doc X.md --apply  # 只处理指定文档

实现要点：
- 去重键用 splitter.chunk_key，与入库阶段的去重口径完全一致。
- chunks 上有 UNIQUE(document_id, chunk_index)，因此重排分两步走：
  先整体加一个偏移，再按保留顺序写回 0..N-1，避免中途撞唯一键。
- chunk_entities / graph_chunk_done 对 chunks 是 ON DELETE CASCADE，
  relations.evidence 是 ON DELETE SET NULL，删块后无需手工清理关联数据。
- 被删重复切片的内容仍存在于保留块中，所以评测 expected_refs 只需按
  「旧下标 → 保留块新下标」映射重写，评测口径不变。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation import load_cases, remap_expected_refs, update_expected_refs
from src.ingestion.splitter import chunk_key
from src.storage.database import connection

# 重排时的临时偏移，必须大于任何现有 chunk_index
_OFFSET = 10_000_000


def plan_document(conn, document_id: str) -> tuple[list[tuple[str, int]], list[str], dict[int, int], int]:
    """算出保留/删除清单与下标映射，不改动数据。

    返回 (keep[(chunk_id, new_index)], drop[chunk_id], old_index→new_index, before_count)。
    """
    rows = list(conn.execute(
        "SELECT id::text AS id, chunk_index, text FROM chunks WHERE document_id = %s ORDER BY chunk_index",
        [document_id],
    ))
    key_to_new: dict[str, int] = {}
    keep: list[tuple[str, int]] = []
    drop: list[str] = []
    mapping: dict[int, int] = {}
    for row in rows:
        key = chunk_key(row["text"])
        new_index = key_to_new.get(key)
        if new_index is None:
            new_index = len(keep)
            key_to_new[key] = new_index
            keep.append((row["id"], new_index))
        else:
            drop.append(row["id"])
        mapping[row["chunk_index"]] = new_index
    return keep, drop, mapping, len(rows)


def apply_document(conn, document_id: str, keep: list[tuple[str, int]], drop: list[str]) -> None:
    """删除重复块、两阶段重排下标、更新文档块数。"""
    conn.execute("DELETE FROM chunks WHERE id::text = ANY(%s)", [drop])
    conn.execute(
        "UPDATE chunks SET chunk_index = chunk_index + %s WHERE document_id = %s",
        [_OFFSET, document_id],
    )
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE chunks SET chunk_index = %s WHERE id::text = %s",
            [[new_index, chunk_id] for chunk_id, new_index in keep],
        )
    conn.execute("UPDATE documents SET chunks = %s WHERE id = %s", [len(keep), document_id])


def main() -> None:
    parser = argparse.ArgumentParser(description="存量切片去重")
    parser.add_argument("--apply", action="store_true", help="真正执行（默认只报告）")
    parser.add_argument("--doc", help="只处理指定文件名")
    ns = parser.parse_args()

    with connection() as conn:
        docs = list(conn.execute("SELECT id, filename FROM documents ORDER BY filename"))
        if ns.doc:
            docs = [doc for doc in docs if doc["filename"] == ns.doc]
            if not docs:
                print(f"未找到文档：{ns.doc}")
                return

        before_total = after_total = removed_total = 0
        touched_docs = 0
        for doc in docs:
            keep, drop, mapping, before = plan_document(conn, doc["id"])
            if not drop:
                continue
            after = len(keep)
            touched_docs += 1
            before_total += before
            after_total += after
            removed_total += len(drop)
            print(f"{doc['filename']}: {before} → {after} 块（删除重复 {len(drop)}）")

            # 只重写引用了本文档的评测例。读写都走同一条连接/事务：
            # 否则后一篇文档会读到未提交的旧引用，把前一篇的重映射覆盖掉。
            for case in load_cases(conn):
                new_refs = remap_expected_refs(case["expected_refs"], doc["filename"], mapping)
                if new_refs != case["expected_refs"]:
                    print(f"    eval#{case['id']}: {case['expected_refs']} → {new_refs}")
                    if ns.apply:
                        update_expected_refs(case["id"], new_refs, conn)

            if ns.apply:
                apply_document(conn, doc["id"], keep, drop)

        if not touched_docs:
            print("没有发现重复切片，无需处理。")
            return

        print()
        print(f"涉及文档 {touched_docs} 篇；切片 {before_total} → {after_total}，共删除 {removed_total} 块")
        if ns.apply:
            print("已执行。")
        else:
            print("以上为 dry-run；加 --apply 才会真正写入。")


if __name__ == "__main__":
    main()
