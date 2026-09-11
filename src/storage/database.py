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
            CREATE TABLE IF NOT EXISTS entities (
                id UUID PRIMARY KEY,
                name TEXT NOT NULL,
                norm TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL DEFAULT 'other',
                description TEXT NOT NULL DEFAULT '',
                embedding vector({_VECTOR_DIM}) NOT NULL,
                mentions INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS entities_embedding_idx
                ON entities USING hnsw (embedding vector_cosine_ops);
            CREATE TABLE IF NOT EXISTS relations (
                id UUID PRIMARY KEY,
                src UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                dst UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                rel TEXT NOT NULL,
                norm_rel TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1,
                evidence UUID REFERENCES chunks(id) ON DELETE SET NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (src, dst, norm_rel)
            );
            CREATE INDEX IF NOT EXISTS relations_src_idx ON relations(src);
            CREATE INDEX IF NOT EXISTS relations_dst_idx ON relations(dst);
            CREATE TABLE IF NOT EXISTS chunk_entities (
                chunk_id UUID NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
                entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                PRIMARY KEY (chunk_id, entity_id)
            );
            CREATE INDEX IF NOT EXISTS chunk_entities_entity_idx ON chunk_entities(entity_id);
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


# ===== GraphRAG P1：实体/关系存储（图谱是检索的第 4 条通道）=====
# ponytail: P1 只做局部检索（实体锚点 + ≤2 跳）。社区摘要/全局检索在 P2。


def upsert_entity(name: str, norm: str, kind: str, description: str, embedding: list[float]) -> str:
    """按 norm 幂等写实体；已存在则累加 mentions、补空 kind/description，返回 entity id。"""
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO entities (id, name, norm, kind, description, embedding, mentions)
            VALUES (%s, %s, %s, %s, %s, %s::vector, 1)
            ON CONFLICT (norm) DO UPDATE
                SET mentions = entities.mentions + 1,
                    kind = CASE WHEN entities.kind = 'other' THEN EXCLUDED.kind ELSE entities.kind END,
                    description = CASE
                        WHEN entities.description = '' THEN EXCLUDED.description
                        ELSE entities.description END
            RETURNING id::text
            """,
            (str(uuid.uuid4()), name, norm, kind, description, vector_literal(embedding)),
        ).fetchone()
    return row["id"]


def get_entity_by_norm(norm: str) -> dict | None:
    """归一化名精确匹配（实体消歧第一层，零成本）。"""
    with connection() as conn:
        return conn.execute(
            "SELECT id::text AS entity_id, name, norm, kind, description, mentions FROM entities WHERE norm = %s",
            (norm,),
        ).fetchone()


def search_entities(query_embedding: list[float], top_k: int = 5) -> list[dict]:
    """实体语义 ANN（查询侧锚点定位）：返回 [{entity_id, name, norm, kind, description, score}]。"""
    query_vector = vector_literal(query_embedding)
    with connection() as conn:
        return list(conn.execute(
            """
            SELECT id::text AS entity_id, name, norm, kind, description,
                   1 - (embedding <=> %s::vector) AS score
            FROM entities
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (query_vector, query_vector, top_k),
        ))


def add_relation(src_id: str, dst_id: str, rel: str, norm_rel: str, evidence_chunk_id: str | None = None) -> None:
    """幂等加边：同 (src,dst,norm_rel) 重复出现则 weight+1（共现证据计数）。自环忽略。"""
    if src_id == dst_id:
        return
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO relations (id, src, dst, rel, norm_rel, weight, evidence)
            VALUES (%s, %s, %s, %s, %s, 1, %s)
            ON CONFLICT (src, dst, norm_rel) DO UPDATE SET weight = relations.weight + 1
            """,
            (str(uuid.uuid4()), src_id, dst_id, rel, norm_rel, evidence_chunk_id),
        )


def link_chunk_entities(chunk_id: str, entity_ids: list[str]) -> None:
    """切片↔实体倒排（图召回最终由此落回切片）。"""
    unique_ids = list(dict.fromkeys(entity_ids))
    if not unique_ids:
        return
    values: list[object] = []
    for entity_id in unique_ids:
        values.extend([chunk_id, entity_id])
    rows = "(" + "),(".join(["%s, %s"] * len(unique_ids)) + ")"
    with connection() as conn:
        conn.execute(
            f"INSERT INTO chunk_entities (chunk_id, entity_id) VALUES {rows} ON CONFLICT DO NOTHING",
            values,
        )


def get_chunks_for_graph(doc_id: str) -> list[dict]:
    """图谱抽取用：带 chunk id 的切片列表（get_chunks 不带 id，抽不了图谱）。"""
    with connection() as conn:
        return list(conn.execute(
            "SELECT id::text AS chunk_id, chunk_index, text FROM chunks WHERE document_id = %s ORDER BY chunk_index",
            (doc_id,),
        ))


def chunk_has_entities(chunk_id: str) -> bool:
    """该切片是否已建过图（断点续跑用；抽取无实体的切片会重复处理，属少数）。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM chunk_entities WHERE chunk_id = %s LIMIT 1", (chunk_id,)
        ).fetchone()
    return row is not None


