# NexusRAG

Multi-document RAG system with a FastAPI backend, PostgreSQL/pgvector storage, and a Next.js + shadcn/ui frontend.

## Requirements

- Docker container `postgres-db` running `pgvector/pgvector:pg15`
- PostgreSQL database `nexus_rag` with the `vector` extension enabled
- Python 3.11+
- Node.js + npm

## Setup

1. Copy `.env.example` to `.env` and fill in PostgreSQL, embedding, and LLM values.
2. Install Python dependencies:

```bash
uv sync
```

3. Install the Next.js UI dependencies:

```bash
cd ui/web && npm install
```

## Run

```bash
./run.sh            # backend :8000 + frontend :3000
./run.sh backend    # FastAPI only
./run.sh ui         # Next.js only
```

## Configuration

| Variable | Purpose |
| --- | --- |
| `POSTGRES_*` | PostgreSQL connection used by FastAPI |
| `EMBEDDING_PROVIDER` | `openai` for OpenAI-compatible embeddings or `local` for sentence-transformers |
| `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION` | Embedding model and vector dimension |
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | OpenAI-compatible Chat Completions provider used for grounded answers |
| `LLM_TIMEOUT` | LLM request timeout in seconds |

The backend creates the `documents` and `chunks` tables plus the HNSW vector index on startup. Uploaded source files are stored under `data/uploads/`.
