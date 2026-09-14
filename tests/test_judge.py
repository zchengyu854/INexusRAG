"""答案级判官：忠实度/正确性打分、端到端生成与汇总。

判官会打真实的 LLM，所以测试里全部用 Fake LLM 打桩，保证离线、确定性。
"""
import unittest
from unittest.mock import MagicMock, patch

from src.judge import (
    generate_answer,
    judge_correctness,
    judge_faithfulness,
    score_faithfulness,
)


class FakeJudgeLLM:
    def __init__(self, payload=None, enabled=True, raises=None):
        self.enabled = enabled
        self._payload = payload or {}
        self._raises = raises
        self.prompts = []

    def tool_call(self, prompt, tool):
        self.prompts.append(prompt)
        if self._raises:
            raise self._raises
        return self._payload

    def generate(self, question, sources, history=None):
        return "生成的回答"


class ScoreFaithfulnessTests(unittest.TestCase):
    def test_all_supported_scores_one(self):
        out = score_faithfulness([{"claim": "a", "supported": True}, {"claim": "b", "supported": True}])
        self.assertEqual(out["score"], 1.0)
        self.assertEqual(out["claim_count"], 2)
        self.assertEqual(out["unsupported_count"], 0)

    def test_mixed_claims_score_ratio(self):
        out = score_faithfulness([
            {"claim": "a", "supported": True},
            {"claim": "b", "supported": False},
            {"claim": "c", "supported": True},
            {"claim": "d", "supported": False},
        ])
        self.assertEqual(out["score"], 0.5)
        self.assertEqual(out["unsupported_claims"], ["b", "d"])

    def test_no_claims_is_undecidable_not_zero(self):
        """空答案判不了，不能算作 0 分（否则和「全都不支撑」混淆）。"""
        self.assertIsNone(score_faithfulness([])["score"])
        self.assertIsNone(score_faithfulness(None)["score"])

    def test_unsupported_claims_are_capped(self):
        claims = [{"claim": f"c{i}", "supported": False} for i in range(25)]
        out = score_faithfulness(claims)
        self.assertEqual(out["unsupported_count"], 25)
        self.assertEqual(len(out["unsupported_claims"]), 10)


class JudgeFaithfulnessTests(unittest.TestCase):
    def test_parses_claims_from_structured_output(self):
        llm = FakeJudgeLLM(payload={"claims": [
            {"claim": "民法典第二百三十条规定继承取得物权自继承开始时生效", "supported": True},
            {"claim": "该条还规定了诉讼时效", "supported": False},
        ]})
        out = judge_faithfulness(
            "民法典的二百三十条是什么",
            "因继承取得物权，自继承开始时发生效力；另规定了诉讼时效。",
            [{"doc_name": "d", "chunk_index": 1, "text": "因继承取得物权的，自继承开始时发生效力"}],
            llm=llm,
        )
        self.assertEqual(out["score"], 0.5)
        self.assertEqual(out["unsupported_count"], 1)
        # prompt 里要同时带上问题、来源与回答，判官才有判据
        prompt = llm.prompts[0]
        self.assertIn("民法典的二百三十条是什么", prompt)
        self.assertIn("因继承取得物权的，自继承开始时发生效力", prompt)
        self.assertIn("另规定了诉讼时效", prompt)

    def test_disabled_llm_returns_none(self):
        self.assertIsNone(judge_faithfulness("q", "a", [], llm=FakeJudgeLLM(enabled=False)))

    def test_judge_failure_returns_none_instead_of_raising(self):
        """判官挂了不能拖垮整个评测。"""
        llm = FakeJudgeLLM(raises=RuntimeError("网关超时"))
        self.assertIsNone(judge_faithfulness("q", "a", [], llm=llm))

    def test_empty_answer_is_skipped(self):
        self.assertIsNone(judge_faithfulness("q", "   ", [], llm=FakeJudgeLLM(payload={"claims": []})))


class JudgeCorrectnessTests(unittest.TestCase):
    def test_parses_and_clamps_score(self):
        llm = FakeJudgeLLM(payload={"verdict": "partial", "score": 1.4, "reason": "x"})
        out = judge_correctness("q", "a", "参考答案", llm=llm)
        self.assertEqual(out["score"], 1.0)
        self.assertEqual(out["verdict"], "partial")

    def test_missing_reference_returns_none(self):
        self.assertIsNone(judge_correctness("q", "a", None, llm=FakeJudgeLLM()))
        self.assertIsNone(judge_correctness("q", "a", "", llm=FakeJudgeLLM()))

    def test_bad_score_returns_none(self):
        llm = FakeJudgeLLM(payload={"verdict": "consistent", "score": "不是数字"})
        self.assertIsNone(judge_correctness("q", "a", "ref", llm=llm))


