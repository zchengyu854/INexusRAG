"""Lightweight tests for ingest-time graph hooks (no DB / LLM)."""
import os
import unittest
from unittest.mock import patch

from src.api import routes


class AutoBuildGraphTests(unittest.TestCase):
    def test_flag_defaults_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AUTO_BUILD_GRAPH", None)
            self.assertFalse(routes._auto_build_graph_enabled())

    def test_flag_accepts_truthy(self):
        for value in ("1", "true", "YES"):
            with patch.dict(os.environ, {"AUTO_BUILD_GRAPH": value}):
                self.assertTrue(routes._auto_build_graph_enabled(), value)

    def test_maybe_build_skips_when_disabled(self):
        with patch.dict(os.environ, {"AUTO_BUILD_GRAPH": "0"}), \
             patch("src.graph.build_document") as build:
            routes._maybe_build_graph("doc-1")
        build.assert_not_called()

    def test_maybe_build_calls_resume_when_enabled(self):
        with patch.dict(os.environ, {"AUTO_BUILD_GRAPH": "1"}), \
             patch("src.graph.build_document", return_value=3) as build:
            routes._maybe_build_graph("doc-1")
        build.assert_called_once_with("doc-1", resume=True)

    def test_maybe_build_swallows_errors(self):
        with patch.dict(os.environ, {"AUTO_BUILD_GRAPH": "1"}), \
             patch("src.graph.build_document", side_effect=RuntimeError("llm")):
            routes._maybe_build_graph("doc-1")  # must not raise


if __name__ == "__main__":
    unittest.main()
