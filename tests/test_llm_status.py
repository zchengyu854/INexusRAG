"""LLM 运行时可用性记录 + 健康检查如实呈现。

背景：健康检查原先只判断「配没配 key」，provider 被 403/402 拒绝时界面依旧显示「后端正常」。
"""
import unittest
from unittest.mock import MagicMock, patch

from src.api.schemas import HealthLLM
from src.llm import status


class _ProviderError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class StatusTrackingTests(unittest.TestCase):
    def setUp(self) -> None:
        status.reset()
        self.addCleanup(status.reset)

    def test_starts_unverified(self):
        self.assertIsNone(status.snapshot()["ok"])

    def test_success_records_model_and_time(self):
        status.record_success("deepseek-flash")
        snap = status.snapshot()
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["model"], "deepseek-flash")
        self.assertIsNotNone(snap["checked_at"])

    def test_failure_records_classified_reason(self):
        status.record_failure(
            _ProviderError("Error code: 402 - Insufficient Balance", 402), "deepseek-flash"
        )
        snap = status.snapshot()
        self.assertFalse(snap["ok"])
        self.assertIn("余额", snap["reason"])
        self.assertIn("充值", snap["hint"])
        self.assertEqual(snap["status_code"], 402)

    def test_snapshot_is_a_copy(self):
        snap = status.snapshot()
        snap["ok"] = "tampered"
        self.assertIsNone(status.snapshot()["ok"])


class ClientRecordsStatusTests(unittest.TestCase):
    def _client(self, effects):
        from src.llm.client import LLMClient

        client = LLMClient(api_key="k", model="deepseek-flash")
        client._client = MagicMock()
        client._client.chat.completions.create.side_effect = effects
        return client

    def setUp(self) -> None:
        status.reset()
        self.addCleanup(status.reset)

    def test_successful_call_marks_available(self):
        ok = MagicMock()
        ok.choices = [MagicMock()]
        ok.choices[0].message = MagicMock()
        client = self._client([ok])
        client.generate("问题", [])
        self.assertTrue(status.snapshot()["ok"])

    def test_failed_call_marks_unavailable_with_reason(self):
        client = self._client([_ProviderError("Your request was blocked.", 403)])
        with self.assertRaises(Exception):
            client.generate("问题", [])
        snap = status.snapshot()
        self.assertFalse(snap["ok"])
        self.assertIn("被拒绝", snap["reason"])


class HealthReportsLLMTests(unittest.TestCase):
    """health 必须把运行时状态带出来，并在 LLM 不可用时标记 degraded。"""

    def _health(self, llm_ok: bool | None):
        provider = {"api_key": "sk-x", "name": "deepseek", "model": "deepseek-flash"}
        with patch("src.api.routes.database_stats",
                   return_value={"total_documents": 8, "total_chunks": 5750}), \
             patch("src.api.routes.get_active_llm_provider_row", return_value=provider), \
             patch("src.llm.status.snapshot", return_value={
                 "ok": llm_ok, "reason": "请求被拒绝" if llm_ok is False else None,
                 "hint": "改用官方端点" if llm_ok is False else None,
                 "status_code": 403 if llm_ok is False else None,
                 "model": "deepseek-flash", "checked_at": "2026-09-14T05:00:00+00:00",
             }):
            from src.api.routes import health

            return health()

    def test_unavailable_llm_marks_service_degraded(self):
        response = self._health(llm_ok=False)
        self.assertEqual(response.status, "degraded")
        self.assertFalse(response.llm.ok)
        self.assertIn("被拒绝", response.llm.reason)
        self.assertEqual(response.llm.status_code, 403)

    def test_verified_llm_keeps_service_ok(self):
        response = self._health(llm_ok=True)
        self.assertEqual(response.status, "ok")
        self.assertTrue(response.llm.ok)

    def test_unverified_llm_does_not_claim_degraded(self):
        """进程刚起、还没调用过 → 不确定，不能谎报降级，也不能谎报正常。"""
        response = self._health(llm_ok=None)
        self.assertEqual(response.status, "ok")
        self.assertIsNone(response.llm.ok)


class HealthLLMSchemaTests(unittest.TestCase):
    def test_runtime_fields_have_safe_defaults(self):
        """新增字段要可选，否则老客户端/旧数据反序列化会炸。"""
        llm = HealthLLM(configured=True, source="database")
        self.assertIsNone(llm.ok)
        self.assertIsNone(llm.reason)


if __name__ == "__main__":
    unittest.main()
