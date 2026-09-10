from __future__ import annotations

import base64
import os
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


def extract_page_images(path: Path | str, pages: list[int], max_per_page: int = 3) -> list[dict]:
    """提取 PDF 指定页的嵌入图，返回 [{page, width, height, data_uri}]；页码无效或无图则跳过。"""
    out: list[dict] = []
    with pymupdf.open(path) as doc:
        for page_number in sorted(set(pages)):
            if not (1 <= page_number <= doc.page_count):
                continue
            page = doc[page_number - 1]
            for img in list(page.get_images())[:max_per_page]:
                xref, width, height = img[0], img[2], img[3]
                if width < 40 or height < 40:  # 与 captioning 同源阈值，跳过图标
                    continue
                pix = pymupdf.Pixmap(doc, xref)
                if pix.colorspace and pix.colorspace.n > 3:  # CMYK 等转 RGB
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                png = base64.b64encode(pix.tobytes("png")).decode()
                if len(png) > 512 * 1024:  # 单图上限，超了跳过
                    continue
                out.append({"page": page_number, "width": pix.width, "height": pix.height,
                            "data_uri": f"data:image/png;base64,{png}"})
                if len(out) >= 6:  # ponytail: 总量上限 6 张
                    return out
    return out


def describe_images(page, page_number: int, min_width: int = 40, min_height: int = 40) -> str:
    """用视觉 LLM 给页面图片生成简短描述，拼入本页切片使内容可检索。"""
    from src.llm.client import get_llm

    llm = get_llm()
    if not llm.enabled:
        return ""
    parts: list[str] = []
    seen: set[str] = set()
    for xref in page.get_images(full=True):
        try:
            pix = pymupdf.Pixmap(page.parent, xref[0])
        except Exception:
            continue
        if pix.width < min_width or pix.height < min_height:
            continue  # 图标/装饰小图
        if pix.n - pix.alpha > 3:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        b64 = base64.b64encode(pix.tobytes("png")).decode()
        try:
            response = llm._get_client().chat.completions.create(
                model=os.getenv("VISION_MODEL") or llm.model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "用不超过50字描述这张图的内容与作用。"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                }],
                max_tokens=100,
            )
            caption = (response.choices[0].message.content or "").strip()
            if caption and caption not in seen:
                seen.add(caption)
                parts.append(caption)
        except Exception:
            continue  # 单图失败不影响该页其余内容
    if not parts:
        return ""
    return f"第{page_number}页（图片）：" + "；".join(parts)


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
