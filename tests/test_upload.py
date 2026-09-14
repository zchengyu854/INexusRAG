"""上传去重（内容哈希）与软删除的行为保证。

不连真实 PostgreSQL：DB 函数全部打桩，上传目录指到临时目录，离线可跑。
"""
import asyncio
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import UploadFile
from starlette.background import BackgroundTasks

from src.api.routes import delete_document, trigger_ingest, upload


def _upload_file(name: str, content: bytes) -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(content))


class UploadDedupeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dir_patch = patch("src.api.routes._UPLOAD_DIR", self.tmp)
        self.dir_patch.start()
        self.addCleanup(self.dir_patch.stop)

    def _call(self, name: str, content: bytes, **patches):
        stack = []
        mocks = {}
        for target, kwargs in patches.items():
            p = patch(f"src.api.routes.{target}", **kwargs)
            mocks[target] = p.start()
            stack.append(p)
        try:
            return asyncio.run(upload(_upload_file(name, content))), mocks
        finally:
            for p in stack:
                p.stop()

    def test_same_content_returns_existing_document(self):
        """同一份内容重复上传：幂等返回既有文档，不新建、不落第二份文件。"""
        existing = {"id": "doc-1", "filename": "a.md", "status": "ready", "deleted_at": None}
        created = MagicMock()
        result, mocks = self._call(
            "a.md", b"same-bytes",
            find_document_by_hash=dict(return_value=existing),
            create_document=dict(return_value=None),
        )
        self.assertEqual(result["id"], "doc-1")
        self.assertTrue(result["duplicate"])
        mocks["create_document"].assert_not_called()
        self.assertEqual(list(self.tmp.iterdir()), [])  # 没有新增磁盘文件

    def test_new_content_creates_document_with_hash(self):
        """新内容：建文档并把 sha256 写进去，文件用内容寻址命名。"""
        result, mocks = self._call(
            "b.md", b"fresh-bytes",
            find_document_by_hash=dict(return_value=None),
            create_document=dict(return_value=None),
        )
        self.assertFalse(result["duplicate"])
        mocks["create_document"].assert_called_once()
        args = mocks["create_document"].call_args.args
        self.assertEqual(args[1], "b.md")
        self.assertEqual(len(args[3]), 64)  # sha256 十六进制长度
        files = list(self.tmp.iterdir())
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].name.endswith("_b.md"))
        self.assertEqual(files[0].read_bytes(), b"fresh-bytes")

    def test_reupload_after_soft_delete_restores_same_row(self):
        """软删除过的同一内容：重传即恢复，复用原文档行而不是新建。"""
        deleted = {"id": "doc-9", "filename": "c.md", "status": "ready", "deleted_at": "2026-09-14"}
        result, mocks = self._call(
            "c.md", b"restore-me",
            find_document_by_hash=dict(return_value=deleted),
            create_document=dict(return_value=None),
            restore_document=dict(return_value=None),
        )
        self.assertTrue(result["restored"])
        self.assertEqual(result["id"], "doc-9")
        self.assertEqual(result["status"], "indexing")  # 需要重新入库
        mocks["restore_document"].assert_called_once()
        mocks["create_document"].assert_not_called()


class SoftDeleteTests(unittest.TestCase):
    def test_delete_is_soft_and_keeps_source_file(self):
        """删除只标记 deleted_at，磁盘原文保留（否则重传无法恢复）。"""
        source = Path(tempfile.mkdtemp()) / "keep.md"
        source.write_text("原文")
        self.addCleanup(shutil.rmtree, source.parent, True)
        doc = {"id": "doc-1", "source_path": str(source)}

        with patch("src.api.routes.get_document", return_value=doc), \
             patch("src.api.routes.delete_document_record", return_value=1) as soft_delete:
            result = asyncio.run(delete_document("doc-1"))

        self.assertTrue(result["soft_deleted"])
        soft_delete.assert_called_once_with("doc-1")
        self.assertTrue(source.exists())

    def test_delete_missing_document_is_404(self):
        from fastapi import HTTPException

        with patch("src.api.routes.get_document", return_value=None):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(delete_document("nope"))
        self.assertEqual(caught.exception.status_code, 404)


class IngestIdempotencyTests(unittest.TestCase):
    def test_ready_document_is_not_reingested(self):
        """前端是「上传后必调 ingest」的串联流程，已入库的文档要幂等跳过。"""
        doc = {"id": "doc-1", "status": "ready", "chunks": 12, "deleted_at": None,
               "filename": "a.md", "source_path": "x"}
        tasks = BackgroundTasks()
        with patch("src.api.routes.get_document", return_value=doc), \
             patch("src.api.routes._ingest_document") as ingest, \
             patch("src.api.routes._doc_info", return_value="info"):
            out = asyncio.run(trigger_ingest("doc-1", tasks))
        self.assertEqual(out, "info")
        self.assertEqual(tasks.tasks, [])  # 没有排入入库任务
        ingest.assert_not_called()

    def test_force_reingest_still_schedules(self):
        doc = {"id": "doc-1", "status": "ready", "chunks": 12, "deleted_at": None,
               "filename": "a.md", "source_path": "x"}
        tasks = BackgroundTasks()
        with patch("src.api.routes.get_document", return_value=doc), \
             patch("src.api.routes.update_document", return_value=None), \
             patch("src.api.routes._doc_info", return_value="info"):
            asyncio.run(trigger_ingest("doc-1", tasks, force=True))
        self.assertEqual(len(tasks.tasks), 1)

    def test_deleted_document_cannot_be_ingested(self):
        from fastapi import HTTPException

        doc = {"id": "doc-1", "status": "ready", "chunks": 0, "deleted_at": "2026-09-14"}
        with patch("src.api.routes.get_document", return_value=doc):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(trigger_ingest("doc-1", BackgroundTasks()))
        self.assertEqual(caught.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
