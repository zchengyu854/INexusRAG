import types
import unittest

from unittest.mock import patch

from src.retrieval import (
    build_routing_summary,
    extract_terms,
    multi_query_search,
    plan_question,
    rrf_merge,
    two_stage_search,
)


def row(cid, score=0.9):
    return {"chunk_id": cid, "score": score}


class _FakePlanLLM:
    enabled = True

    def __init__(self, payload: str):
        self.model = "fake"
        self._payload = payload

    def tool_call(self, prompt: str, tool: dict) -> dict:
        import json as _json
        return _json.loads(self._payload)


_EMPTY_PLAN = {"subs": [], "step_back": None, "hyde": None}


class PlanTests(unittest.TestCase):
    def test_disabled_llm_returns_empty_plan(self):
        with patch("src.llm.client.get_llm", return_value=types.SimpleNamespace(enabled=False)):
            self.assertEqual(plan_question("什么是 RAG"), _EMPTY_PLAN)

    def test_plan_parses_all_three_fields(self):
        llm = _FakePlanLLM(
            '{"subs": ["RAG 是什么", "向量库怎么选型"], '
            '"step_back": "检索系统如何提高召回率", '
            '"hyde": "本文档讨论了检索与增强的关系，包含向量检索、关键词匹配以及上下文组装等关键环节，并比较了不同召回策略的优缺点……"}'
        )
        with patch("src.llm.client.get_llm", return_value=llm):
            plan = plan_question("复杂问题")
        self.assertEqual(plan["subs"], ["RAG 是什么", "向量库怎么选型"])
        self.assertEqual(plan["step_back"], "检索系统如何提高召回率")
        self.assertIn("向量检索", plan["hyde"])

    def test_plan_ignores_degenerate_fields(self):
        llm = _FakePlanLLM('{"subs": ["", "  "], "step_back": "短", "hyde": "太短"}')
        with patch("src.llm.client.get_llm", return_value=llm):
            self.assertEqual(plan_question("问题"), _EMPTY_PLAN)

    def test_malformed_llm_output_falls_back_to_empty(self):
        llm = _FakePlanLLM("我不太会输出 JSON")
        with patch("src.llm.client.get_llm", return_value=llm):
            self.assertEqual(plan_question("复杂问题"), _EMPTY_PLAN)

    def test_llm_failure_returns_empty_plan(self):
        class _BrokenLLM:
            enabled = True
            def tool_call(self, prompt, tool):
                raise RuntimeError("api down")
        with patch("src.llm.client.get_llm", return_value=_BrokenLLM()):
            self.assertEqual(plan_question("问题"), _EMPTY_PLAN)


    def test_two_stage_search_no_routing_is_global_vector_only(self):
        with patch("src.retrieval.search_doc_index") as sdi, \
             patch("src.retrieval.search_chunks", return_value=[row("a")]), \
             patch("src.retrieval.keyword_chunks", return_value=[]):
            two_stage_search([0.0], top_k=2, terms=[], use_routing=False)
            sdi.assert_not_called()

    def test_multi_query_search_features_off_skips_planning_and_uses_single_channel(self):
        with patch("src.retrieval.two_stage_search", return_value=[row("a")]) as tss, \
             patch("src.retrieval.plan_question") as plan, \
             patch("src.ingestion.embedder.get_embedder") as ge:
            ge.return_value.encode.return_value = [[0.0]]
            multi_query_search("原始问题", top_k=2, features=[])
            plan.assert_not_called()  # 规划类特性全关 → 不付 LLM 调用
            self.assertEqual(len(tss.call_args_list), 1)
            self.assertEqual(
                tss.call_args_list[0].kwargs,
                {"top_k": 2, "terms": [], "filters": None, "use_routing": False, "stats": None},
            )

    def test_multi_query_search_features_keywords_only_disables_routing(self):
        with patch("src.retrieval.two_stage_search", return_value=[row("a")]) as tss, \
             patch("src.retrieval.plan_question", return_value={"subs": ["子"], "step_back": None, "hyde": None}) as plan, \
             patch("src.ingestion.embedder.get_embedder") as ge:
            ge.return_value.encode.return_value = [[0.0]]
            multi_query_search("原始问题", top_k=2, features=["keywords"])
            plan.assert_not_called()  # keywords 不属于规划类
            self.assertTrue(all(not c.kwargs["use_routing"] for c in tss.call_args_list))
            self.assertTrue(all(c.kwargs["terms"] for c in tss.call_args_list))

    def test_multi_query_search_default_features_keeps_current_behavior(self):
        with patch("src.retrieval.two_stage_search", return_value=[]) as tss, \
             patch("src.retrieval.plan_question", return_value={"subs": [], "step_back": None, "hyde": None}), \
             patch("src.ingestion.embedder.get_embedder") as ge:
            ge.return_value.encode.return_value = [[0.0]]
            multi_query_search("原始问题", top_k=2)
            # 默认 = 路由+关键词开，无 rerank
            self.assertTrue(all(c.kwargs["use_routing"] for c in tss.call_args_list))
            self.assertTrue(all(c.kwargs["terms"] for c in tss.call_args_list))


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

    def test_multi_query_search_merges_subquestion_channels(self):
        def fake_tss(vec, top_k, terms, filters=None, use_routing=True, stats=None):
            if stats is not None:
                stats["channels"].append({"channel": "vector", "count": top_k})
            return [{"chunk_id": f"c-{i}", "text": f"{terms}-{i}"} for i in range(top_k)]

        plan = {"subs": ["子问题 A", "子问题 B"], "step_back": None, "hyde": None}
        with patch("src.retrieval.two_stage_search", side_effect=fake_tss) as tss_mock, \
             patch("src.retrieval.plan_question", return_value=plan), \
             patch("src.ingestion.embedder.get_embedder") as ge:
            ge.return_value.encode.return_value = [[0.0]] * 3
            results = multi_query_search("原始问题", top_k=2, filters={"page": 1})

        self.assertEqual(len(tss_mock.call_args_list), 3)  # 原问题 + 两个子问题
        self.assertTrue(all(c.kwargs.get("filters") == {"page": 1} for c in tss_mock.call_args_list))
        ids = [r["chunk_id"] for r in results]
        self.assertEqual(len(set(ids)), len(ids))  # RRF 按 chunk_id 去重

    def test_multi_query_search_full_plan_gives_four_channels(self):
        plan = {
            "subs": ["子问题 A"],
            "step_back": "抽象概念问题",
            "hyde": "假想文档段落，足够长能通过长度校验",
        }
        with patch("src.retrieval.two_stage_search", return_value=[]) as tss_mock, \
             patch("src.retrieval.plan_question", return_value=plan), \
             patch("src.ingestion.embedder.get_embedder") as ge:
            ge.return_value.encode.side_effect = lambda qs: [[0.0]] * len(qs)
            multi_query_search("原始问题", top_k=2)
        # 原问题 + 子问题 + 退步 + HyDE(纯向量, terms=[]) = 4 通道
        self.assertEqual(len(tss_mock.call_args_list), 4)
        self.assertEqual(tss_mock.call_args_list[3].kwargs["terms"], [])

    def test_rerank_failure_degrades_to_rrf_and_is_reported_as_skipped(self):
        """cross/colbert 依赖本地模型，缺失时不能让问答整体 500，且 trace 要说明原因。"""
        plan = {"subs": [], "step_back": None, "hyde": None}

        def fake_tss(vec, top_k, terms, filters=None, use_routing=True, stats=None):
            return [row("a", 0.9), row("b", 0.8)]

        with patch("src.retrieval.two_stage_search", side_effect=fake_tss), \
             patch("src.retrieval.plan_question", return_value=plan), \
             patch("src.ingestion.embedder.get_embedder") as ge, \
             patch("src.rerank.rerank", side_effect=RuntimeError("cross-encoder 未下载")):
            ge.return_value.encode.return_value = [[0.0]]
            out = multi_query_search("问题", top_k=1, features=["rerank"], debug=True)

        trace = out["trace"]
        self.assertNotIn("rerank", trace["applied"])
        reason = next(s["reason"] for s in trace["skipped"] if s["name"] == "rerank")
        self.assertIn("退回", reason)
        self.assertEqual([r["chunk_id"] for r in out["results"]], ["a"])

    def test_multi_query_search_empty_plan_is_single_channel(self):
        with patch("src.retrieval.two_stage_search", return_value=[]) as tss_mock, \
             patch("src.retrieval.plan_question", return_value={"subs": [], "step_back": None, "hyde": None}), \
             patch("src.ingestion.embedder.get_embedder") as ge:
            ge.return_value.encode.return_value = [[0.0]]
            multi_query_search("简单问题", top_k=2)
        # 门控：LLM 判定不需要分解/退步/HyDE → 仅原问题单通道
        self.assertEqual(len(tss_mock.call_args_list), 1)


if __name__ == "__main__":
    unittest.main()
