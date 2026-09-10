import unittest

from unittest.mock import patch

from src.rerank import rerank


def cand(i):
    return {"chunk_id": f"c-{i}", "doc_name": "d.pdf", "chunk_index": i, "text": f"text {i}", "score": 0.1 * (i + 1)}


class RerankTests(unittest.TestCase):
    def test_cross_strategy_orders_by_model_score(self):
        class _FakeModel:
            def predict(self, pairs):
                return [0.1, 0.9, 0.5]
        with patch.dict("os.environ", {"RERANK_STRATEGY": "cross"}), \
             patch("src.rerank.get_reranker", return_value=_FakeModel()):
            out = rerank("q", [cand(0), cand(1), cand(2)], 2)
        self.assertEqual([r["chunk_index"] for r in out], [1, 2])
        self.assertEqual(out[0]["rerank_score"], 0.9)

    def test_llm_strategy_maps_scores_by_chunk_id(self):
        class _LLM:
            enabled = True
            model = "fake"
            def _get_client(self):
                import types
                message = types.SimpleNamespace(content='{"c-2": 9, "c-0": 1}')
                return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(
                    create=lambda **kw: types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)]))))
        with patch.dict("os.environ", {"RERANK_STRATEGY": "llm"}), \
             patch("src.llm.client.get_llm", return_value=_LLM()):
            out = rerank("q", [cand(0), cand(1), cand(2)], 3)
        # c-2 得 9 分排第一；c-1 无打分回落 rrf score
        self.assertEqual(out[0]["chunk_id"], "c-2")

    def test_unknown_strategy_raises(self):
        with patch.dict("os.environ", {"RERANK_STRATEGY": "xgboost"}):
            with self.assertRaises(ValueError):
                rerank("q", [cand(0)], 1)

    def test_rerank_empty_candidates(self):
        self.assertEqual(rerank("q", [], 5), [])

    def test_colbert_missing_model_gives_clear_error(self):
        import src.rerank as R
        with patch.dict("os.environ", {"RERANK_STRATEGY": "colbert"}), \
             patch.object(R, "_colbert", None, create=True):
            R._colbert = None
            R._COLBERT_MODEL = "/nonexistent/colbert"
            with self.assertRaises(FileNotFoundError):
                rerank("q", [cand(0)], 1)
            R._COLBERT_MODEL = "models/colbert"

    def test_default_strategy_is_rrf(self):
        with patch.dict("os.environ", {"RERANK_STRATEGY": "rrf"}):
            out = rerank("q", [cand(0), cand(1)], 2)  # rrf：score 0.2 > 0.1
        self.assertEqual(out[0]["chunk_id"], "c-1")


if __name__ == "__main__":
    unittest.main()
