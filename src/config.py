from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def embedding_dimension() -> int:
    """Return the configured vector size, with provider-safe defaults."""
    configured = os.getenv("EMBEDDING_DIMENSION")
    if configured:
        dimension = int(configured)
        if dimension < 1:
            raise ValueError("EMBEDDING_DIMENSION 必须大于 0")
        return dimension

    return 1024 if os.getenv("EMBEDDING_PROVIDER", "openai").lower() == "local" else 1536
