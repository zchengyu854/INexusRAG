"""PostgreSQL persistence and pgvector access."""
from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from typing import Iterator

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from src.config import embedding_dimension

load_dotenv()

_DB_NAME = os.getenv("POSTGRES_DB", "nexus_rag")
_DB_ADMIN = os.getenv("POSTGRES_ADMIN_DB", "postgres")
_DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
_DB_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
_DB_USER = os.getenv("POSTGRES_USER", "postgres")
_DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
_VECTOR_DIM = embedding_dimension()


def _dsn(database: str = _DB_NAME) -> str:
    return f"host={_DB_HOST} port={_DB_PORT} dbname={database} user={_DB_USER} password={_DB_PASSWORD}"


@contextmanager
def connection(database: str = _DB_NAME) -> Iterator[psycopg.Connection]:
    with psycopg.connect(_dsn(database), row_factory=dict_row) as conn:
        yield conn


def ensure_database() -> None:
    """Create the application database and schema on startup."""
    with connection(_DB_ADMIN) as conn:
        conn.autocommit = True
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (_DB_NAME,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{_DB_NAME}"')

    with connection() as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                source_path TEXT NOT NULL,
                source_sha256 TEXT,
                status TEXT NOT NULL DEFAULT 'indexing',
                chunks INTEGER NOT NULL DEFAULT 0,
                latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
                config JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id UUID PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                doc_name TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                embedding vector({_VECTOR_DIM}) NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(document_id, chunk_index)
            );
            CREATE INDEX IF NOT EXISTS chunks_embedding_idx
                ON chunks USING hnsw (embedding vector_cosine_ops);
            CREATE INDEX IF NOT EXISTS chunks_document_idx ON chunks(document_id);
            CREATE INDEX IF NOT EXISTS chunks_metadata_idx
                ON chunks USING gin (metadata jsonb_path_ops);
            CREATE INDEX IF NOT EXISTS chunks_text_trgm_idx
                ON chunks USING gin (text gin_trgm_ops);
            CREATE TABLE IF NOT EXISTS conversation_messages (
                id UUID PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                sources JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS conversation_messages_idx
                ON conversation_messages(conversation_id, created_at);
            CREATE TABLE IF NOT EXISTS doc_index (
                doc_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
                doc_name TEXT NOT NULL,
                summary TEXT NOT NULL,
                embedding vector({_VECTOR_DIM}) NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS llm_providers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                model TEXT NOT NULL,
                base_url TEXT NOT NULL DEFAULT 'https://api.openai.com/v1',
                api_key TEXT NOT NULL DEFAULT '',
                timeout REAL NOT NULL DEFAULT 60,
                active BOOLEAN NOT NULL DEFAULT false,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        vector_type = conn.execute(
            """
            SELECT format_type(a.atttypid, a.atttypmod) AS type
            FROM pg_attribute AS a
            JOIN pg_class AS c ON c.oid = a.attrelid
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = 'chunks' AND a.attname = 'embedding'
            """
        ).fetchone()["type"]
        expected_type = f"vector({_VECTOR_DIM})"
        if vector_type != expected_type:
            raise RuntimeError(
                f"数据库向量维度为 {vector_type}，配置要求 {expected_type}；请迁移或重建 chunks 表"
            )


def vector_literal(values: list[float]) -> str:
    if len(values) != _VECTOR_DIM:
        raise ValueError(f"embedding dimension mismatch: expected {_VECTOR_DIM}, got {len(values)}")
    return "[" + ",".join(str(float(value)) for value in values) + "]"


def create_document(doc_id: str, filename: str, source_path: str) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO documents (id, filename, source_path) VALUES (%s, %s, %s)",
            (doc_id, filename, source_path),
        )


def get_document(doc_id: str) -> dict | None:
    with connection() as conn:
        return conn.execute("SELECT * FROM documents WHERE id = %s", (doc_id,)).fetchone()


def list_documents() -> list[dict]:
    with connection() as conn:
        return list(conn.execute("SELECT * FROM documents ORDER BY created_at DESC"))


def update_document(doc_id: str, **fields: object) -> None:
    if not fields:
        return
    fields["updated_at"] = "now()"
    assignments = []
    values: list[object] = []
    for key, value in fields.items():
        if value == "now()":
            assignments.append(f"{key} = now()")
        else:
            assignments.append(f"{key} = %s")
            values.append(json.dumps(value) if key == "config" else value)
    values.append(doc_id)
    with connection() as conn:
        conn.execute(f"UPDATE documents SET {', '.join(assignments)} WHERE id = %s", values)


def delete_document(doc_id: str) -> int:
    with connection() as conn:
        result = conn.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
        return result.rowcount


def replace_chunks(
    doc_id: str,
    doc_name: str,
    texts: list[str],
    embeddings: list[list[float]],
    metadata: list[dict] | None = None,
) -> None:
    if len(texts) != len(embeddings):
        raise ValueError("texts and embeddings length mismatch")
    if metadata is not None and len(texts) != len(metadata):
        raise ValueError("texts and metadata length mismatch")
    metadata = metadata or [{} for _ in texts]
    values = []
    for index, (text, embedding, item_metadata) in enumerate(zip(texts, embeddings, metadata)):
        values.extend([
            str(uuid.uuid4()),
            doc_id,
            doc_name,
            index,
            text,
            vector_literal(embedding),
            json.dumps(item_metadata),
        ])
    rows = "(" + "),(".join([", ".join(["%s, %s, %s, %s, %s, %s::vector, %s"]) for _ in texts]) + ")"
    with connection() as conn:
        # Transactional replacement: encoding happens before this function.
        conn.execute("DELETE FROM chunks WHERE document_id = %s", (doc_id,))
        # ponytail: 单条多行 INSERT，参数数 = 7*chunks，超过 PG 65535 参数上限（约 9000 chunk/文档）时改用 COPY
        conn.execute(
            f"""
            INSERT INTO chunks (id, document_id, doc_name, chunk_index, text, embedding, metadata)
            VALUES {rows}
            """,
            values,
        )


def get_chunks(doc_id: str) -> list[dict]:
    with connection() as conn:
        return list(conn.execute(
            "SELECT chunk_index, text, metadata FROM chunks WHERE document_id = %s ORDER BY chunk_index",
            (doc_id,),
        ))


def search_chunks(query_embedding: list[float], top_k: int = 5, doc_id: str | None = None, filters: dict | None = None) -> list[dict]:
    """向量通道；filters 为 metadata JSONB 包含条件，如 {"page": 5}、{"figure": True}。"""
    query_vector = vector_literal(query_embedding)
    where: list[str] = []
    params: list[object] = []
    if doc_id:
        where.append("document_id = %s")
        params.append(doc_id)
    if filters:
        where.append("metadata @> %s::jsonb")
        params.append(json.dumps(filters, ensure_ascii=False))
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    with connection() as conn:
        return list(conn.execute(
            f"""
            SELECT id::text AS chunk_id, document_id, doc_name, chunk_index, text, metadata,
                   1 - (embedding <=> %s::vector) AS score
            FROM chunks
            {where_sql}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            [query_vector, *params, query_vector, top_k],
        ))


def keyword_chunks(terms: list[str], limit: int = 50, filters: dict | None = None) -> list[dict]:
    """词汇通道：大小写不敏感子串匹配，由 trigram GIN 索引服务；filters 同 search_chunks。"""
    if not terms:
        return []
    def _escape(term: str) -> str:
        return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    patterns = [f"%{_escape(t)}%" for t in terms]
    # ponytail: GIN trigram 只支持单模式/AND，多词 OR 退回 Seq Scan；数据量大时换 tsvector+zhparser 分词列
    where = ["(" + " OR ".join(["text ILIKE %s"] * len(patterns)) + ")"]
    params: list[object] = list(patterns)
    if filters:
        where.append("metadata @> %s::jsonb")
        params.append(json.dumps(filters, ensure_ascii=False))
    sql = f"""
        SELECT id::text AS chunk_id, document_id, doc_name, chunk_index, text, metadata,
               0::double precision AS score
        FROM chunks
        WHERE {' AND '.join(where)}
        LIMIT %s
    """
    with connection() as conn:
        return list(conn.execute(sql, [*params, limit]))


def upsert_doc_index(doc_id: str, doc_name: str, summary: str, embedding: list[float]) -> None:
    """路由层：每个文档一行极短摘要 + 向量，用于检索前定位目标文档。"""
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO doc_index (doc_id, doc_name, summary, embedding, updated_at)
            VALUES (%s, %s, %s, %s::vector, now())
            ON CONFLICT (doc_id) DO UPDATE
                SET doc_name = EXCLUDED.doc_name,
                    summary = EXCLUDED.summary,
                    embedding = EXCLUDED.embedding,
                    updated_at = now()
            """,
            (doc_id, doc_name, summary, vector_literal(embedding)),
        )


def search_doc_index(query_embedding: list[float], top_k: int = 3) -> list[dict]:
    """第一步路由：向量命中最相关的文档。"""
    query_vector = vector_literal(query_embedding)
    with connection() as conn:
        return list(conn.execute(
            """
            SELECT doc_id, doc_name, summary, 1 - (embedding <=> %s::vector) AS score
            FROM doc_index
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (query_vector, query_vector, top_k),
        ))


def save_message(
    conversation_id: str,
    role: str,
    content: str,
    sources: list[dict] | None = None,
) -> dict:
    if role not in {"user", "assistant"}:
        raise ValueError("invalid message role")
    message_id = str(uuid.uuid4())
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO conversation_messages (id, conversation_id, role, content, sources)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id::text, role, content, sources, created_at
            """,
            (message_id, conversation_id, role, content, json.dumps(sources or [])),
        ).fetchone()
    return dict(row)


def get_messages(conversation_id: str, limit: int = 100) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT id::text, role, content, sources, created_at
            FROM conversation_messages
            WHERE conversation_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (conversation_id, limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def list_conversations(limit: int = 50) -> list[dict]:
    with connection() as conn:
        return list(conn.execute(
            """
            SELECT conversation_id AS id,
                   COALESCE(
                       (array_agg(content ORDER BY created_at) FILTER (WHERE role = 'user'))[1],
                       'New conversation'
                   ) AS title,
                   count(*)::int AS message_count,
                   max(created_at) AS updated_at
            FROM conversation_messages
            GROUP BY conversation_id
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            (limit,),
        ))


def delete_messages(conversation_id: str) -> None:
    with connection() as conn:
        conn.execute(
            "DELETE FROM conversation_messages WHERE conversation_id = %s",
            (conversation_id,),
        )
def list_llm_providers() -> list[dict]:
    with connection() as conn:
        return list(conn.execute("SELECT * FROM llm_providers ORDER BY created_at"))


def get_llm_provider(provider_id: str) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM llm_providers WHERE id = %s", (provider_id,)).fetchone()
        return dict(row) if row else None


def get_active_llm_provider() -> dict | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM llm_providers WHERE active ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def upsert_llm_provider(data: dict) -> dict:
    """按 name 插入或更新。"""
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO llm_providers (id, name, model, base_url, api_key, timeout, active)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (name) DO UPDATE
              SET model = EXCLUDED.model,
                  base_url = EXCLUDED.base_url,
                  api_key = EXCLUDED.api_key,
                  timeout = EXCLUDED.timeout,
                  active = EXCLUDED.active
            RETURNING *
            """,
            (
                str(uuid.uuid4()),
                data["name"],
                data["model"],
                data["base_url"],
                data["api_key"],
                data["timeout"],
                data.get("active", False),
            ),
        ).fetchone()
    return dict(row)


def activate_llm_provider(provider_id: str) -> dict | None:
    """互斥激活：先全部置 false，再激活目标行（同一事务内提交）。"""
    with connection() as conn:
        conn.execute("UPDATE llm_providers SET active = false")
        row = conn.execute(
            "UPDATE llm_providers SET active = true WHERE id = %s RETURNING *", (provider_id,)
        ).fetchone()
        return dict(row) if row else None


def delete_llm_provider(provider_id: str) -> bool:
    with connection() as conn:
        result = conn.execute("DELETE FROM llm_providers WHERE id = %s", (provider_id,))
        return result.rowcount > 0


def stats() -> dict:
    with connection() as conn:
        row = conn.execute(
            "SELECT count(*)::int AS total_chunks, COALESCE(sum(octet_length(text)), 0)::bigint AS text_bytes FROM chunks"
        ).fetchone()
        docs = conn.execute("SELECT count(*)::int AS total_documents FROM documents").fetchone()
        return {**row, **docs, "embedding_dimension": _VECTOR_DIM}
