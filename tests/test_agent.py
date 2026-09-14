import contextlib
import unittest

from unittest.mock import patch

from src.agent import _active_tools, run_agent
from src.llm.client import LLMClient


def row(chunk_id: str, score: float = 0.5, doc: str = "d.pdf", index: int = 0):
    return {
        "chunk_id": chunk_id,
        "document_id": "doc-1",
        "doc_name": doc,
        "chunk_index": index,
        "text": f"text of {chunk_id}",
        "score": score,
        "metadata": {},
    }


class FakeLLM:
    """按序吐出预设动作；动作用完即 answer。"""

    def __init__(self, actions=None, enabled=True, raise_at=None):
        self.enabled = enabled
        self._actions = list(actions or [])
        self.raise_at = raise_at
        self.calls = 0
        self.prompts = []

    def chat_with_tools(self, messages, tools, temperature=0):
        self.calls += 1
        self.prompts.append(messages)
        if self.raise_at is not None and self.calls >= self.raise_at:
            raise RuntimeError("LLM 网关超时")
        if not self._actions:
            return {"thought": "", "tool": "answer", "args": {}}
        return self._actions.pop(0)

    def generate(self, question, sources, history=None):
        return "generated"


class FakeEmbedder:
    def encode(self, texts):
        return [[0.1] for _ in texts]


def _patches(llm, tss=None, graph=None):
    """统一的 mock 组合：LLM + embedder + 两个检索工具。"""
    patches = [
        patch("src.llm.client.get_llm", return_value=llm),
        patch("src.ingestion.embedder.get_embedder", return_value=FakeEmbedder()),
        patch("src.retrieval.extract_terms", return_value=[]),
        patch("src.retrieval.two_stage_search", side_effect=tss if tss else (lambda *a, **k: [])),
        patch("src.graph.graph_channel", side_effect=graph if graph else (lambda *a, **k: [])),
    ]
    return patches


