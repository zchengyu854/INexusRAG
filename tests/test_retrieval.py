import types
import unittest

from unittest.mock import patch

from src.retrieval import (
    ALL_FEATURES,
    _DEFAULT_FEATURES,
    _extract_article_terms,
    _gate_keyword_rows,
    _relevance_filter,
    build_routing_summary,
    expand_terms,
    extract_terms,
    multi_query_search,
    plan_question,
    rewrite_query,
    rrf_merge,
    search_terms,
    synonym_group,
    two_stage_search,
)


def row(cid, score=0.9):
    return {"chunk_id": cid, "score": score}


class SynonymTests(unittest.TestCase):
    """同义词映射：让「插图」能匹配到写「图片」的切片，且不至于把过滤条件放宽成 OR。"""

    def test_known_word_returns_its_group(self):
        self.assertIn("图片", synonym_group("插图"))
        self.assertIn("插图", synonym_group("图片"))
        self.assertIn("illustration", synonym_group("插图"))

    def test_unknown_word_is_its_own_group(self):
        self.assertEqual(synonym_group("民法典"), ("民法典",))

    def test_expand_terms_adds_variants_without_duplicates(self):
        out = expand_terms(["插图", "第4页"])
        self.assertIn("图片", out)
        self.assertIn("第4页", out)
        self.assertEqual(len(out), len(set(out)))

    def test_search_terms_expands_question_keywords(self):
        self.assertIn("图片", search_terms("第4页的插图是什么？"))

    def test_filter_accepts_synonym_variant(self):
        """关键行为：问「插图」而切片写「图片」，应算命中而不是被滤掉。"""
        results = [
            {"chunk_id": "hit", "text": "第4页（图片）：卡通机器人图标", "vector_score": 0.4},
            {"chunk_id": "miss", "text": "第4页的正文段落", "vector_score": 0.4},
        ]
        out = _relevance_filter(results, "第4页的插图是什么？")
        self.assertEqual([r["chunk_id"] for r in out], ["hit"])

    def test_filter_still_requires_every_group(self):
        """同义词只在组内放宽，组间仍是 AND——少一个概念的切片不能混进来。

        注意这里不能用「第4页的插图是什么」：jieba 会把「第4页」切成 第/4/页，
        三者都被停用词与单字规则过滤掉，整句只剩「插图」一个概念，验证不了组间 AND。
        """
        results = [
            {"chunk_id": "only_synonym", "text": "这里有一张图片", "vector_score": 0.4},
        ]
        self.assertEqual(_relevance_filter(results, "RAG 论文的插图是什么"), [])

    def test_filter_keeps_chunk_matching_all_groups(self):
        results = [
            {"chunk_id": "both", "text": "RAG 论文第4页的图片：卡通机器人图标", "vector_score": 0.4},
            {"chunk_id": "partial", "text": "RAG 论文的正文段落", "vector_score": 0.4},
        ]
        out = _relevance_filter(results, "RAG 论文的插图是什么")
        self.assertEqual([r["chunk_id"] for r in out], ["both"])

    def test_keyword_channel_receives_expanded_terms(self):
        """扩召回必须落到关键词通道上，否则同义词只是空转。"""
        captured: dict = {}

        def fake_tss(vector, top_k, terms, filters=None, use_routing=True, stats=None):
            captured["terms"] = terms
            return [row("a")]

        with patch("src.retrieval.two_stage_search", side_effect=fake_tss), \
             patch("src.retrieval.plan_question", return_value={"subs": [], "step_back": None, "hyde": None}), \
             patch("src.retrieval.keyword_chunks", return_value=[]), \
             patch("src.ingestion.embedder.get_embedder") as ge:
            ge.return_value.encode.side_effect = lambda qs: [[0.0]] * len(qs)
            multi_query_search("第4页的插图是什么？", top_k=2)
        self.assertIn("图片", captured["terms"])


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
            ge.return_value.encode.side_effect = lambda qs: [[0.0]] * len(qs)
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
            ge.return_value.encode.side_effect = lambda qs: [[0.0]] * len(qs)
            multi_query_search("原始问题", top_k=2, features=["keywords"])
            plan.assert_not_called()  # keywords 不属于规划类
            self.assertTrue(all(not c.kwargs["use_routing"] for c in tss.call_args_list))
            self.assertTrue(all(c.kwargs["terms"] for c in tss.call_args_list))

    def test_multi_query_search_default_features_keeps_current_behavior(self):
        with patch("src.retrieval.two_stage_search", return_value=[]) as tss, \
             patch("src.retrieval.plan_question", return_value={"subs": [], "step_back": None, "hyde": None}), \
             patch("src.ingestion.embedder.get_embedder") as ge:
            ge.return_value.encode.side_effect = lambda qs: [[0.0]] * len(qs)
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

    def test_keyword_hits_do_not_fake_vector_score(self):
        """关键词通道的 score 是命中词数（≥1），不是余弦：未打标的行融合后必须记 0.0。

        修复前 rrf_merge 用 score 兜底 vector_score，关键词行会带着 1.0~3.0 的
        假余弦进入 _relevance_filter，把「无精确匹配即清空」的阈值闸门永远撑开。
        """
        kw = [{"chunk_id": "k1", "text": "x", "score": 2.0}]
        merged = rrf_merge([kw], top_k=5)
        self.assertEqual(merged[0]["vector_score"], 0.0)

    def test_keyword_noise_cannot_defeat_relevance_gate(self):
        """端到端口径：无精确匹配且真实余弦不足时，关键词弱命中必须被闸门清空。"""
        results = rrf_merge([[
            {"chunk_id": "kw", "text": "只提到一个词的切片", "score": 1.0},
            {"chunk_id": "noise", "text": "完全无关的内容", "score": 1.0},
        ]], top_k=5)
        self.assertEqual(_relevance_filter(results, "民法典的继承规则是什么"), [])

    _FAKE_GROUPS = {
        "甲": ("甲", "A"), "乙": ("乙", "B"), "丙": ("丙", "C"), "丁": ("丁", "D"),
    }

    def _fake_synonym_group(self, term: str):
        return self._FAKE_GROUPS.get(term, (term,))

    def test_keyword_gate_drops_weak_hits_on_long_queries(self):
        """≥3 组查询：只覆盖一半以下概念组的弱命中行必须被门控拦下。"""
        rows = [
            {"chunk_id": "strong", "text": "同时提到甲与乙的切片", "score": 2.0},
            {"chunk_id": "weak", "text": "只提到甲的切片", "score": 1.0},
        ]
        with patch("src.retrieval.synonym_group", side_effect=self._fake_synonym_group):
            kept = _gate_keyword_rows(rows, ["甲", "乙", "丙", "丁"])
        self.assertEqual([r["chunk_id"] for r in kept], ["strong"])

    def test_keyword_gate_counts_synonym_groups_not_raw_terms(self):
        """同义词变体归并为一组：一词多变体命中不得虚增覆盖数。"""
        rows = [{"chunk_id": "one", "text": "只覆盖甲（含变体 A）", "score": 2.0}]
        with patch("src.retrieval.synonym_group", side_effect=self._fake_synonym_group):
            # 甲/A 同组、乙/B 同组 → 扁平 4 词只有 2 组 → 门控不收紧
            kept = _gate_keyword_rows(rows, ["甲", "A", "乙", "B"])
        self.assertEqual([r["chunk_id"] for r in kept], ["one"])

    def test_keyword_gate_noop_for_short_queries(self):
        """组数 ≤2 时不收紧：单一精确串救援（如「第4页」）不因门控丢失。"""
        rows = [{"chunk_id": "w", "text": "只提到甲", "score": 1.0}]
        with patch("src.retrieval.synonym_group", side_effect=self._fake_synonym_group):
            self.assertEqual(_gate_keyword_rows(rows, ["甲"]), rows)
            self.assertEqual(_gate_keyword_rows(rows, ["甲", "乙"]), rows)
            self.assertEqual(_gate_keyword_rows(rows, []), rows)

    def test_two_stage_search_gates_weak_keyword_rows(self):
        """通道级接线：弱命中行被门控清空后，融合结果只剩向量行。"""
        with patch("src.retrieval.synonym_group", side_effect=self._fake_synonym_group), \
             patch("src.retrieval.keyword_chunks", return_value=[
                 {"chunk_id": "k1", "text": "只提到甲", "score": 1.0},
             ]), \
             patch("src.retrieval.search_chunks", return_value=[
                 {"chunk_id": "v1", "text": "y", "score": 0.52},
             ]), \
             patch("src.retrieval.search_doc_index", return_value=[]):
            merged = two_stage_search([0.0], top_k=5, terms=["甲", "乙", "丙", "丁"], use_routing=True)
        self.assertEqual([r["chunk_id"] for r in merged], ["v1"])

    def test_vector_channel_rows_carry_real_cosine(self):
        """two_stage_search 出来的行：向量行带真实余弦，关键词行标 0.0。"""
        with patch("src.retrieval.keyword_chunks", return_value=[
            {"chunk_id": "k1", "text": "x", "score": 1.0},
        ]), patch("src.retrieval.search_chunks", return_value=[
            {"chunk_id": "v1", "text": "y", "score": 0.52},
        ]), patch("src.retrieval.search_doc_index", return_value=[
            {"doc_id": "d1", "score": 0.9},
        ]):
            merged = two_stage_search([0.0], top_k=5, terms=["x"], use_routing=True)
        by_id = {r["chunk_id"]: r["vector_score"] for r in merged}
        self.assertEqual(by_id["k1"], 0.0)
        self.assertEqual(by_id["v1"], 0.52)

    def test_extract_terms_filters_junk_and_single_chars(self):
        terms = extract_terms("如何安装数据库")
        self.assertIn("安装", terms)
        self.assertIn("数据库", terms)
        self.assertNotIn("如何", terms)

    def test_extract_terms_keeps_codes_and_numbers(self):
        self.assertIn("pgvector", extract_terms("pgvector 0.7 是什么"))
        self.assertNotIn("是什么", extract_terms("pgvector 0.7 是什么"))

    def test_extract_terms_strips_question_suffixes(self):
        # jieba 会把 "条是什么" 切成 ["条是", "什么"]，预处理后应只剩下 "条"
        terms = extract_terms("民法典的二百三十条是什么？")
        self.assertIn("民法典", terms)
        self.assertIn("二百三十", terms)
        self.assertNotIn("条是", terms)

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

    def test_low_route_score_uses_global_only_without_per_doc_scans(self):
        """阈值以上才做文档内检索；低分时只跑全局，避免 3 路错文档 + 全局的双倍开销。"""
        with patch("src.retrieval.search_doc_index", return_value=[{"doc_id": "d1", "score": 0.1}]), \
             patch("src.retrieval.search_chunks") as sc, \
             patch("src.retrieval.keyword_chunks", return_value=[]):
            two_stage_search([0.0], top_k=5, terms=[])
            self.assertEqual([c.kwargs.get("doc_id") for c in sc.call_args_list], [None])

    def test_confident_route_skips_global_fallback(self):
        routed = [
            {"doc_id": "d1", "score": 0.85},
            {"doc_id": "d2", "score": 0.80},
        ]
        with patch("src.retrieval.search_doc_index", return_value=routed), \
             patch("src.retrieval.search_chunks") as sc, \
             patch("src.retrieval.keyword_chunks", return_value=[]):
            two_stage_search([0.0], top_k=5, terms=[])
            self.assertEqual([c.kwargs.get("doc_id") for c in sc.call_args_list], ["d1", "d2"])

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
            ge.return_value.encode.side_effect = lambda qs: [[0.0]] * len(qs) * 3
            results = multi_query_search(
                "原始问题", top_k=2, filters={"page": 1},
                features=["routing", "keywords", "decompose", "rewrite"],
            )

        self.assertEqual(len(tss_mock.call_args_list), 4)  # 原问题 + 改写 + 两个子问题
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
            multi_query_search(
                "原始问题", top_k=2,
                features=["routing", "keywords", "decompose", "stepback", "hyde", "rewrite"],
            )
        # 原问题 + 改写 + 子问题 + 退步 + HyDE(纯向量, terms=[]) = 5 通道
        self.assertEqual(len(tss_mock.call_args_list), 5)
        self.assertEqual(tss_mock.call_args_list[4].kwargs["terms"], [])

    def test_rerank_failure_degrades_to_rrf_and_is_reported_as_skipped(self):
        """cross/colbert 依赖本地模型，缺失时不能让问答整体 500，且 trace 要说明原因。"""
        plan = {"subs": [], "step_back": None, "hyde": None}

        def fake_tss(vec, top_k, terms, filters=None, use_routing=True, stats=None):
            # two_stage_search 现契约：向量行自带真实余弦（vector_score），见 _stamp_cosine
            return [
                {"chunk_id": "a", "score": 0.9, "vector_score": 0.9},
                {"chunk_id": "b", "score": 0.8, "vector_score": 0.8},
            ]

        with patch("src.retrieval.two_stage_search", side_effect=fake_tss), \
             patch("src.retrieval.plan_question", return_value=plan), \
             patch("src.ingestion.embedder.get_embedder") as ge, \
             patch("src.rerank.rerank", side_effect=RuntimeError("cross-encoder 未下载")):
            ge.return_value.encode.side_effect = lambda qs: [[0.0]] * len(qs)
            out = multi_query_search("问题", top_k=1, features=["rerank"], debug=True)

        trace = out["trace"]
        self.assertNotIn("rerank", trace["applied"])
        reason = next(s["reason"] for s in trace["skipped"] if s["name"] == "rerank")
        self.assertIn("退回", reason)

    def test_relevance_filter_removes_noise_when_entity_missing(self):
        """知识库不含问题里的核心实体词时，不应把沾边数字（如 '230'）的噪声切片喂给 LLM。"""
        plan = {"subs": [], "step_back": None, "hyde": None}

        def fake_tss(vec, top_k, terms, filters=None, use_routing=True, stats=None):
            # 模拟向量分很低、且文本不含 "民点" 的垃圾结果
            return [
                {"chunk_id": "c1", "text": "Brock Purdy MVP odds -230", "score": 0.1},
                {"chunk_id": "c2", "text": "some other irrelevant text", "score": 0.09},
            ]

        with patch("src.retrieval.two_stage_search", side_effect=fake_tss), \
             patch("src.retrieval.plan_question", return_value=plan), \
             patch("src.ingestion.embedder.get_embedder") as ge:
            ge.return_value.encode.side_effect = lambda qs: [[0.0]] * len(qs)
            results = multi_query_search("民点发的230条是什么？", top_k=2)

        self.assertEqual(results, [])

    def test_relevance_filter_prefers_exact_term_coverage(self):
        """AND 命中全部实体词的切片应优先保留，避免只命中部分词的通用切片混进来。"""
        plan = {"subs": [], "step_back": None, "hyde": None}

        def fake_tss(vec, top_k, terms, filters=None, use_routing=True, stats=None):
            return [
                {"chunk_id": "c1", "text": "中华人民共和国民法典 物权编 第二百零五条 ...", "score": 0.6},
                {"chunk_id": "c2", "text": "中华人民共和国民法典 物权编 第二百三十条 因继承取得物权...", "score": 0.5},
            ]

        def fake_kw(terms, limit=None, filters=None):
            # 精确法条通道只命中真正的"第二百三十条"切片
            if "第二百三十条" in terms:
                return [{"chunk_id": "c2", "text": "中华人民共和国民法典 物权编 第二百三十条 因继承取得物权...", "score": 0.0}]
            return []

        with patch("src.retrieval.two_stage_search", side_effect=fake_tss), \
             patch("src.retrieval.keyword_chunks", side_effect=fake_kw), \
             patch("src.retrieval.plan_question", return_value=plan), \
             patch("src.ingestion.embedder.get_embedder") as ge:
            ge.return_value.encode.side_effect = lambda qs: [[0.0]] * len(qs)
            results = multi_query_search("民法典的二百三十条是什么？", top_k=2)

        self.assertEqual([r["chunk_id"] for r in results], ["c2"])

    def test_extract_article_terms_captures_full_article_string(self):
        """'第二百三十条' 必须作为带边界的整体提取，而不是被切散成 '二百三十' 或误截出 '第百三十条'。"""
        self.assertEqual(_extract_article_terms("民法典的二百三十条是什么？"), ["第二百三十条"])
        self.assertEqual(_extract_article_terms("民法典第二百三十条"), ["第二百三十条"])
        self.assertNotIn("第百三十条", _extract_article_terms("民法典第二百三十条"))
        self.assertEqual(_extract_article_terms("刑法第230条如何适用"), ["第230条"])
        self.assertEqual(_extract_article_terms("RAG 是什么"), [])

    def test_relevance_filter_excludes_wrong_article_with_same_digits(self):
        """'第二百三十条' 不应被 '第一千二百三十条' 同数字串污染：精确法条通道只命中真正的 230 条。"""
        plan = {"subs": [], "step_back": None, "hyde": None}

        def fake_tss(vec, top_k, terms, filters=None, use_routing=True, stats=None):
            return [
                {"chunk_id": "c2276", "text": "中华人民共和国民法典 物权编 第一千二百三十条 因污染环境...", "score": 0.55},
                {"chunk_id": "c21", "text": "中华人民共和国民法典 物权编 第二百三十条 因继承取得物权...", "score": 0.5},
            ]

        def fake_kw(terms, limit=None, filters=None):
            # 精确法条通道只命中真正的"第二百三十条"切片，不含"第一千二百三十条"
            if "第二百三十条" in terms:
                return [{"chunk_id": "c21", "text": "中华人民共和国民法典 物权编 第二百三十条 因继承取得物权...", "score": 0.0}]
            return []

        with patch("src.retrieval.two_stage_search", side_effect=fake_tss), \
             patch("src.retrieval.keyword_chunks", side_effect=fake_kw), \
             patch("src.retrieval.plan_question", return_value=plan), \
             patch("src.ingestion.embedder.get_embedder") as ge:
            ge.return_value.encode.side_effect = lambda qs: [[0.0]] * len(qs)
            results = multi_query_search("民法典的二百三十条是什么？", top_k=2)

        self.assertEqual([r["chunk_id"] for r in results], ["c21"])

    def test_relevance_filter_direct_unit_article_precision(self):
        """直接单测 _relevance_filter：第 2 档（仅法条编号命中）应排除同数字串错误法条。"""
        results = [
            {"chunk_id": "c2276", "text": "第一千二百三十条 因污染环境...", "vector_score": 0.55},
            {"chunk_id": "c21", "text": "第二百三十条 因继承取得物权...", "vector_score": 0.5},
        ]
        out = _relevance_filter(results, "民法典的二百三十条是什么？")
        self.assertEqual([r["chunk_id"] for r in out], ["c21"])

    def test_relevance_filter_direct_unit_entity_only_fallback(self):
        """没有法条编号时，退回第 3 档实体词 AND 覆盖；低于向量阈值则清空。"""
        results = [
            {"chunk_id": "a", "text": "体育赔率 -230 的盘口分析", "vector_score": 0.41},
            {"chunk_id": "b", "text": "无关内容", "vector_score": 0.40},
        ]
        # 知识库不含 '民点' 实体 → AND 无全命中且向量分 < 0.45 → 清空
        self.assertEqual(_relevance_filter(results, "民点发的230条是什么？"), [])

    def test_multi_query_search_empty_plan_is_single_channel(self):
        with patch("src.retrieval.two_stage_search", return_value=[]) as tss_mock, \
             patch("src.retrieval.plan_question", return_value={"subs": [], "step_back": None, "hyde": None}), \
             patch("src.ingestion.embedder.get_embedder") as ge:
            ge.return_value.encode.side_effect = lambda qs: [[0.0]] * len(qs)
            # 门控：LLM 判定不需要分解/退步/HyDE，且 rewrite 默认关闭 → 仅原问题单通道
            multi_query_search("简单问题", top_k=2)
            with patch("src.retrieval.two_stage_search", return_value=[]) as tss_kw:
                multi_query_search("简单问题", top_k=2, features=list(_DEFAULT_FEATURES) + ["rewrite"])
        self.assertEqual(len(tss_mock.call_args_list), 1)
        # 显式开启 rewrite 时，确定性改写把"简单问题"归一为"简单 问题"并作为额外通道并入
        self.assertEqual(len(tss_kw.call_args_list), 2)

    def test_rewrite_query_normalizes_question(self):
        """确定性改写：去后缀、归一法条、拼实体词；无实体时原样返回。"""
        self.assertEqual(rewrite_query("民法典的二百三十条是什么？"), "民法典 二百三十 第二百三十条")
        self.assertEqual(rewrite_query("民法典第二百三十条"), "民法典 二百三十 第二百三十条")
        self.assertEqual(rewrite_query("RAG 是什么"), "RAG")  # 去「是什么」后缀，无实体可补
        self.assertEqual(rewrite_query("你好"), "你好")        # 无实体/法条，原样

    def test_multi_query_search_rewrite_disabled_yields_single_channel(self):
        """features 不含 rewrite 时，确定性改写不生效，仅原问题单通道。"""
        with patch("src.retrieval.two_stage_search", return_value=[]) as tss, \
             patch("src.retrieval.plan_question", return_value={"subs": [], "step_back": None, "hyde": None}), \
             patch("src.ingestion.embedder.get_embedder") as ge:
            ge.return_value.encode.side_effect = lambda qs: [[0.0]] * len(qs)
            multi_query_search("民法典的二百三十条是什么？", top_k=2, features=["routing", "keywords"])
        self.assertEqual(len(tss.call_args_list), 1)

    def test_multi_query_search_rewrite_adds_channel_and_surfaces_in_trace(self):
        """显式开启 rewrite：可改写查询会多一路通道，并在 debug trace 的 plan.rewritten 暴露。"""
        with patch("src.retrieval.two_stage_search", return_value=[]), \
             patch("src.retrieval.keyword_chunks", return_value=[]), \
             patch("src.retrieval.plan_question", return_value={"subs": [], "step_back": None, "hyde": None}), \
             patch("src.ingestion.embedder.get_embedder") as ge:
            ge.return_value.encode.side_effect = lambda qs: [[0.0]] * len(qs)
            out = multi_query_search(
                "民法典的二百三十条是什么？", top_k=2, debug=True,
                features=["routing", "keywords", "rewrite"],
            )
        self.assertIsNotNone(out["trace"]["plan"]["rewritten"])
        self.assertIn("第二百三十条", out["trace"]["plan"]["rewritten"])
        self.assertIn("rewrite", out["trace"]["applied"])

    def test_rewrite_not_in_default_features(self):
        """回归：rewrite 默认关闭（n=63 消融上三个子集 ΔMRR 全为负，见评测报告第九节）。"""
        self.assertNotIn("rewrite", _DEFAULT_FEATURES)
        self.assertIn("rewrite", ALL_FEATURES)  # 仍可显式开启

    def test_hyde_embedding_shares_encode_batch_with_queries(self):
        """HyDE 向量与问题向量一次 encode，避免多一次模型前向。"""
        plan = {"subs": [], "step_back": None, "hyde": "假想文档段落，足够长能通过长度校验"}
        captured: list[list[str]] = []

        def fake_encode(qs):
            captured.append(list(qs))
            return [[0.0]] * len(qs)

        with patch("src.retrieval.two_stage_search", return_value=[]), \
             patch("src.retrieval.plan_question", return_value=plan), \
             patch("src.ingestion.embedder.get_embedder") as ge:
            ge.return_value.encode.side_effect = fake_encode
            multi_query_search("原始问题", top_k=2, features=["hyde"])
        self.assertEqual(len(captured), 1)
        self.assertEqual(len(captured[0]), 2)

    def test_graph_channel_is_invoked_with_primary_vector(self):
        # 图谱行与现实一致：带正文文本（锚点实体所在切片），无 vector_score（非余弦信号）
        graph_row = {"chunk_id": "g", "score": 0.9, "text": "问题涉及的核心实体内容"}
        with patch("src.retrieval.two_stage_search", return_value=[]), \
             patch("src.graph.graph_channel", return_value=[graph_row]) as gc, \
             patch("src.ingestion.embedder.get_embedder") as ge:
            ge.return_value.encode.side_effect = lambda qs: [[0.1, 0.2]] * len(qs)
            out = multi_query_search("问题", top_k=2, features=["graph"])
        gc.assert_called_once()
        self.assertEqual(gc.call_args[0][0], [0.1, 0.2])
        self.assertEqual([r["chunk_id"] for r in out], ["g"])


if __name__ == "__main__":
    unittest.main()
