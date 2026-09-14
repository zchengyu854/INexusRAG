import unittest
from unittest.mock import patch

from src.evaluation import (
    _normalize_runner_out,
    agent_runner,
    retrieval_metrics,
    run_ablation,
)


def r(doc, idx):
    return {"chunk_id": f"{doc}-{idx}", "doc_name": doc, "chunk_index": idx, "text": "t"}


class RetrievalMetricsTests(unittest.TestCase):
    def test_hit_and_mrr_at_first_rank(self):
        results = [r("a.pdf", 0), r("a.pdf", 1), r("a.pdf", 2)]
        m = retrieval_metrics(results, {"a.pdf:2"}, 3)
        self.assertTrue(m["hit"])
        self.assertAlmostEqual(m["mrr"], 1 / 3)

    def test_miss_outside_k_is_no_hit(self):
        results = [r("a.pdf", i) for i in range(10)]
        m = retrieval_metrics(results, {"a.pdf:9"}, 3)
        self.assertFalse(m["hit"])
        self.assertEqual(m["mrr"], 0.0)

    def test_first_hit_wins_mrr(self):
        results = [r("a.pdf", 5), r("a.pdf", 1), r("a.pdf", 9)]
        m = retrieval_metrics(results, {"a.pdf:1", "a.pdf:9"}, 3)
        self.assertAlmostEqual(m["mrr"], 1 / 2)  # 第一次命中在 rank 2


class AblationRunnerTests(unittest.TestCase):
    def test_normalize_list_and_cost_dict(self):
        results, cost = _normalize_runner_out([r("a.pdf", 0)])
        self.assertEqual(len(results), 1)
        self.assertIsNone(cost)
        results, cost = _normalize_runner_out({"results": [r("a.pdf", 1)], "cost": {"steps": 2}})
        self.assertEqual(results[0]["chunk_index"], 1)
        self.assertEqual(cost["steps"], 2)

    def test_run_ablation_accepts_custom_runner_with_cost(self):
        cases = [{"question": "q", "expected": {"a.pdf:0"}}]

        def runner(question, top_k, features):
            return {
                "results": [r("a.pdf", 0)],
                "cost": {"steps": 3, "llm_calls": 2, "latency_ms": 100.0},
            }

        with patch("src.evaluation.load_cases", return_value=cases):
            rows = run_ablation([("agent", None, runner)], top_k=5)
        self.assertEqual(rows[0]["hit@k"], 1.0)
        self.assertEqual(rows[0]["avg_steps"], 3)
        self.assertEqual(rows[0]["avg_llm_calls"], 2)
        self.assertEqual(rows[0]["avg_latency_ms"], 100.0)

    def test_agent_runner_empty_on_none(self):
        with patch("src.agent.run_agent", return_value=None):
            out = agent_runner("q", 5, None)
        self.assertEqual(out["results"], [])
        self.assertTrue(out["cost"]["fallback"])


if __name__ == "__main__":
    unittest.main()