class RunAgentTests(unittest.TestCase):
    def test_returns_none_when_llm_disabled(self):
        # 必须显式 mock：否则会依赖「环境是否配了 LLM_API_KEY」，
        # 配了的话这里会真的打一次 LLM + 查库（既慢又让测试失去意义）
        with patch("src.llm.client.get_llm", return_value=FakeLLM(enabled=False)):
            out = run_agent("问题", top_k=3)
        self.assertIsNone(out)

    def test_returns_none_when_agent_answers_without_evidence(self):
        """模型一上来就 answer：没有证据可交，返回 None 让调用方走单轮。"""
        llm = FakeLLM(actions=[])
        with patch("src.llm.client.get_llm", return_value=llm):
            self.assertIsNone(run_agent("问题"))

    def test_search_then_answer_returns_results_and_trace(self):
        llm = FakeLLM(actions=[{"thought": "先查", "tool": "search_knowledge", "args": {"query": "q1"}}])
        patches = _patches(llm, tss=lambda *a, **k: [row("a", 0.9), row("b", 0.8)])
        with _enter(patches):
            out = run_agent("问题", top_k=5)
        self.assertIsNotNone(out)
        self.assertEqual([r["chunk_id"] for r in out["results"]], ["a", "b"])
        self.assertEqual(out["trace"]["termination"], "answered")
        self.assertEqual(len(out["trace"]["steps"]), 2)  # 1 次检索 + 1 次 answer
        self.assertEqual(out["trace"]["steps"][0]["tool"], "search_knowledge")
        self.assertEqual(out["trace"]["steps"][0]["new_chunks"], 2)
        self.assertEqual(out["trace"]["evidence_chunks"], 2)

    def test_on_step_fires_after_each_recorded_step(self):
        llm = FakeLLM(actions=[{"thought": "先查", "tool": "search_knowledge", "args": {"query": "q1"}}])
        seen: list[str] = []
        patches = _patches(llm, tss=lambda *a, **k: [row("a", 0.9)])
        with _enter(patches):
            run_agent("问题", top_k=3, on_step=lambda rec: seen.append(rec["tool"]))
        self.assertEqual(seen, ["search_knowledge", "answer"])

    def test_tool_error_does_not_abort_loop(self):
        """工具报错只记一步 error，循环继续（失败静默降级，但不整体失败）。"""
        llm = FakeLLM(actions=[
            {"thought": "", "tool": "search_knowledge", "args": {"query": "q1"}},
            {"thought": "", "tool": "search_knowledge", "args": {"query": "q2"}},
        ])
        patches = _patches(llm, tss=[RuntimeError("向量库超时"), [row("a", 0.7)]])
        with _enter(patches):
            out = run_agent("问题")
        self.assertIsNotNone(out)
        self.assertEqual(out["trace"]["termination"], "answered")
        self.assertEqual(out["trace"]["steps"][0]["error"], "向量库超时")
        self.assertIsNone(out["trace"]["steps"][1]["error"])

    def test_stagnant_terminates_early(self):
        """连续两步没有新增证据 → 判定边际收益为 0，强制收敛。"""
        llm = FakeLLM(actions=[
            {"thought": "", "tool": "search_knowledge", "args": {"query": f"q{i}"}} for i in range(5)
        ])
        # 第一步拿到 1 块，之后都是空 → 第 3 步后 stagnant=2 触发
        patches = _patches(llm, tss=[[row("a", 0.9)], [], []])
        with _enter(patches):
            out = run_agent("问题", max_steps=6)
        self.assertEqual(out["trace"]["termination"], "stagnant")
        self.assertEqual(len(out["trace"]["steps"]), 3)

    def test_budget_exhausted_terminates(self):
        llm = FakeLLM(actions=[
            {"thought": "", "tool": "search_knowledge", "args": {"query": f"q{i}"}} for i in range(6)
        ])
        patches = _patches(llm, tss=lambda *a, **k: [row("a", 0.9), row("b", 0.8)])
        with _enter(patches):
            out = run_agent("问题", max_steps=6, max_llm_calls=2)
        self.assertEqual(out["trace"]["termination"], "budget")
        self.assertEqual(llm.calls, 2)

    def test_max_steps_reached_terminates(self):
        llm = FakeLLM(actions=[
            {"thought": "", "tool": "search_knowledge", "args": {"query": f"q{i}"}} for i in range(5)
        ])
        seen = {"n": 0}

        def tss(*a, **k):
            seen["n"] += 1
            return [row(f"c{seen['n']}", 0.9)]  # 每步都是新块，不触发 stagnant

        with _enter(_patches(llm, tss=tss)):
            out = run_agent("问题", max_steps=3)
        self.assertEqual(out["trace"]["termination"], "max_steps")
        self.assertEqual(len(out["trace"]["steps"]), 3)

    def test_llm_exception_converges_with_existing_evidence(self):
        """LLM 中途挂掉：不整体失败，用已收集的证据收敛。"""
        llm = FakeLLM(actions=[{"thought": "", "tool": "search_knowledge", "args": {"query": "q1"}}], raise_at=2)
        patches = _patches(llm, tss=lambda *a, **k: [row("a", 0.9)])
        with _enter(patches):
            out = run_agent("问题", max_steps=6)
        self.assertIsNotNone(out)
        self.assertEqual(out["trace"]["termination"], "error")
        self.assertEqual([r["chunk_id"] for r in out["results"]], ["a"])

    def test_evidence_is_deduped_keeping_highest_score(self):
        llm = FakeLLM(actions=[
            {"thought": "", "tool": "search_knowledge", "args": {"query": "q1"}},
            {"thought": "", "tool": "search_knowledge", "args": {"query": "q2"}},
        ])
        patches = _patches(llm, tss=[[row("a", 0.4)], [row("a", 0.9), row("b", 0.5)]])
        with _enter(patches):
            out = run_agent("问题")
        # 第二次不再新增 a，但要把最高分带回去
        self.assertEqual(out["trace"]["steps"][1]["new_chunks"], 1)
        by_id = {r["chunk_id"]: r["score"] for r in out["results"]}
        self.assertEqual(by_id["a"], 0.9)
        self.assertEqual(out["trace"]["evidence_chunks"], 2)

    def test_observation_is_fed_back_into_next_prompt(self):
        """反思-改写闭环：上一步的观测必须出现在下一步的 prompt 里。"""
        llm = FakeLLM(actions=[
            {"thought": "换个角度", "tool": "search_knowledge", "args": {"query": "q1"}},
            {"thought": "", "tool": "search_knowledge", "args": {"query": "q2"}},
        ])
        patches = _patches(llm, tss=lambda *a, **k: [row("a", 0.9)])
        with _enter(patches):
            run_agent("问题")
        second_prompt = llm.prompts[1][-1]["content"]
        self.assertIn("Steps taken", second_prompt)
        self.assertIn("q1", second_prompt)
        self.assertIn("text of a", second_prompt)  # 观测摘要回灌

    def test_graph_tool_mounted_by_default(self):
        llm = FakeLLM(actions=[{"thought": "", "tool": "search_graph", "args": {"query": "q1"}}])
        patches = _patches(llm, graph=lambda *a, **k: [row("g1", 0.9)])
        with _enter(patches):
            out = run_agent("问题")
        self.assertIn("search_graph", out["trace"]["tools"])
        self.assertEqual(out["trace"]["steps"][0]["tool"], "search_graph")

    def test_graph_tool_excluded_when_features_omit_graph(self):
        """agent 模式下 features 语义为「工具子集」：不含 graph 就不挂载、也绝不执行图谱工具。"""
        self.assertEqual(_active_tools(["keywords"]), ["search_knowledge", "answer"])
        self.assertEqual(_active_tools(None), ["search_knowledge", "search_graph", "answer"])

        llm = FakeLLM(actions=[{"thought": "", "tool": "search_graph", "args": {"query": "q1"}}])
        patches = _patches(llm, graph=lambda *a, **k: [row("g1", 0.9)])
        with _enter(patches):
            out = run_agent("问题", features=["keywords"])
        # 未挂载 → 模型选了它也不会被执行 → 按终止处理 → 无证据 → 返回 None 降级
        self.assertIsNone(out)

    def test_unknown_tool_is_treated_as_answer(self):
        llm = FakeLLM(actions=[{"thought": "", "tool": "search_knowledge", "args": {"query": "q1"}},
                               {"thought": "", "tool": "not_a_tool", "args": {}}])
        patches = _patches(llm, tss=lambda *a, **k: [row("a", 0.9)])
        with _enter(patches):
            out = run_agent("问题")
        self.assertEqual(out["trace"]["termination"], "answered")

    def test_rerank_reorders_final_evidence_when_feature_enabled(self):
        """features 含 rerank：整个循环结束后对累积证据池做一次终排，trace 记录策略。"""
        llm = FakeLLM(actions=[{"thought": "", "tool": "search_knowledge", "args": {"query": "q1"}}])
        patches = _patches(llm, tss=lambda *a, **k: [row("a", 0.9), row("b", 0.8)])

        def fake_rerank(query, candidates, top_k, strategy=None):
            self.assertEqual(strategy, "cross")
            return [row("b", 0.8), row("a", 0.9)][:top_k]

        with _enter(patches + [patch("src.rerank.rerank", side_effect=fake_rerank)]):
            out = run_agent("问题", top_k=2, features=["rerank"], rerank_strategy="cross")
        self.assertIsNotNone(out)
        self.assertEqual([r["chunk_id"] for r in out["results"]], ["b", "a"])  # 重排序生效
        self.assertEqual(out["trace"]["rerank"], "cross")

    def test_rerank_skipped_when_feature_absent(self):
        """features 不含 rerank（含 None）时不重排，与管线 None=默认集（无 rerank）语义一致。"""
        llm = FakeLLM(actions=[{"thought": "", "tool": "search_knowledge", "args": {"query": "q1"}}])
        patches = _patches(llm, tss=lambda *a, **k: [row("a", 0.9)])
        with _enter(patches):
            out = run_agent("问题", top_k=1)
        self.assertIsNone(out["trace"].get("rerank"))
        self.assertEqual([r["chunk_id"] for r in out["results"]], ["a"])

    def test_rerank_failure_degrades_to_rrf_order(self):
        """重排模型缺失等失败不致命：退回 RRF 序，trace.rerank 为 None。"""
        llm = FakeLLM(actions=[{"thought": "", "tool": "search_knowledge", "args": {"query": "q1"}}])
        patches = _patches(llm, tss=lambda *a, **k: [row("a", 0.9), row("b", 0.8)])
        with _enter(patches + [patch("src.rerank.rerank", side_effect=RuntimeError("cross-encoder 未下载"))]):
            out = run_agent("问题", top_k=2, features=["rerank"])
        self.assertEqual([r["chunk_id"] for r in out["results"]], ["a", "b"])
        self.assertIsNone(out["trace"]["rerank"])

    def test_search_knowledge_shares_pipeline_basic_devices(self):
        """search_knowledge 与管线共用基础装置：改写查询 + 法条精确注入 + 相关性过滤。"""
        llm = FakeLLM(actions=[{"thought": "", "tool": "search_knowledge",
                                "args": {"query": "民法典的二百三十条是什么？"}}])
        captured: dict = {}

        def fake_terms(question, max_terms=12):
            return ["二百三十"] if "二百三十" in question else []

        def fake_tss(vector, top_k, terms, filters=None, use_routing=True, stats=None):
            captured["terms"] = terms
            return [{"chunk_id": "a", "text": "民法典 第二百三十条 因继承取得物权", "score": 0.9}]

        patches = [
            patch("src.llm.client.get_llm", return_value=llm),
            patch("src.ingestion.embedder.get_embedder", return_value=FakeEmbedder()),
            patch("src.retrieval.extract_terms", side_effect=fake_terms),
            patch("src.retrieval.two_stage_search", side_effect=fake_tss),
            patch("src.retrieval.keyword_chunks",
                  return_value=[{"chunk_id": "k", "text": "民法典 第二百三十条 因继承取得物权", "score": 0.0}]),
        ]
        with _enter(patches):
            out = run_agent("问题", top_k=5)
        self.assertIsNotNone(out)
        # 改写后的查询喂给了检索（去后缀 + 归一法条），而不是原始口语问句
        self.assertEqual(captured["terms"], ["二百三十"])
        # 法条精确通道把真法条切片补进了候选集
        self.assertEqual([r["chunk_id"] for r in out["results"]], ["a", "k"])
        self.assertEqual(out["trace"]["steps"][0]["new_chunks"], 2)


