from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

from src.ingestion.loaders import load

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """切片单元。"""
    text: str
    chunk_id: str  # "{doc_name}-{index}"
    doc_name: str
    metadata: dict | None = None


class TextSplitter:
    """
    核心算法：分隔符按语义重量排优先级回退
    fence > 标题 > 空行 > 句子 > 字符

    1. ``` 预切分成 [prose, code, ...] 交替序列，代码块为原子单元（记 lang 元数据）
    2. prose 按标题切 section（标题归属内容，不独立成块）
    3. section 按空行切段落
    4. 贪心装箱：单元永不跨箱
    5. 超限单元降级：代码块按空行/行组切，段落回退 sentence
    6. overlap 用单元级（新块带前块最后一个单元），不用字符级
    7. 短尾块并入前块，不丢弃
    """

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        strategy: Literal["recursive", "sentence"] = "recursive",
        min_chunk_size: int = 64,
    ):
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")
        if chunk_size < min_chunk_size:
            raise ValueError(f"chunk_size 不能小于 {min_chunk_size}")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.strategy = strategy
        self.min_chunk_size = min_chunk_size

    def split(self, text: str, doc_name: str = "unknown") -> list[Chunk]:
        if not text.strip():
            return []

        # Step 1: fence 预切分 → [prose, code, ...] 交替序列
        segments = self._split_by_fences(text)
        logger.info("fence split: %d segments", len(segments))

        # Step 2-3: prose 按标题切 section，再按空行切段落；代码块保持原子
        units: list[dict] = []  # [{"text": ..., "type": "prose"|"code", "meta": ...}]
        for seg_type, seg_content, seg_meta in segments:
            if seg_type == "code":
                units.append({"text": seg_content, "type": "code", "meta": seg_meta})
                logger.debug("code block: %d chars, lang=%s", len(seg_content), seg_meta.get("lang") if seg_meta else None)
            else:
                sections = list(self._split_prose_by_headings(seg_content))
                logger.info("prose: %d sections", len(sections))
                for section in sections:
                    paras = list(self._split_by_paragraphs(section))
                    for para in paras:
                        if para.strip():
                            units.append({"text": para, "type": "prose", "meta": None})

        # Step 5: 超限单元降级 —— 代码块按空行/行组切，段落回退 sentence
        degraded: list[dict] = []
        degraded_count = 0
        for u in units:
            if len(u["text"]) <= self.chunk_size:
                degraded.append(u)
            elif u["type"] == "code":
                degraded.extend(self._degrade_code(u["text"], u["meta"]))
                degraded_count += 1
            else:
                degraded.extend(self._degrade_paragraph(u["text"]))
                degraded_count += 1
        if degraded_count:
            logger.info("degraded %d oversized units", degraded_count)

        # Step 4: 贪心装箱
        chunks = self._greedy_pack(degraded)

        # Step 7: 短尾块并入前块（在 overlap 之前，避免短块被 overlap 膨胀后跳过合并）
        before_merge = len(chunks)
        chunks = self._merge_short_tail(chunks)
        if len(chunks) < before_merge:
            logger.info("merged %d short tails into previous chunks", before_merge - len(chunks))

        # Step 6: 单元级 overlap
        if self.chunk_overlap > 0:
            chunks = self._apply_overlap(chunks)

        logger.info("total chunks: %d", len(chunks))

        # 生成最终 Chunk 对象
        result: list[Chunk] = []
        for i, c in enumerate(chunks):
            text = c.strip()
            if not text:
                continue
            result.append(Chunk(
                text=text,
                chunk_id=f"{doc_name}-{i}",
                doc_name=doc_name,
            ))
        return result

    # ── Step 1: fence 预切分 ──────────────────────────────────

    _fence_re = re.compile(r"^(```[\w+-]*\s*\n.*?\n```)", re.MULTILINE | re.DOTALL)

    def _split_by_fences(self, text: str) -> list[tuple[str, str, dict | None]]:
        """返回 [(type, content, meta), ...]，type = "prose"|"code"。"""
        result: list[tuple[str, str, dict | None]] = []
        last_end = 0
        for m in self._fence_re.finditer(text):
            # fence 之前的 prose
            if m.start() > last_end:
                result.append(("prose", text[last_end:m.start()], None))
            fence_block = m.group(1)
            # 提取语言标记
            first_line = fence_block.split("\n", 1)[0]
            lang = first_line[3:].strip() or None
            result.append(("code", fence_block, {"lang": lang}))
            last_end = m.end()
        # 剩余 prose
        if last_end < len(text):
            result.append(("prose", text[last_end:], None))
        return result

    # ── Step 2: prose 按标题切 section ────────────────────────

    _heading_re = re.compile(r"^(#{1,6}\s+.+)$", re.MULTILINE)

    def _split_prose_by_headings(self, text: str) -> list[str]:
        """标题归属后续内容，不独立成块。"""
        parts = self._heading_re.split(text)
        sections: list[str] = []
        buf = ""
        for p in parts:
            if self._heading_re.match(p):
                # 遇到新标题，把之前的 buf 存下
                if buf.strip():
                    sections.append(buf)
                buf = p  # 标题作为新 section 的开头
            else:
                buf += p
        if buf.strip():
            sections.append(buf)
        return sections if sections else [text]

    # ── Step 3: section 按空行切段落 ─────────────────────────

    def _split_by_paragraphs(self, text: str) -> list[str]:
        return [p for p in re.split(r"\n\s*\n", text) if p.strip()]

    # ── Step 5: 超限单元降级 ──────────────────────────────────

    def _degrade_code(self, code: str, meta: dict | None) -> list[dict]:
        """代码块降级：按空行或行组切，每块不超过 chunk_size。"""
        groups = re.split(r"\n\s*\n", code)
        result: list[dict] = []
        buf = ""
        for g in groups:
            candidate = buf + "\n\n" + g if buf else g
            if len(candidate) <= self.chunk_size:
                buf = candidate
            else:
                if buf.strip():
                    result.append({"text": buf, "type": "code", "meta": meta})
                buf = g
        if buf.strip():
            result.append({"text": buf, "type": "code", "meta": meta})
        # 如果单个 group 仍然超限，按行组切
        final: list[dict] = []
        for u in result:
            if len(u["text"]) <= self.chunk_size:
                final.append(u)
            else:
                final.extend(self._degrade_code_by_lines(u["text"], u["meta"]))
        return final

    def _degrade_code_by_lines(self, code: str, meta: dict | None) -> list[dict]:
        """行组切分：每 N 行一组，不超过 chunk_size。"""
        lines = code.split("\n")
        result: list[dict] = []
        buf = ""
        for line in lines:
            candidate = buf + "\n" + line if buf else line
            if len(candidate) <= self.chunk_size:
                buf = candidate
            else:
                if buf.strip():
                    result.append({"text": buf, "type": "code", "meta": meta})
                buf = line
        if buf.strip():
            result.append({"text": buf, "type": "code", "meta": meta})
        return result

    def _degrade_paragraph(self, text: str) -> list[dict]:
        """段落回退到句子切分。"""
        # 中英文句尾切分，保留分隔符
        sentences = re.split(r"(?<=[。！？.!?\n])\s*", text)
        result: list[dict] = []
        for s in sentences:
            if s.strip():
                result.append({"text": s, "type": "prose", "meta": None})
        return result

    # ── Step 4 + 6: 贪心装箱 + 单元级 overlap ────────────────

    def _greedy_pack(self, units: list[dict]) -> list[str]:
        """贪心装箱：单元永不跨箱。"""
        if not units:
            return []

        chunks: list[str] = []
        current_parts: list[str] = []
        current_len = 0

        for u in units:
            u_len = len(u["text"])
            if current_len + u_len <= self.chunk_size:
                current_parts.append(u["text"])
                current_len += u_len
            else:
                # 当前箱满了，保存
                if current_parts:
                    chunks.append("\n\n".join(current_parts))
                current_parts = [u["text"]]
                current_len = u_len

        if current_parts:
            chunks.append("\n\n".join(current_parts))

        return chunks

    def _apply_overlap(self, chunks: list[str]) -> list[str]:
        """单元级 overlap：新块（从第二个开始）开头附加前块的最后一个单元。"""
        if self.chunk_overlap <= 0 or len(chunks) <= 1:
            return chunks

        overlapped: list[str] = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_parts = chunks[i - 1].split("\n\n")
            # 取前块最后一个单元（按当前 chunk_overlap 截断）
            tail = prev_parts[-1]
            if len(tail) > self.chunk_overlap:
                tail = tail[:self.chunk_overlap]
            # 如果前缀已在新块中出现则跳过
            new_chunk = chunks[i]
            if not new_chunk.startswith(tail):
                new_chunk = tail + "\n\n" + new_chunk
            overlapped.append(new_chunk)
        return overlapped

    # ── Step 7: 短尾块并入前块 ────────────────────────────────

    def _merge_short_tail(self, chunks: list[str]) -> list[str]:
        """短尾块（< min_chunk_size）并入前块，不丢弃。"""
        if not chunks:
            return []

        merged: list[str] = [chunks[0]]
        for c in chunks[1:]:
            if len(c.strip()) < self.min_chunk_size:
                # 并入前块
                merged[-1] = merged[-1] + "\n\n" + c
            else:
                merged.append(c)

        # 处理第一个块本身就是短块的情况：如果整体都很短就保留（不丢弃）
        return merged


def split_text(
    text: str,
    doc_name: str = "unknown",
    chunk_size: int = 512,
    chunk_overlap: int = 64,
    strategy: Literal["recursive", "sentence"] = "recursive",
    min_chunk_size: int = 64,
) -> list[Chunk]:
    """便捷函数：直接传入文本 + 文档名返回 Chunk 列表。"""
    return TextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        strategy=strategy,
        min_chunk_size=min_chunk_size,
    ).split(text, doc_name=doc_name)


def split_file(path: str | Path, **kwargs) -> list[Chunk]:
    """从文件路径自动读取并切片（内部调用 loaders.load）。"""
    from pathlib import Path
    text = load(Path(path))
    doc_name = Path(path).name
    return split_text(text, doc_name=doc_name, **kwargs)
