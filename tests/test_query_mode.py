"""mode 分流的行为保证：pipeline 零回归、agent 成功不重跑、agent 失败静默降级。"""
import contextlib
import unittest

from unittest.mock import MagicMock, patch

from src.api.routes import query
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

    def test_pipeline_trace_has_no_agent_field(self):
        req = QueryRequest(question="问题", debug=True)
        with contextlib.ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in
                     self._env({"results": [chunk()], "trace": {"timings": {}}}, None)]
            resp = query(req)
        self.assertIsNone(resp.trace.agent)


if __name__ == "__main__":
    unittest.main()
