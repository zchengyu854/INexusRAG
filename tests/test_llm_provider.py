import os
import unittest
from unittest.mock import MagicMock, patch

from src.llm.client import LLMClient, _is_transient, get_llm


class FakeTransient(Exception):
    """带 status_code 的假瞬时错误（模拟 5xx，避免依赖 openai 异常构造器）。"""

    status_code = 502


class FakeFatal(Exception):
    status_code = 400


class TestGetLlmResolution(unittest.TestCase):
    """get_llm(): active DB provider 优先，未激活或 DB 故障时回退环境变量。"""

    def test_active_provider_wins(self):
        row = {"api_key": "sk-db", "base_url": "https://db.local/v1/", "model": "db-model", "timeout": 30}
        with patch("src.storage.database.get_active_llm_provider", return_value=row):
            client = get_llm()
        self.assertEqual(client.api_key, "sk-db")
        self.assertEqual(client.base_url, "https://db.local/v1")  # 尾斜杠被剥掉
        self.assertEqual(client.model, "db-model")
        self.assertEqual(client.timeout, 30.0)
        self.assertTrue(client.enabled)

    def test_fallback_to_env_when_no_active_provider(self):
        env = {"LLM_API_KEY": "sk-env", "LLM_BASE_URL": "https://env.local/v1", "LLM_MODEL": "env-model", "LLM_TIMEOUT": "12"}
        with patch("src.storage.database.get_active_llm_provider", return_value=None), patch.dict(os.environ, env, clear=False):
            client = get_llm()
        self.assertEqual(client.api_key, "sk-env")
        self.assertEqual(client.model, "env-model")
        self.assertEqual(client.timeout, 12.0)

    def test_db_error_falls_back_to_env(self):
        with patch("src.storage.database.get_active_llm_provider", side_effect=RuntimeError("db down")), patch.dict(
            os.environ, {"LLM_API_KEY": "", "LLM_MODEL": "gpt-4o-mini"}, clear=False
        ):
            client = get_llm()
        self.assertFalse(client.enabled)
        self.assertEqual(client.model, "gpt-4o-mini")


class RetryTests(unittest.TestCase):
    """_create_with_retry：瞬时错误指数退避重试，致命错误立即抛出。"""

    def _client_with_side_effects(self, effects):
        """构造 LLMClient，其 create 依序抛出 effects 中的异常/返回值。"""
        client = LLMClient(api_key="k", model="m")
        client._client = MagicMock()
        client._client.chat.completions.create.side_effect = effects
        return client

    def test_transient_error_is_retried_then_succeeds(self):
        ok = MagicMock()
        client = self._client_with_side_effects([FakeTransient("网关抖动"), FakeTransient("又抖"), ok])
        with patch("src.llm.client.time.sleep") as sleep_mock:
            out = client._create_with_retry(model="m", messages=[])
        self.assertIs(out, ok)
        self.assertEqual(client._client.chat.completions.create.call_count, 3)
        # 指数退避：0.5s → 1.0s
        self.assertEqual([c.args[0] for c in sleep_mock.call_args_list], [0.5, 1.0])

    def test_fatal_error_is_not_retried(self):
        client = self._client_with_side_effects([FakeFatal("参数错误"), MagicMock()])
        with self.assertRaises(FakeFatal):
            client._create_with_retry(model="m", messages=[])
        self.assertEqual(client._client.chat.completions.create.call_count, 1)

    def test_retries_exhausted_raises_last_error(self):
        client = self._client_with_side_effects([FakeTransient("一直抖")] * 5)
        with patch("src.llm.client.time.sleep"):
            with self.assertRaises(FakeTransient):
                client._create_with_retry(model="m", messages=[])
        # 1 次原始调用 + max_retries(默认 2) 次重试 = 3 次
        self.assertEqual(client._client.chat.completions.create.call_count, 3)

    def test_is_transient_covers_http_semantics(self):
        self.assertTrue(_is_transient(FakeTransient("502")))
        self.assertFalse(_is_transient(FakeFatal("400")))
        self.assertFalse(_is_transient(RuntimeError("无 status_code 的普通错误")))

    def test_zero_retries_raises_immediately(self):
        client = self._client_with_side_effects([FakeTransient("抖"), MagicMock()])
        client.max_retries = 0
        with self.assertRaises(FakeTransient):
            client._create_with_retry(model="m", messages=[])
        self.assertEqual(client._client.chat.completions.create.call_count, 1)

    def test_generate_uses_retry_path(self):
        """generate 走重试包装：第一次瞬时失败后第二次成功。"""
        client = LLMClient(api_key="k", model="m")
        msg = MagicMock()
        msg.content = "答案"
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message = msg
        client._client = MagicMock()
        client._client.chat.completions.create.side_effect = [FakeTransient("抖"), resp]
        with patch("src.llm.client.time.sleep"):
            out = client.generate("问题", [])
        self.assertEqual(out, "答案")
        self.assertEqual(client._client.chat.completions.create.call_count, 2)


if __name__ == "__main__":
    unittest.main()
