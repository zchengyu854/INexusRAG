import os
import unittest
from unittest.mock import patch

from src.llm.client import get_llm


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


if __name__ == "__main__":
    unittest.main()
