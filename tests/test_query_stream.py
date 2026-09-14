"""流式问答：generate_stream 拼 token；_run_query 经 emit 推送阶段/token/done。"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.api.routes import _run_query
from src.api.schemas import QueryRequest
from src.llm.client import LLMClient
from src.storage.database import _CHUNK_INSERT_BATCH


class GenerateStreamTests(unittest.TestCase):
    def test_yields_delta_tokens(self):
        chunks = [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="你"))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="好"))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))]),
        ]
        client = MagicMock()
        client.chat.completions.create.return_value = iter(chunks)
        llm = LLMClient(client=client, api_key="k")
        self.assertEqual("".join(llm.generate_stream("问", [{"doc_name": "d", "chunk_index": 0, "text": "t"}])), "你好")
        self.assertTrue(client.chat.completions.create.call_args.kwargs["stream"])


class QueryEmitTests(unittest.TestCase):
    def test_emit_receives_retrieve_generate_token_done(self):
        events: list[tuple[str, dict]] = []

        def emit(event, payload):
            events.append((event, payload))

        llm = MagicMock()
        llm.generate_stream.return_value = iter(["答", "案"])
        req = QueryRequest(question="问题")
        with patch("src.api.routes.database_stats", return_value={"total_chunks": 10}), \
             patch("src.api.routes.get_messages", return_value=[]), \
             patch("src.api.routes.save_message", return_value=None), \
             patch("src.api.routes.get_llm", return_value=llm), \
             patch("src.api.routes.multi_query_search", return_value=[{
                 "doc_name": "d.pdf", "chunk_index": 0, "text": "t", "score": 0.9, "metadata": {},
             }]):
            resp = _run_query(req, emit=emit)
        self.assertEqual(resp.answer, "答案")
        stages = [p.get("stage") for e, p in events if e == "stage"]
        self.assertIn("retrieve", stages)
        self.assertIn("generate", stages)
        self.assertEqual([p.get("text") for e, p in events if e == "token"], ["答", "案"])
        self.assertEqual(events[-1][0], "done")

    def test_chunk_insert_batch_stays_under_pg_param_limit(self):
        self.assertGreaterEqual(_CHUNK_INSERT_BATCH, 1)
        self.assertLessEqual(_CHUNK_INSERT_BATCH * 7, 65535)


if __name__ == "__main__":
    unittest.main()
