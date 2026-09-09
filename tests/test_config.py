import os
import unittest
from unittest.mock import patch

from src.config import embedding_dimension


class ConfigTests(unittest.TestCase):
    def test_embedding_dimension_defaults_by_provider(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(embedding_dimension(), 1536)
            os.environ["EMBEDDING_PROVIDER"] = "local"
            self.assertEqual(embedding_dimension(), 1024)

    def test_embedding_dimension_rejects_non_positive_values(self):
        with patch.dict(os.environ, {"EMBEDDING_DIMENSION": "0"}):
            with self.assertRaises(ValueError):
                embedding_dimension()


if __name__ == "__main__":
    unittest.main()