class ChatWithToolsTests(unittest.TestCase):
    def _client_with(self, message):
        client = LLMClient(api_key="k")
        response = unittest.mock.MagicMock()
        response.choices = [unittest.mock.MagicMock()]
        response.choices[0].message = message
        client._client = unittest.mock.MagicMock()
        client._client.chat.completions.create.return_value = response
        return client

    def test_no_tool_call_is_treated_as_answer(self):
        msg = unittest.mock.MagicMock()
        msg.tool_calls = None
        msg.content = "证据够了"
        out = self._client_with(msg).chat_with_tools([{"role": "user", "content": "hi"}], [])
        self.assertEqual(out, {"thought": "证据够了", "tool": "answer", "args": {}})

    def test_parses_first_tool_call_arguments(self):
        fn = unittest.mock.MagicMock()
        fn.name = "search_knowledge"
        fn.arguments = '{"query": "ReCite 的 CiteLocator"}'
        msg = unittest.mock.MagicMock()
        msg.tool_calls = [unittest.mock.MagicMock()]
        msg.tool_calls[0].function = fn
        msg.content = "先查一下"
        out = self._client_with(msg).chat_with_tools([{"role": "user", "content": "hi"}], [])
        self.assertEqual(out["tool"], "search_knowledge")
        self.assertEqual(out["args"], {"query": "ReCite 的 CiteLocator"})
        self.assertEqual(out["thought"], "先查一下")

    def test_malformed_arguments_fall_back_to_empty(self):
        fn = unittest.mock.MagicMock()
        fn.name = "search_knowledge"
        fn.arguments = "not json"
        msg = unittest.mock.MagicMock()
        msg.tool_calls = [unittest.mock.MagicMock()]
        msg.tool_calls[0].function = fn
        msg.content = ""
        out = self._client_with(msg).chat_with_tools([{"role": "user", "content": "hi"}], [])
        self.assertEqual(out["args"], {})


def _enter(patches):
    """把一组 patch 串成一个上下文管理器。"""
    stack = contextlib.ExitStack()
    for p in patches:
        stack.enter_context(p)
    return stack


if __name__ == "__main__":
    unittest.main()
