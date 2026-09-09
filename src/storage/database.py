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
    rows = [
        (
            str(uuid.uuid4()),
            doc_id,
            doc_name,
            index,
            text,
            vector_literal(embedding),
            json.dumps(item_metadata),
        )
        for index, (text, embedding, item_metadata) in enumerate(zip(texts, embeddings, metadata))
    ]
    with connection() as conn:
        # Transactional replacement: encoding happens before this function.
        conn.execute("DELETE FROM chunks WHERE document_id = %s", (doc_id,))
        conn.executemany(
            """
            INSERT INTO chunks (id, document_id, doc_name, chunk_index, text, embedding, metadata)
            VALUES (%s, %s, %s, %s, %s, %s::vector, %s)
            """,
            rows,
        )


def get_chunks(doc_id: str) -> list[dict]:
    with connection() as conn:
        return list(conn.execute(
            "SELECT chunk_index, text, metadata FROM chunks WHERE document_id = %s ORDER BY chunk_index",
            (doc_id,),
        ))


def search_chunks(query_embedding: list[float], top_k: int = 5, doc_id: str | None = None) -> list[dict]:
    query_vector = vector_literal(query_embedding)
    where = ""
    filters: list[object] = []
    if doc_id:
        where = "WHERE document_id = %s"
        filters.append(doc_id)
    with connection() as conn:
        return list(conn.execute(
            f"""
            SELECT id::text AS chunk_id, document_id, doc_name, chunk_index, text, metadata,
                   1 - (embedding <=> %s::vector) AS score
            FROM chunks
            {where}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            [query_vector, *filters, query_vector, top_k],
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
def stats() -> dict:
    with connection() as conn:
        row = conn.execute(
            "SELECT count(*)::int AS total_chunks, COALESCE(sum(octet_length(text)), 0)::bigint AS text_bytes FROM chunks"
        ).fetchone()
        docs = conn.execute("SELECT count(*)::int AS total_documents FROM documents").fetchone()
        return {**row, **docs, "embedding_dimension": _VECTOR_DIM}
