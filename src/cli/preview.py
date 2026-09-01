"""CLI 切片预览工具。

用法:
    python -m src.cli.preview data/test_docs/fastapi_readme.md
    python -m src.cli.preview data/test_docs/fastapi_readme.md --chunk-size 200
    python -m src.cli.preview data/test_docs/fastapi_readme.md --verbose
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.ingestion.splitter import split_text


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


def preview(path: str, chunk_size: int, chunk_overlap: int, min_chunk_size: int, verbose: bool) -> None:
    filepath = Path(path)
    if not filepath.exists():
        print(f"错误: 文件不存在: {path}", file=sys.stderr)
        sys.exit(1)

    doc_name = filepath.name
    chunks = split_text(
        filepath.read_text(encoding="utf-8"),
        doc_name=doc_name,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        min_chunk_size=min_chunk_size,
    )

    print(f"\n{'='*60}")
    print(f"  文档: {doc_name}")
    print(f"  切片数: {len(chunks)} | chunk_size={chunk_size} overlap={chunk_overlap} min={min_chunk_size}")
    print(f"{'='*60}\n")

    for i, chunk in enumerate(chunks):
        print(f"── 块 #{i} [{chunk.chunk_id}] ({len(chunk.text)} chars) ──")
        # 显示前200字符预览
        preview_text = chunk.text[:300]
        if len(chunk.text) > 300:
            preview_text += "...\n[截断]"
        print(preview_text)
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="预览文档切分结果")
    parser.add_argument("path", help="文档路径（.md/.txt/.pdf）")
    parser.add_argument("--chunk-size", type=int, default=512, help="切片大小（默认 512）")
    parser.add_argument("--chunk-overlap", type=int, default=64, help="重叠字符数（默认 64）")
    parser.add_argument("--min-chunk-size", type=int, default=64, help="最小切片大小（默认 64）")
    parser.add_argument("-v", "--verbose", action="store_true", help="显示 DEBUG 日志")
    args = parser.parse_args()

    setup_logging(args.verbose)
    preview(
        args.path,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        min_chunk_size=args.min_chunk_size,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