class GenerateAnswerTests(unittest.TestCase):
    def test_returns_answer_with_sources(self):
        llm = FakeJudgeLLM()
        with patch("src.retrieval.multi_query_search", return_value=[{"doc_name": "d", "chunk_index": 0, "text": "t"}]):
            out = generate_answer("问题", llm=llm)
        self.assertEqual(out["answer"], "生成的回答")
        self.assertEqual(len(out["sources"]), 1)

    def test_no_sources_short_circuits(self):
        llm = FakeJudgeLLM()
        with patch("src.retrieval.multi_query_search", return_value=[]):
            out = generate_answer("问题", llm=llm)
        self.assertEqual(out["sources"], [])
        self.assertIn("未检索到", out["answer"])


class EvaluateAnswersTests(unittest.TestCase):
    def test_summary_averages_and_persists(self):
        from src.evaluation import evaluate_answers

        cases = [
            {"id": 1, "question": "q1", "reference_answer": "r1", "expected": set()},
            {"id": 2, "question": "q2", "reference_answer": "r2", "expected": set()},
        ]
        saved: list = []
        with patch("src.evaluation.load_cases", return_value=cases), \
             patch("src.judge.generate_answer", return_value={"answer": "a", "sources": [{"text": "t"}]}), \
             patch("src.judge.judge_faithfulness", side_effect=[
                 {"score": 1.0, "claim_count": 2, "unsupported_count": 0, "unsupported_claims": []},
                 {"score": 0.5, "claim_count": 4, "unsupported_count": 2, "unsupported_claims": ["x"]},
             ]), \
             patch("src.judge.judge_correctness", return_value={"score": 0.8, "verdict": "partial"}), \
             patch("src.judge.save_result", side_effect=lambda *a: saved.append(a)):
            out = evaluate_answers(run_label="t", llm=FakeJudgeLLM())

        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["faithfulness"], 0.75)   # (1.0 + 0.5) / 2
        self.assertEqual(out[0]["correctness"], 0.8)
        self.assertEqual(out[0]["unsupported_claims"], 2)
        self.assertEqual(len(saved), 2)                  # 两例都落库


    def test_config_mode_overrides_default(self):
        """三项形式 (label, features, mode) 必须真的切换范式，不能只换标签。"""
        from src.evaluation import evaluate_answers

        cases = [{"id": 1, "question": "q1", "reference_answer": "r1", "expected": set()}]
        seen: list = []
        with patch("src.evaluation.load_cases", return_value=cases), \
             patch("src.judge.generate_answer",
                   side_effect=lambda q, **kw: (seen.append(kw.get("mode")), {"answer": "a", "sources": []})[1]), \
             patch("src.judge.judge_faithfulness", return_value=None), \
             patch("src.judge.judge_correctness", return_value=None), \
             patch("src.judge.save_result", return_value=None):
            evaluate_answers(
                configs=[("a", None, "pipeline"), ("b", None, "agent")],
                llm=FakeJudgeLLM(),
            )
        self.assertEqual(seen, ["pipeline", "agent"])


    def test_generation_failure_does_not_abort_the_run(self):
        """单例生成失败（余额不足/限流）要记录并继续，不能丢掉整轮结果。"""
        from src.evaluation import evaluate_answers

        cases = [
            {"id": 1, "question": "q1", "reference_answer": "r1", "expected": set()},
            {"id": 2, "question": "q2", "reference_answer": "r2", "expected": set()},
        ]
        calls = {"n": 0}

        def flaky(question, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("402 Insufficient Balance")
            return {"answer": "a", "sources": []}

        with patch("src.evaluation.load_cases", return_value=cases), \
             patch("src.judge.generate_answer", side_effect=flaky), \
             patch("src.judge.judge_faithfulness", return_value={"score": 0.5, "claim_count": 2,
                                                                 "unsupported_count": 1, "unsupported_claims": ["x"]}), \
             patch("src.judge.judge_correctness", return_value={"score": 0.5, "verdict": "partial"}), \
             patch("src.judge.save_result", return_value=None):
            out = evaluate_answers(run_label="t", llm=FakeJudgeLLM())

        self.assertEqual(out[0]["failed"], 1)          # 记下了失败
        self.assertEqual(out[0]["judged"], 1)          # 成功的那例照常统计
        self.assertEqual(out[0]["faithfulness"], 0.5)
        self.assertIn("402", out[0]["failures"][0]["error"])


if __name__ == "__main__":
    unittest.main()
