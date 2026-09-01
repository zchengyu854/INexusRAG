from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import markdown
import pymupdf  # fitz


def _clean(text: str) -> str:
    """压缩空白，保留段落分隔。"""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_pdf(path: Path | str) -> str:
    """提取 PDF 全文，含换行保留段落结构。"""
    doc = pymupdf.open(path)
    parts: list[str] = []
    for page in doc:
        text = page.get_text("text")
        if text.strip():
            parts.append(_clean(text))
    return "\n\n".join(parts)


def load_md(path: Path | str) -> str:
    """解析 Markdown 为纯文本（标题/列表转行，图片 alt 保留）。"""
    raw = Path(path).read_text(encoding="utf-8")

    # Markdown 图片：[alt](url) → [alt]，保留关键信息
    raw = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"[*\1*]", raw)
    # 删除链接括号但保留链接文字：[text](url) → text
    raw = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", raw)
    # 删除 HTML 标签
    raw = re.sub(r"<[^>]+>", "", raw)
    # Markdown → HTML → plain text（保留段落结构）
    html = markdown.markdown(raw, extensions=["tables"])
    # 简化 HTML 标签为换行/空格
    html = re.sub(r"<h[1-6][^>]*>", "\n## ", html)
    html = re.sub(r"</h[1-6][^>]*>", "\n", html)
    html = re.sub(r"<p[^>]*>", "\n", html)
    html = re.sub(r"</p>", "\n", html)
    html = re.sub(r"<li[^>]*>", "- ", html)
    html = re.sub(r"</li>", "\n", html)
    html = re.sub(r"<br\s*/?>", "\n", html)
    html = re.sub(r"<[^>]+>", "", html)

    return _clean(html)


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
