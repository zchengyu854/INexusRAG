import unittest

from src.evaluation import retrieval_metrics


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


if __name__ == "__main__":
    unittest.main()
