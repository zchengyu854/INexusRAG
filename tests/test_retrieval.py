import unittest

from unittest.mock import patch

from src.retrieval import (
    build_routing_summary,
    extract_terms,
    rrf_merge,
    two_stage_search,
)


def row(cid, score=0.9):
    return {"chunk_id": cid, "score": score}


class RetrievalTests(unittest.TestCase):
    def test_term_in_both_channels_ranks_first(self):
        vector = [row("a"), row("b"), row("c")]
        keyword = [row("b"), row("a")]
        merged = rrf_merge([vector, keyword], top_k=5)
        self.assertEqual([r["chunk_id"] for r in merged], ["a", "b", "c"])
        self.assertGreater(merged[0]["score"], merged[2]["score"])

    def test_single_channel_keeps_original_ranking(self):
        merged = rrf_merge([[row("x"), row("y")]], top_k=5)
        self.assertEqual([r["chunk_id"] for r in merged], ["x", "y"])

    def test_top_k_truncates(self):
        self.assertEqual(len(rrf_merge([[row(str(i)) for i in range(20)]], top_k=5)), 5)

    def test_extract_terms_filters_junk_and_single_chars(self):
        terms = extract_terms("如何安装数据库")
        self.assertIn("安装", terms)
        self.assertIn("数据库", terms)
        self.assertNotIn("如何", terms)

    def test_extract_terms_keeps_codes_and_numbers(self):
        self.assertIn("pgvector", extract_terms("pgvector 0.7 是什么"))
        self.assertNotIn("是什么", extract_terms("pgvector 0.7 是什么"))

    def test_two_stage_search_limits_vector_search_to_routed_docs(self):
        with patch("src.retrieval.search_doc_index", return_value=[{"doc_id": "d1", "score": 0.9}]), \
             patch("src.retrieval.search_chunks") as sc, \
             patch("src.retrieval.keyword_chunks", return_value=[]):
            two_stage_search([0.0], top_k=5, terms=[])
            self.assertEqual([c.kwargs.get("doc_id") for c in sc.call_args_list], ["d1"])

    def test_two_stage_search_falls_back_globally_when_routing_is_confident_none(self):
        with patch("src.retrieval.search_doc_index", return_value=[]), \
             patch("src.retrieval.search_chunks") as sc, \
             patch("src.retrieval.keyword_chunks", return_value=[]):
            two_stage_search([0.0], top_k=5, terms=[])
            self.assertEqual([c.kwargs.get("doc_id") for c in sc.call_args_list], [None])

    def test_low_route_score_adds_global_fallback_channel(self):
        with patch("src.retrieval.search_doc_index", return_value=[{"doc_id": "d1", "score": 0.1}]), \
             patch("src.retrieval.search_chunks") as sc, \
             patch("src.retrieval.keyword_chunks", return_value=[]):
            two_stage_search([0.0], top_k=5, terms=[])
            self.assertEqual([c.kwargs.get("doc_id") for c in sc.call_args_list], ["d1", None])

    def test_two_stage_search_passes_filters_to_all_channels(self):
        with patch("src.retrieval.search_doc_index", return_value=[{"doc_id": "d1", "score": 0.9}]), \
             patch("src.retrieval.search_chunks") as sc, \
             patch("src.retrieval.keyword_chunks") as kc:
            two_stage_search([0.0], top_k=5, terms=["x"], filters={"page": 7})
            self.assertTrue(all(c.kwargs.get("filters") == {"page": 7} for c in sc.call_args_list))
            self.assertEqual(kc.call_args.kwargs["filters"], {"page": 7})

    def test_build_routing_summary_dedupes_headings_and_truncates_opening(self):
        class C:
            def __init__(self, text, metadata):
                self.text = text
                self.metadata = metadata
        chunks = [
            C("a" * 300, {"heading_path": ["# 指南", "## 安装"]}),
            C("b", {"heading_path": ["# 指南", "## 安装", "### 验证"]}),
        ]
        summary = build_routing_summary("doc.pdf", chunks)
        self.assertTrue(summary.startswith("doc.pdf"))
        self.assertEqual(summary.count("## 安装"), 1)
        self.assertNotIn("### 验证", summary)
        self.assertLess(len(summary), 320)


if __name__ == "__main__":
    unittest.main()
