"""LLM 错误归类：把 provider 的原始报错翻成「原因 + 建议」。

背景：界面曾直接显示 `Your request was blocked.`——用户看到英文原文，无法判断
该换 key、充值还是换端点。这些用例锁住归类结果。
"""
import unittest

from src.llm.errors import describe_key, explain_llm_error


class _FakeProviderError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ExplainLlmErrorTests(unittest.TestCase):
    def test_insufficient_balance_is_reported_as_credit_issue(self):
        exc = _FakeProviderError(
            "Error code: 402 - {'error': {'message': 'Insufficient Balance'}}", 402
        )
        out = explain_llm_error(exc)
        self.assertIn("余额", out["reason"])
        self.assertIn("充值", out["hint"])
        self.assertEqual(out["status"], 402)

    def test_blocked_request_points_at_key_or_relay(self):
        """实测第三方中转返回这个错误，提示里要提到中转与官方端点两条路。"""
        exc = _FakeProviderError("Your request was blocked.", 403)
        out = explain_llm_error(exc)
        self.assertIn("被拒绝", out["reason"])
        self.assertIn("中转", out["hint"])

    def test_invalid_key(self):
        exc = _FakeProviderError("Error code: 401 - Invalid API key", 401)
        self.assertIn("密钥", explain_llm_error(exc)["reason"])

    def test_unknown_model(self):
        exc = _FakeProviderError("Error code: 404 - Model Not Exist", 404)
        out = explain_llm_error(exc)
        self.assertIn("模型", out["reason"])

    def test_rate_limit(self):
        exc = _FakeProviderError("Rate limit reached for requests", 429)
        self.assertIn("限流", explain_llm_error(exc)["reason"])

    def test_timeout_without_status(self):
        out = explain_llm_error(_FakeProviderError("Request timed out."))
        self.assertIn("超时", out["reason"])

    def test_connection_failure(self):
        out = explain_llm_error(_FakeProviderError("Connection error."))
        self.assertIn("连不上", out["reason"])

    def test_bad_gateway_status(self):
        out = explain_llm_error(_FakeProviderError("Bad gateway", 502))
        self.assertIn("网关", out["reason"])

    def test_unclassified_error_falls_back_to_raw_message(self):
        out = explain_llm_error(RuntimeError("某种没见过的故障"))
        self.assertIn("某种没见过的故障", out["reason"])
        self.assertTrue(out["hint"])
        self.assertIsNone(out["status"])

    def test_raw_is_truncated_for_storage(self):
        out = explain_llm_error(RuntimeError("x" * 500))
        self.assertLessEqual(len(out["raw"]), 300)


class DescribeKeyTests(unittest.TestCase):
    def test_masks_middle_of_key(self):
        out = describe_key("sk-8d3abcdefghijklmnopqrstuvwxyz3e79")
        self.assertTrue(out.startswith("sk-8d3"))
        self.assertTrue(out.endswith("3e79"))
        self.assertNotIn("abcdefghij", out)

    def test_short_or_empty_key_is_not_leaked(self):
        self.assertEqual(describe_key(""), "（0 字符）")
        self.assertEqual(describe_key("short"), "（5 字符）")


if __name__ == "__main__":
    unittest.main()