def graph_chunks(
    anchor_ids: list[str],
    hops: int = 2,
    limit: int = 25,
    filters: dict | None = None,
) -> list[dict]:
    """图通道：锚点实体 ≤hops 跳扩展 → 落回切片；返回与 search_chunks 同构的行。

    score = Σ 1/(1+hop)（多锚点命中累加）。
    剪枝策略：锚点自身发出的边（hop=0）不剪——锚点已确认相关；再往外走要求 weight>1，
    因为单篇文档里多数关系只出现一次，一律要求 weight>1 会把图剪成空壳。
    """
    if not anchor_ids:
        return []
    where = ""
    params: list[object] = [anchor_ids, hops]
    if filters:
        where = "WHERE c.metadata @> %s::jsonb"
        params.append(json.dumps(filters, ensure_ascii=False))
    params.append(limit)
    with connection() as conn:
        return list(conn.execute(
            f"""
            WITH RECURSIVE reach(entity_id, hop, path) AS (
                SELECT a, 0, ARRAY[a] FROM unnest(%s::uuid[]) AS a
                UNION ALL
                SELECT nb.entity_id, reach.hop + 1, reach.path || nb.entity_id
                FROM reach
                JOIN LATERAL (
                    SELECT CASE WHEN r.src = reach.entity_id THEN r.dst ELSE r.src END AS entity_id
                    FROM relations r
                    WHERE (r.src = reach.entity_id OR r.dst = reach.entity_id)
                      AND (reach.hop = 0 OR r.weight > 1)
                ) AS nb ON NOT (nb.entity_id = ANY(reach.path))
                WHERE reach.hop < %s
            )
            SELECT c.id::text AS chunk_id, c.document_id, c.doc_name, c.chunk_index, c.text, c.metadata,
                   SUM(1.0 / (1 + reach.hop))::double precision AS score
            FROM reach
            JOIN chunk_entities ce ON ce.entity_id = reach.entity_id
            JOIN chunks c ON c.id = ce.chunk_id
            {where}
            GROUP BY c.id
            ORDER BY score DESC
            LIMIT %s
            """,
            params,
        ))


def reset_graph() -> None:
    """P1 重建策略：全量清空（增量更新留到 P3，rechunk 后需重跑 build）。"""
    with connection() as conn:
        conn.execute("DELETE FROM relations")
        conn.execute("DELETE FROM chunk_entities")
        conn.execute("DELETE FROM entities")


