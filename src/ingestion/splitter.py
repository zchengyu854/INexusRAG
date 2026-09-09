"""Markdown-aware semantic text splitting for RAG ingestion."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from src.ingestion.loaders import describe_images, load, load_pdf_pages


@dataclass
class Chunk:
    """切片单元。"""

    text: str
    chunk_id: str  # "{doc_name}-{index}"
    doc_name: str
    metadata: dict | None = None


@dataclass
class _Block:
    text: str
    kind: Literal["prose", "list", "code"]


@dataclass
class _Section:
    heading_path: tuple[str, ...]
    blocks: list[_Block] = field(default_factory=list)


class TextSplitter:
    """
    Markdown-aware semantic splitter.

    Priority is: fenced code > heading section > blank-line block > sentence >
    character fallback. Heading paths are repeated in each chunk of a section
    so a retrieved chunk keeps its document context.
    """

    _heading_re = re.compile(r"^\s{0,3}(#{1,6})[ \t]+(.+?)\s*$")
    _setext_re = re.compile(r"^\s*(=+|-+)\s*$")
    _horizontal_rule_re = re.compile(r"^\s{0,3}(?:-{3,}|\*\s*\*\s*\*|_{3,})\s*$")
    _fence_open_re = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")
    _list_item_re = re.compile(r"^\s*(?:[-+*]|\d+[.)])[ \t]+")
    _sentence_re = re.compile(
        r"(?<=[。！？!?])\s*|(?<=[.!?])\s+(?=[A-Za-z0-9\u4e00-\u9fff])"
    )

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
    ):
        if chunk_size < 1:
            raise ValueError("chunk_size 必须大于 0")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(self, text: str, doc_name: str = "unknown") -> list[Chunk]:
        if not text.strip():
            return []

        result: list[Chunk] = []
        for section in self._parse_sections(text):
            for section_text in self._split_section(section):
                section_text = section_text.strip()
                if not section_text:
                    continue
                result.append(
                    Chunk(
                        text=section_text,
                        chunk_id=f"{doc_name}-{len(result)}",
                        doc_name=doc_name,
                        metadata={"heading_path": list(section.heading_path)},
                    )
                )
        return result

    def _parse_sections(self, text: str) -> list[_Section]:
        """Parse fenced code and headings before applying content split rules."""
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        sections: list[_Section] = []
        current = _Section(())
        sections.append(current)
        heading_stack: list[tuple[int, str]] = []
        text_buffer: list[str] = []

        def append_block(block: _Block) -> None:
            if current.blocks and block.kind == "list" and current.blocks[-1].kind == "list":
                current.blocks[-1].text += "\n" + block.text
            else:
                current.blocks.append(block)

        def flush_text() -> None:
            if not text_buffer:
                return
            block_text = "\n".join(text_buffer).strip()
            text_buffer.clear()
            if not block_text:
                return
            kind: Literal["prose", "list"] = (
                "list" if self._list_item_re.match(block_text) else "prose"
            )
            append_block(_Block(block_text, kind))

        i = 0
        while i < len(lines):
            line = lines[i]
            heading = self._heading_re.match(line)
            setext = (
                not heading
                and line.strip()
                and not self._list_item_re.match(line)
                and i + 1 < len(lines)
                and self._setext_re.match(lines[i + 1])
            )
            if heading or setext:
                flush_text()
                if heading:
                    level = len(heading.group(1))
                    title_text = heading.group(2).strip()
                    i += 1
                else:
                    level = 1 if lines[i + 1].lstrip().startswith("=") else 2
                    title_text = line.strip()
                    i += 2
                title = f"{'#' * level} {title_text}"
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, title))
                current = _Section(tuple(item[1] for item in heading_stack))
                sections.append(current)
                continue

            if self._horizontal_rule_re.match(line):
                flush_text()
                i += 1
                continue

            fence = self._fence_open_re.match(line)
            if fence:
                flush_text()
                marker = fence.group(1)
                fence_char = marker[0]
                fence_size = len(marker)
                code_lines = [line]
                i += 1
                while i < len(lines):
                    code_lines.append(lines[i])
                    closing = re.match(
                        rf"^\s*{re.escape(fence_char)}{{{fence_size},}}\s*$",
                        lines[i],
                    )
                    i += 1
                    if closing:
                        break
                append_block(_Block("\n".join(code_lines).strip(), "code"))
                continue

            if not line.strip():
                flush_text()
            else:
                text_buffer.append(line)
            i += 1

        flush_text()
        return [section for section in sections if section.blocks]

    def _split_section(self, section: _Section) -> list[str]:
        heading = "\n".join(section.heading_path)
        if not section.blocks:
            return []

        # Keep room for the heading context in every chunk. chunk_size is a
        # maximum for an oversized semantic unit, not a target to fill.
        heading_cost = len(heading) + 2 if heading else 0
        body_capacity = self.chunk_size - heading_cost
        if body_capacity <= 0:
            body_capacity = self.chunk_size
            heading = ""

        rendered: list[str] = []
        for block in section.blocks:
            pieces = self._split_block(block, body_capacity)
            rendered.extend(self._render_block(pieces, heading, body_capacity, block.kind))
        return rendered

    def _render_block(
        self,
        pieces: list[str],
        heading: str,
        capacity: int,
        kind: Literal["prose", "list", "code"],
    ) -> list[str]:
        """Render one semantic block without combining it with its neighbors."""
        rendered: list[str] = []
        use_overlap = self.chunk_overlap > 0 and kind == "prose" and len(pieces) > 1
        for index, piece in enumerate(pieces):
            body = piece
            if use_overlap and index:
                tail = pieces[index - 1][-self.chunk_overlap :]
                room = capacity - len(body) - 2
                if room > 0:
                    body = f"{tail[-room:]}\n\n{body}"
            rendered.append(f"{heading}\n\n{body}" if heading else body)
        return rendered

    def _split_block(self, block: _Block, capacity: int) -> list[str]:
        if len(block.text) <= capacity:
            return [block.text]
        if block.kind == "code":
            return self._pack_code_lines(block.text.splitlines(), capacity)
        if block.kind == "list":
            return self._split_list(block.text, capacity)
        return self._split_prose(block.text, capacity)

    def _pack_code_lines(self, lines: list[str], capacity: int) -> list[str]:
        """Pack code lines while retaining indentation and line structure."""
        packed: list[str] = []
        current = ""
        for line in lines:
            parts = self._hard_split(line, capacity) if len(line) > capacity else [line]
            for part in parts:
                candidate = f"{current}\n{part}" if current else part
                if current and len(candidate) > capacity:
                    packed.append(current)
                    current = part
                else:
                    current = candidate
        if current:
            packed.append(current)
        return packed

    def _split_list(self, text: str, capacity: int) -> list[str]:
        """Keep list items together, falling back to sentences/chars per item."""
        items: list[str] = []
        current: list[str] = []
        for line in text.splitlines():
            if self._list_item_re.match(line) and current:
                items.append("\n".join(current).strip())
                current = []
            current.append(line)
        if current:
            items.append("\n".join(current).strip())

        pieces: list[str] = []
        for item in items:
            if len(item) <= capacity:
                pieces.append(item)
            else:
                pieces.extend(self._split_prose(item, capacity))
        return pieces

    def _split_prose(self, text: str, capacity: int) -> list[str]:
        sentences = [part.strip() for part in self._sentence_re.split(text) if part.strip()]
        pieces: list[str] = []
        for sentence in sentences or [text]:
            if len(sentence) <= capacity:
                pieces.append(sentence)
            else:
                pieces.extend(self._hard_split(sentence, capacity))
        return pieces

    @staticmethod
    def _hard_split(text: str, capacity: int) -> list[str]:
        if capacity <= 0:
            raise ValueError("切片容量必须大于 0")
        return [text[start : start + capacity] for start in range(0, len(text), capacity)]


def split_text(
    text: str,
    doc_name: str = "unknown",
    chunk_size: int = 512,
    chunk_overlap: int = 64,
) -> list[Chunk]:
    """Convenience wrapper for Markdown-aware semantic splitting."""
    return TextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    ).split(text, doc_name=doc_name)


def split_pdf_file(path: str | Path, doc_name: str | None = None, include_images: bool = True, **kwargs) -> list[Chunk]:
    """Split PDF pages independently and retain the source page in metadata."""
    import pymupdf as _pymupdf

    path = Path(path)
    options = dict(kwargs)
    if doc_name is None:
        doc_name = path.name
    result: list[Chunk] = []
    doc = _pymupdf.open(path)
    try:
        for page_number, page_text in load_pdf_pages(path):
            page_chunks = split_text(page_text, doc_name=doc_name, **options)
            if include_images:
                description = describe_images(doc[page_number - 1], page_number)
                if description:
                    page_chunks.append(Chunk(
                        text=description,
                        chunk_id="",
                        doc_name=doc_name,
                        metadata={"page": page_number, "figure": True},
                    ))
            for chunk in page_chunks:
                result.append(
                    Chunk(
                        text=chunk.text,
                        chunk_id=f"{doc_name}-{len(result)}",
                        doc_name=doc_name,
                        metadata={**(chunk.metadata or {}), "page": page_number},
                    )
                )
    finally:
        doc.close()
    return result


def split_document(path: str | Path, **kwargs) -> list[Chunk]:
    """Load and split a document, using page-aware rules for PDF files."""
    path = Path(path)
    options = dict(kwargs)
    doc_name = options.pop("doc_name", path.name)
    if path.suffix.lower() == ".pdf":
        return split_pdf_file(path, doc_name=doc_name, **options)
    return split_text(load(path), doc_name=doc_name, **options)


def split_file(path: str | Path, **kwargs) -> list[Chunk]:
    """Backward-compatible alias for document-aware splitting."""
    return split_document(path, **kwargs)
