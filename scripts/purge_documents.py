"""文档维护：内容哈希回填 + 软删除文档的物理清理。

软删除（DELETE /documents/{id}）只标记 deleted_at 并回收检索索引，磁盘原文保留，
所以「删错了」重新上传同一份文件即可恢复。本脚本负责两件维护工作：
  1) 回填 source_sha256 —— 加哈希去重之前入库的文档没有哈希，不回填则去重不生效；
  2) 物理清理 —— 真正释放已软删除文档占用的空间。

用法：
    uv run python scripts/purge_documents.py --backfill          # 回填缺失的内容哈希
    uv run python scripts/purge_documents.py                      # dry-run，列出将清理的内容
    uv run python scripts/purge_documents.py --apply               # 清理所有已软删除的文档
    uv run python scripts/purge_documents.py --days 7 --apply      # 只清理 7 天前删除的
    uv run python scripts/purge_documents.py --orphans --apply     # 顺带清理磁盘孤儿文件
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage.database import (
    connection,
    documents_missing_hash,
    purge_deleted_documents,
    set_document_hash,
)

_UPLOAD_DIR = Path("data/uploads")


def backfill_hashes() -> None:
    """给缺哈希的文档补上 source_sha256（读磁盘原文算，源文件丢失则跳过）。"""
    pending = documents_missing_hash()
    if not pending:
        print("所有文档都已有内容哈希，无需回填。")
        return
    done = missing_file = 0
    for doc in pending:
        path = Path(doc["source_path"])
        if not path.exists():
            missing_file += 1
            print(f"  跳过（源文件不存在）：{doc['filename']} → {path}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        set_document_hash(doc["id"], digest)
        done += 1
        print(f"  已回填：{doc['filename']} → {digest[:12]}")
    print(f"回填完成：{done} 篇；跳过 {missing_file} 篇。")


def _referenced_paths() -> set[str]:
    """当前仍被任一文档行引用的磁盘路径（含软删除的，它们在被清理前仍可恢复）。"""
    with connection() as conn:
        rows = conn.execute("SELECT source_path FROM documents WHERE source_path IS NOT NULL")
    return {row["source_path"] for row in rows}


def _orphan_files(referenced: set[str]) -> list[Path]:
    """磁盘上存在、但没有任何文档行引用的文件。"""
    if not _UPLOAD_DIR.exists():
        return []
    return sorted(
        path for path in _UPLOAD_DIR.iterdir()
        if path.is_file() and str(path) not in referenced
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="文档维护：哈希回填 + 软删除清理")
    parser.add_argument("--days", type=int, default=0, help="只清理软删除超过 N 天的文档（默认 0）")
    parser.add_argument("--apply", action="store_true", help="真正执行（默认只报告）")
    parser.add_argument("--orphans", action="store_true", help="同时清理磁盘上的无主文件")
    parser.add_argument("--backfill", action="store_true", help="回填缺失的 source_sha256 后退出")
    ns = parser.parse_args()

    if ns.backfill:
        backfill_hashes()
        return

    referenced = _referenced_paths()

    if not ns.apply:
        # dry-run：只列出，不动数据（复用同一 SQL 的只读版本）
        with connection() as conn:
            pending = list(conn.execute(
                """
                SELECT id, filename, source_path FROM documents
                 WHERE deleted_at IS NOT NULL
                   AND deleted_at <= now() - make_interval(days => %s)
                """,
                (max(0, ns.days),),
            ))
        print(f"待物理清理的软删除文档：{len(pending)} 篇")
        for row in pending:
            print(f"  - {row['filename']}（{row['id']}）→ {row['source_path']}")
        if ns.orphans:
            orphans = _orphan_files(referenced)
            print(f"\n磁盘孤儿文件：{len(orphans)} 个")
            for path in orphans:
                print(f"  - {path}")
        print("\n以上为 dry-run；加 --apply 才会真正删除。")
        return

    rows = purge_deleted_documents(ns.days)
    print(f"已删除文档行：{len(rows)} 篇")
    removed_files = 0
    for row in rows:
        path = Path(row["source_path"])
        # 同一路径可能仍被其它文档行引用（内容寻址命名），确认无引用再删
        remaining = _referenced_paths()
        if path.exists() and str(path) not in remaining:
            path.unlink()
            removed_files += 1
    print(f"已删除磁盘原文：{removed_files} 个")

    if ns.orphans:
        orphans = _orphan_files(_referenced_paths())
        for path in orphans:
            path.unlink()
        print(f"已删除孤儿文件：{len(orphans)} 个")


if __name__ == "__main__":
    main()
