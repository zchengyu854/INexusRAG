import tempfile
import unittest
from pathlib import Path

import pymupdf

from src.ingestion.loaders import load_md
from src.ingestion.splitter import split_document, split_pdf_file, split_text


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

    def test_overlap_and_short_tail_never_exceed_limit(self):
        text = "# Notes\n\n" + "Sentence one. Sentence two. Sentence three. " * 8
        chunks = split_text(text, chunk_size=80, chunk_overlap=12)

        self.assertTrue(all(len(chunk.text) <= 80 for chunk in chunks))
        if len(chunks) > 1:
            self.assertTrue(any(chunks[i].text[:12] in chunks[i - 1].text for i in range(1, len(chunks))))


if __name__ == "__main__":
    unittest.main()