def graph_stats() -> dict:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT (SELECT count(*) FROM entities) AS entities,
                   (SELECT count(*) FROM relations) AS relations,
                   (SELECT count(*) FROM chunk_entities) AS links,
                   (SELECT count(*) FROM entities e WHERE NOT EXISTS (
                        SELECT 1 FROM chunk_entities ce WHERE ce.entity_id = e.id)) AS orphan_entities
            """
        ).fetchone()
    return dict(row)


def graph_kind_counts() -> dict:
    """实体类型分布，供图谱页筛选器使用。"""
    with connection() as conn:
        rows = list(conn.execute(
            "SELECT kind, count(*)::int AS count FROM entities GROUP BY kind ORDER BY count DESC"
        ))
    return {row["kind"]: row["count"] for row in rows}


def search_entities_by_text(query: str, kind: str | None = None, limit: int = 20) -> list[dict]:
    """按名称/描述子串检索实体（浏览用，非检索锚点），按提及次数排序。"""
    where: list[str] = []
    params: list[object] = []
    text = (query or "").strip()
    if text:
        where.append("(name ILIKE %s OR norm ILIKE %s OR description ILIKE %s)")
        pattern = f"%{text}%"
        params.extend([pattern, pattern, pattern])
    if kind:
        where.append("kind = %s")
        params.append(kind)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    with connection() as conn:
        return list(conn.execute(
            f"""
            SELECT id::text AS entity_id, name, norm, kind, description, mentions
            FROM entities
            {clause}
            ORDER BY mentions DESC, name ASC
            LIMIT %s
            """,
            [*params, limit],
        ))


def get_entity(entity_id: str) -> dict | None:
    """单个实体详情。"""
    with connection() as conn:
        return conn.execute(
            """
            SELECT id::text AS entity_id, name, norm, kind, description, mentions
            FROM entities WHERE id = %s
            """,
            (entity_id,),
        ).fetchone()


def entity_edges(entity_id: str, limit: int = 50) -> dict:
    """实体的出边与入边（含对端实体信息），按 weight 降序。"""
    with connection() as conn:
        outgoing = list(conn.execute(
            """
            SELECT r.rel, r.norm_rel, r.weight, r.evidence::text AS evidence_chunk_id,
                   e.id::text AS entity_id, e.name, e.kind
            FROM relations r
            JOIN entities e ON e.id = r.dst
            WHERE r.src = %s
            ORDER BY r.weight DESC, e.name ASC
            LIMIT %s
            """,
            (entity_id, limit),
        ))
        incoming = list(conn.execute(
            """
            SELECT r.rel, r.norm_rel, r.weight, r.evidence::text AS evidence_chunk_id,
                   e.id::text AS entity_id, e.name, e.kind
            FROM relations r
            JOIN entities e ON e.id = r.src
            WHERE r.dst = %s
            ORDER BY r.weight DESC, e.name ASC
            LIMIT %s
            """,
            (entity_id, limit),
        ))
    return {"out": outgoing, "in": incoming}


def entity_evidence_chunks(entity_id: str, limit: int = 10) -> list[dict]:
    """该实体被提及的切片（图谱召回最终落回的证据）。"""
    with connection() as conn:
        return list(conn.execute(
            """
            SELECT c.id::text AS chunk_id, c.document_id, c.doc_name, c.chunk_index,
                   c.text, c.metadata
            FROM chunk_entities ce
            JOIN chunks c ON c.id = ce.chunk_id
            WHERE ce.entity_id = %s
            ORDER BY c.doc_name, c.chunk_index
            LIMIT %s
            """,
            (entity_id, limit),
        ))


def graph_subgraph(anchor_ids: list[str], hops: int = 2, limit: int = 150) -> dict:
    """以锚点实体为起点扩展 ≤hops 跳，返回 {nodes, edges} 图结构。

    与 graph_chunks 同源（都用 relations 双向扩展 + path 防环），区别是这里返回图本身
    而不是落回切片。hop 取多锚点命中时的最小跳数。
    """
    if not anchor_ids:
        return {"nodes": [], "edges": []}
    with connection() as conn:
        nodes = list(conn.execute(
            """
            WITH RECURSIVE reach(entity_id, hop, path) AS (
                SELECT a, 0, ARRAY[a] FROM unnest(%s::uuid[]) AS a
                UNION ALL
                SELECT nb.entity_id, reach.hop + 1, reach.path || nb.entity_id
                FROM reach
                JOIN LATERAL (
                    SELECT CASE WHEN r.src = reach.entity_id THEN r.dst ELSE r.src END AS entity_id
                    FROM relations r
                    WHERE r.src = reach.entity_id OR r.dst = reach.entity_id
                ) AS nb ON NOT (nb.entity_id = ANY(reach.path))
                WHERE reach.hop < %s
            )
            SELECT e.id::text AS entity_id, e.name, e.kind, e.mentions, min(reach.hop) AS hop
            FROM reach
            JOIN entities e ON e.id = reach.entity_id
            GROUP BY e.id, e.name, e.kind, e.mentions
            ORDER BY hop ASC, e.mentions DESC
            LIMIT %s
            """,
            (anchor_ids, hops, limit),
        ))
        if not nodes:
            return {"nodes": [], "edges": []}
        node_ids = [row["entity_id"] for row in nodes]
        edges = list(conn.execute(
            """
            SELECT r.src::text AS src, r.dst::text AS dst, r.rel, r.norm_rel, r.weight
            FROM relations r
            WHERE r.src = ANY(%s::uuid[]) AND r.dst = ANY(%s::uuid[])
            ORDER BY r.weight DESC
            """,
            (node_ids, node_ids),
        ))
    return {"nodes": nodes, "edges": edges}


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
