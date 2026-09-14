import tempfile
import unittest
from pathlib import Path

import pymupdf

from src.ingestion.loaders import load_md
from src.ingestion.splitter import Chunk, dedupe_chunks, split_document, split_pdf_file, split_text


class SplitterTests(unittest.TestCase):
    def test_markdown_sections_keep_heading_context(self):
        text = """# Guide

Intro.

## Install

- First step
- Second step

### Verify

It works.
"""
        chunks = split_text(text, doc_name="guide.md", chunk_size=96, chunk_overlap=0)

        self.assertTrue(chunks)
        self.assertTrue(all(len(chunk.text) <= 96 for chunk in chunks))
        self.assertTrue(any(chunk.metadata["heading_path"] == ["# Guide"] for chunk in chunks))
        self.assertTrue(
            any(chunk.metadata["heading_path"] == ["# Guide", "## Install"] for chunk in chunks)
        )
        self.assertTrue(
            any(chunk.metadata["heading_path"] == ["# Guide", "## Install", "### Verify"] for chunk in chunks)
        )
        self.assertTrue(any("- First step\n- Second step" in chunk.text for chunk in chunks))

    def test_paragraphs_are_not_filled_to_chunk_size(self):
        text = "# Notes\n\nShort paragraph one.\n\nShort paragraph two."
        chunks = split_text(text, chunk_size=512, chunk_overlap=64)

        self.assertEqual(len(chunks), 2)
        self.assertIn("Short paragraph one.", chunks[0].text)
        self.assertNotIn("Short paragraph two.", chunks[0].text)
        self.assertIn("Short paragraph two.", chunks[1].text)

    def test_setext_heading_and_fenced_code_are_preserved(self):
        text = """Guide
=====

```python
if True:
    print(\"ok\")
```
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "guide.md"
            path.write_text(text, encoding="utf-8")
            loaded = load_md(path)

        self.assertIn("=====", loaded)
        chunks = split_text(loaded, doc_name="guide.md", chunk_size=48, chunk_overlap=0)
        combined = "\n".join(chunk.text for chunk in chunks)
        self.assertIn("```python", combined)
        self.assertIn('    print("ok")', combined)
        self.assertTrue(all(len(chunk.text) <= 48 for chunk in chunks))

    def test_pdf_pages_keep_hard_page_boundaries_and_page_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "guide.pdf"
            document = pymupdf.open()
            for title in ("Page one", "Page three"):
                page = document.new_page()
                page.insert_text((72, 72), title)
            document.save(path)
            document.close()

            chunks = split_document(path, chunk_size=96, chunk_overlap=0)

        self.assertEqual([chunk.metadata["page"] for chunk in chunks], [1, 2])
        self.assertIn("Page one", chunks[0].text)
        self.assertIn("Page three", chunks[1].text)
        self.assertTrue(all(len(chunk.text) <= 96 for chunk in chunks))


        text = "没有句号的超长内容" * 30
        chunks = split_text(text, chunk_size=32, chunk_overlap=0)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk.text) <= 32 for chunk in chunks))
        self.assertEqual("".join(chunk.text for chunk in chunks), text)

    def test_figure_description_is_stored_as_chunk_with_page(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fig.pdf"
            document = pymupdf.open()
            page = document.new_page()
            page.insert_text((72, 72), "Body text.")
            page.insert_image(pymupdf.Rect(72, 100, 300, 260),
                              pixmap=pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 200, 150)))
            document.save(path)
            document.close()

            from unittest.mock import patch
            with patch("src.ingestion.splitter.describe_images",
                       return_value="第1页（图片）：检索流程示意图") as mock_desc:
                chunks = split_pdf_file(path, doc_name="fig.pdf", include_images=True)
            mock_desc.assert_called_once()

        figures = [c for c in chunks if c.metadata.get("figure")]
        self.assertEqual(len(figures), 1)
        self.assertEqual(figures[0].metadata["page"], 1)
        self.assertIn("第1页（图片）", figures[0].text)

    def test_list_and_extract_page_image_share_index(self):
        from src.ingestion.loaders import extract_page_image_png, list_page_images

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fig.pdf"
            document = pymupdf.open()
            page = document.new_page()
            page.insert_image(
                pymupdf.Rect(72, 100, 300, 260),
                pixmap=pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 200, 150)),
            )
            document.save(path)
            document.close()

            listed = list_page_images(path, [1])
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["page"], 1)
            self.assertEqual(listed[0]["index"], 0)
            png = extract_page_image_png(path, listed[0]["page"], listed[0]["index"])
            self.assertIsNotNone(png)
            self.assertGreater(len(png), 20)
            self.assertIsNone(extract_page_image_png(path, 1, 9))

    def test_overlap_and_short_tail_never_exceed_limit(self):
        text = "# Notes\n\n" + "Sentence one. Sentence two. Sentence three. " * 8
        chunks = split_text(text, chunk_size=80, chunk_overlap=12)

        self.assertTrue(all(len(chunk.text) <= 80 for chunk in chunks))
        if len(chunks) > 1:
            self.assertTrue(any(chunks[i].text[:12] in chunks[i - 1].text for i in range(1, len(chunks))))


class DedupeChunksTests(unittest.TestCase):
    """源文档自带多份相同内容时，入库只应保留一份。"""

    def _chunk(self, index: int, text: str) -> Chunk:
        return Chunk(text=text, chunk_id=f"doc.md-{index}", doc_name="doc.md")

    def test_exact_duplicates_are_dropped_keeping_first(self):
        chunks = [
            self._chunk(0, "第一条 立法目的"),
            self._chunk(1, "第二条 调整范围"),
            self._chunk(2, "第一条 立法目的"),  # 第二份拷贝
        ]
        out = dedupe_chunks(chunks)
        self.assertEqual([c.text for c in out], ["第一条 立法目的", "第二条 调整范围"])

    def test_chunk_ids_are_renumbered_after_dedupe(self):
        chunks = [
            self._chunk(0, "甲"),
            self._chunk(1, "乙"),
            self._chunk(2, "甲"),
            self._chunk(3, "丙"),
        ]
        out = dedupe_chunks(chunks)
        self.assertEqual([c.chunk_id for c in out], ["doc.md-0", "doc.md-1", "doc.md-2"])

    def test_whitespace_only_differences_are_treated_as_duplicates(self):
        chunks = [
            self._chunk(0, "第一条  立法目的\n"),
            self._chunk(1, "第一条 立法目的"),
        ]
        self.assertEqual(len(dedupe_chunks(chunks)), 1)

    def test_distinct_content_is_preserved(self):
        chunks = [self._chunk(i, f"第{i}条 内容 {i}") for i in range(5)]
        self.assertEqual(len(dedupe_chunks(chunks)), 5)

    def test_empty_list_is_returned_as_is(self):
        self.assertEqual(dedupe_chunks([]), [])


if __name__ == "__main__":
    unittest.main()
