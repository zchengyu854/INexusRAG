from __future__ import annotations

import re
from pathlib import Path

import pymupdf  # fitz


def _clean(text: str) -> str:
    """压缩空白，保留段落分隔。"""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_pdf_pages(path: Path | str) -> list[tuple[int, str]]:
    """Extract layout blocks page by page, retaining the original 1-based page number."""
    pages: list[tuple[int, str]] = []
    with pymupdf.open(path) as doc:
        for page_number, page in enumerate(doc, start=1):
            blocks: list[str] = []
            for block in page.get_text("blocks", sort=True):
                text = _clean(block[4])
                if text:
                    blocks.append(text)
            if blocks:
                pages.append((page_number, "\n\n".join(blocks)))
    return pages


def load_pdf(path: Path | str) -> str:
    """Extract PDF text while preserving page and layout-block separators."""
    return "\n\f\n".join(text for _, text in load_pdf_pages(path))


def load_md(path: Path | str) -> str:
    """读取 Markdown，保留标题、段落、列表和代码围栏供切片器处理。"""
    raw = Path(path).read_text(encoding="utf-8")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")

    lines: list[str] = []
    in_fence = False
    fence_char = ""
    for line in raw.split("\n"):
        fence = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
            elif marker[0] == fence_char:
                in_fence = False
            lines.append(line)
            continue
        if not in_fence:
            line = re.sub(r"<img\b[^>]*>", "", line, flags=re.IGNORECASE)
            line = re.sub(r"</?[^>]+>", "", line)
        lines.append(line)

    text = "\n".join(lines)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_txt(path: Path | str) -> str:
    """读取文本文件，尝试自动检测编码。"""
    raw = Path(path).read_bytes()
    # 简单 BOM + 常用编码回退
    for enc in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    else:
        text = raw.decode("utf-8", errors="ignore")
    return _clean(text)


def load(path: Path | str) -> str:
    """按扩展名分派：PDF → pymupdf，MD → markdown，TXT → 纯文本。"""
    path = Path(path)
    ext = path.suffix.lower()
    loaders = {
        ".pdf": load_pdf,
        ".md": load_md,
        ".markdown": load_md,
        ".txt": load_txt,
    }
    loader = loaders.get(ext)
    if loader is None:
        raise ValueError(f"不支持的文件类型: {ext}，支持 PDF / MD / TXT")
    text = loader(path)
    if not text.strip():
        raise ValueError(f"文件内容为空: {path.name}")
    return text
