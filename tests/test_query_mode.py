"""mode 分流的行为保证：pipeline 零回归、agent 成功不重跑、agent 失败静默降级。"""
import contextlib
import unittest

from unittest.mock import MagicMock, patch

from src.api.routes import _query_sync as query
from src.api.routes import _run_agent_or_none
from src.api.schemas import QueryRequest


def chunk(chunk_id="a", score=0.9):
    return {
        "chunk_id": chunk_id,
        "document_id": "doc-1",
        "doc_name": "d.pdf",
        "chunk_index": 0,
        "text": "text",
        "score": score,
        "metadata": {},
    }


class QueryModeTests(unittest.TestCase):
    def test_features_cap_matches_feature_name_count(self):
        """全选 8 个特性不应被 422 拒掉：features 上限必须与 FeatureName 选项数同步。

        回归背景：新增 rewrite 后选项变 8 个，max_length 仍写 7，前端全选触发 HTTP 422。
        """
        from src.retrieval import ALL_FEATURES

        all_features = sorted(ALL_FEATURES)
        req = QueryRequest(question="问题", features=all_features)  # 不抛 = 通过校验
        self.assertEqual(sorted(req.features), all_features)
        # 常量上限与选项数严格一致，防止下次加特性再脱节
        self.assertEqual(len(all_features), 8)

    def _env(self, mqs_return, agent_return):
        """把 /api/query 的外部依赖全部打桩，只观察分流行为。"""
        return [
            patch("src.api.routes.database_stats", return_value={"total_chunks": 10}),
            patch("src.api.routes.get_messages", return_value=[]),
            patch("src.api.routes.save_message", return_value=None),
            patch("src.api.routes.get_llm", return_value=MagicMock(generate=lambda *a, **k: "答案")),
            patch("src.api.routes.multi_query_search", return_value=mqs_return) ,
            patch("src.api.routes._run_agent_or_none", return_value=agent_return),
        ]

    def test_pipeline_mode_never_calls_agent(self):
        with contextlib.ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in self._env([chunk()], {"results": [chunk("z")], "trace": {}})]
            mqs, agent = mocks[4], mocks[5]
            resp = query(QueryRequest(question="问题"))
        agent.assert_not_called()
        mqs.assert_called_once()
        self.assertEqual([s.doc_name for s in resp.sources], ["d.pdf"])

    def test_agent_success_does_not_rerun_pipeline(self):
        trace = {"steps": [{"step": 1, "tool": "search_knowledge", "args": {"query": "q"}}],
                 "termination": "answered", "budget": {}, "evidence_chunks": 1, "tools": []}
        req = QueryRequest(question="问题", mode="agent", debug=True)
        with contextlib.ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in self._env([chunk()], {"results": [chunk("z")], "trace": trace})]
            mqs, agent = mocks[4], mocks[5]
            resp = query(req)
        agent.assert_called_once()
        mqs.assert_not_called()
        self.assertIsNotNone(resp.trace.agent)
        self.assertEqual(resp.trace.agent.termination, "answered")
        self.assertIsNone(resp.trace.agent_degraded_reason)  # 成功时不该有降级原因

    def test_agent_failure_falls_back_to_pipeline_silently(self):
        """agent 返回 None（不可用/无证据/异常）→ 静默退回单轮，响应形态不变。"""
        req = QueryRequest(question="问题", mode="agent")
        with contextlib.ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in self._env([chunk()], None)]
            mqs, agent = mocks[4], mocks[5]
            resp = query(req)
        agent.assert_called_once()
        mqs.assert_called_once()  # 退回了单轮
        self.assertEqual(len(resp.sources), 1)

    def test_agent_degrade_reason_is_surfaced_in_trace(self):
        """降级原因要透传到 trace，界面才能说清「为什么没走 Agent」。"""
        req = QueryRequest(question="问题", mode="agent", debug=True)

        def fake_agent(request, on_step=None, degrade=None):
            if degrade is not None:
                degrade["reason"] = "Agent 调用大模型失败：429 Too Many Requests"
            return None

        patches = [
            patch("src.api.routes.database_stats", return_value={"total_chunks": 10}),
            patch("src.api.routes.get_messages", return_value=[]),
            patch("src.api.routes.save_message", return_value=None),
            patch("src.api.routes.get_llm", return_value=MagicMock(generate=lambda *a, **k: "答案")),
            patch("src.api.routes.multi_query_search", return_value=[chunk()]),
            patch("src.api.routes._run_agent_or_none", side_effect=fake_agent),
        ]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            resp = query(req)
        self.assertIsNone(resp.trace.agent)
        self.assertEqual(resp.trace.agent_degraded_reason, "Agent 调用大模型失败：429 Too Many Requests")

    def test_run_agent_exception_is_reported_in_degrade_sink(self):
        """run_agent 抛异常时也不能吞掉原因：_run_agent_or_none 要写进 degrade。"""
        req = QueryRequest(question="问题", mode="agent")
        degrade: dict = {}
        with patch("src.agent.run_agent", side_effect=RuntimeError("boom")):
            out = _run_agent_or_none(req, degrade=degrade)
        self.assertIsNone(out)
        self.assertIn("boom", degrade["reason"])

    def test_pipeline_trace_has_no_agent_field(self):
        req = QueryRequest(question="问题", debug=True)
        with contextlib.ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in
                     self._env({"results": [chunk()], "trace": {"timings": {}}}, None)]
            resp = query(req)
        self.assertIsNone(resp.trace.agent)


if __name__ == "__main__":
    unittest.main()
