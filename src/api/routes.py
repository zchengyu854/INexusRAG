from __future__ import annotations

import asyncio
import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

import aiofiles
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse

from src.api.schemas import (
    ChunksPreviewResponse,
    DocChunkPreview,
    DocConfig,
    DocDetail,
    DocInfo,
    QueryRequest,
    QueryResponse,
    RechunkRequest,
    RechunkResult,
    SystemStats,
)
from src.ingestion.embedder import get_embedder
from src.ingestion.ingestion_pipeline import ingest_document
from src.ingestion.loaders import load
from src.ingestion.splitter import split_text
from src.ingestion.vector_store import get_vector_store

router = APIRouter(prefix="/api")

# ── 持久化层 ────────────────────────────────────────────────────────────────
_DOCS_FILE   = Path("data/docs_index.json")
_CHUNKS_FILE = Path("data/chunks_cache.json")
_EMB_FILE    = Path("data/embeddings_cache.json")
for p in (_DOCS_FILE, _CHUNKS_FILE, _EMB_FILE):
    p.parent.mkdir(parents=True, exist_ok=True)

# 每个切片最多缓存前 N 维，避免 JSON 过大
_PREVIEW_DIMS = 8


def _load_docs() -> dict:
    if not _DOCS_FILE.exists():
        return {}
    return json.loads(_DOCS_FILE.read_text(encoding="utf-8"))


def _rebuild_docs_index():
    """从 chunks_cache 重建 docs_index（处理手动入库后索引缺失的情况）。"""
    chunks = _load_chunks()
    if not chunks:
        return
    docs = _load_docs()
    rebuilt = False
    for doc_id, chunk_texts in chunks.items():
        if doc_id not in docs:
            # doc_id 格式: {timestamp}_{filename}
            # 用最后一个下划线分割
            parts = doc_id.rsplit("_", 1)
            filename = parts[1] if len(parts) > 1 else doc_id
            docs[doc_id] = {
                "filename": filename,
                "status": "ready",
                "chunks": len(chunk_texts),
                "latency_ms": 0,
                "config": {"strategy": "recursive", "chunk_size": 512, "chunk_overlap": 64},
                "error": None,
            }
            rebuilt = True
    if rebuilt:
        _save_docs(docs)


def _save_docs(docs: dict) -> None:
    _DOCS_FILE.write_text(json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_chunks() -> dict:
    if not _CHUNKS_FILE.exists():
        return {}
    return json.loads(_CHUNKS_FILE.read_text(encoding="utf-8"))


def _save_chunks(data: dict) -> None:
    _CHUNKS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_embeddings() -> dict:
    if not _EMB_FILE.exists():
        return {}
    return json.loads(_EMB_FILE.read_text(encoding="utf-8"))


def _save_embeddings(data: dict) -> None:
    _EMB_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 工具 ────────────────────────────────────────────────────────────────────
def _file_ext(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def _valid_types(ext: str) -> bool:
    return ext in ("pdf", "md", "markdown", "txt")


def _truncate_embed(emb: list[float], n: int = _PREVIEW_DIMS) -> list[float]:
    return emb[:n]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return round(dot / (na * nb), 4)


# ── 路由 ────────────────────────────────────────────────────────────────────
@router.get("/stats", response_model=SystemStats)
async def get_stats():
    docs     = _load_docs()
    chunks   = _load_chunks()
    emb      = _load_embeddings()
    store    = get_vector_store()
    emb_dim  = next(iter(emb.values()))[0] if emb else 1024
    if isinstance(emb_dim, list):
        emb_dim = len(emb_dim) if emb_dim else 1024

    total_chunks = sum(d["chunks"] for d in docs.values())
    total_size = 0
    for p in (_CHUNKS_FILE, _EMB_FILE):
        if p.exists():
            total_size += p.stat().st_size

    return SystemStats(
        total_documents=len(docs),
        total_chunks=total_chunks,
        embedding_dimension=emb_dim,
        total_size_kb=round(total_size, 1),
    )


@router.post("/documents/{doc_id}/preview", response_model=ChunksPreviewResponse)
async def preview_rechunk(doc_id: str, req: RechunkRequest):
    """预览新参数下的切片结果，不写入向量库，不消耗 embedding。"""
    docs = _load_docs()
    if doc_id not in docs:
        raise HTTPException(404, "文档不存在")

    doc_cfg = docs[doc_id]
    filename = doc_cfg["filename"]

    search_dirs = [Path("data/test_docs"), Path("data")]
    src_path = None
    for d in search_dirs:
        found = list(d.glob(filename))
        if found:
            src_path = found[0]
            break
    if src_path is None:
        raise HTTPException(404, f"未找到源文件: {filename}")

    text = load(src_path)
    chunks = split_text(
        text,
        doc_name=filename,
        chunk_size=req.chunk_size,
        chunk_overlap=req.chunk_overlap,
        strategy=req.strategy,
    )
    if not chunks:
        raise ValueError("切片后无有效内容")

    previews = []
    co = req.chunk_overlap
    for i, c in enumerate(chunks):
        previews.append(DocChunkPreview(
            index=i,
            chunk_id=f"{filename}-{i}",
            text=c.text,
            length=len(c.text),
            overlap_with_next=min(co, len(c.text)),
        ))
    return ChunksPreviewResponse(
        doc_id=doc_id,
        filename=filename,
        total_chunks=len(chunks),
        strategy=req.strategy,
        chunk_size=req.chunk_size,
        chunk_overlap=req.chunk_overlap,
        chunks=previews,
    )


@router.post("/upload", response_model=dict)
async def upload(file: UploadFile = File(...)):
    ext = _file_ext(file.filename)
    if not _valid_types(ext):
        raise HTTPException(400, f"不支持的文件类型: .{ext}，支持 PDF / MD / TXT")

    docs      = _load_docs()
    doc_id    = f"{datetime.now().isoformat(timespec='seconds')}_{file.filename}"
    # 先标记为 indexing，入库完成后更新
    docs[doc_id] = {
        "filename": file.filename,
        "status": "indexing",
        "chunks": 0,
        "latency_ms": 0,
        "config": {"strategy": "recursive", "chunk_size": 512, "chunk_overlap": 64},
        "error": None,
    }
    _save_docs(docs)
    return {"id": doc_id, "filename": file.filename, "status": "indexing"}


@router.post("/ingest/{doc_id}", response_model=DocInfo)
async def trigger_ingest(doc_id: str):
    """触发入库并缓存切片文本供详情展示。"""
    docs = _load_docs()
    if doc_id not in docs:
        raise HTTPException(404, "文档不存在")
    doc_cfg = docs[doc_id]
    filename = doc_cfg["filename"]

    search_dirs = [Path("data/test_docs"), Path("data")]
    src_path = None
    for d in search_dirs:
        found = list(d.glob(filename))
        if found:
            src_path = found[0]
            break
    if src_path is None:
        raise HTTPException(404, f"未找到源文件: {filename}")

    cfg = doc_cfg.get("config", {})
    result = ingest_document(
        src_path,
        chunk_size=cfg.get("chunk_size", 512),
        chunk_overlap=cfg.get("chunk_overlap", 64),
        strategy=cfg.get("strategy", "recursive"),
    )

    if result.success:
        _save_chunks({doc_id: result.chunk_texts})
        docs[doc_id].update({
            "status": "ready",
            "chunks": result.chunks,
            "latency_ms": round(result.latency_ms, 1),
            "error": None,
        })
    else:
        docs[doc_id]["status"] = "failed"
        docs[doc_id]["error"] = "; ".join(result.errors) if result.errors else "未知错误"
    _save_docs(docs)

    return DocInfo(
        id=doc_id,
        filename=docs[doc_id]["filename"],
        chunks=docs[doc_id]["chunks"],
        status=docs[doc_id]["status"],
    )


@router.get("/documents/{doc_id}/detail", response_model=DocDetail)
async def get_doc_detail(doc_id: str):
    docs          = _load_docs()
    if doc_id not in docs:
        raise HTTPException(404, "文档不存在")
    doc_cfg       = docs[doc_id]
    chunks_dict   = _load_chunks()
    emb_dict      = _load_embeddings()

    return DocDetail(
        id=doc_id,
        filename=doc_cfg["filename"],
        status=doc_cfg["status"],
        chunks=doc_cfg["chunks"],
        latency_ms=doc_cfg.get("latency_ms", 0),
        config=DocConfig(**doc_cfg.get("config", {})),
        error=doc_cfg.get("error"),
        embeddings=[_truncate_embed(e) for e in emb_dict.get(doc_id, [])],
    )


@router.get("/documents/{doc_id}/chunks", response_model=ChunksPreviewResponse)
async def get_chunks_preview(doc_id: str):
    docs = _load_docs()
    if doc_id not in docs:
        raise HTTPException(404, "文档不存在")
    doc_cfg = docs[doc_id]
    cfg = doc_cfg.get("config", {})

    # 优先从缓存读取，否则从向量库懒加载
    chunks_dict = _load_chunks()
    doc_chunks = chunks_dict.get(doc_id, [])

    if not doc_chunks:
        # 懒加载：从向量库获取原文
        store = get_vector_store()
        all_results = store._collection.get(include=["documents", "metadatas"])
        doc_ids = all_results["ids"]
        doc_texts = all_results["documents"]
        doc_metas = all_results["metadatas"]
        # 筛选当前文档的切片
        filtered_ids = [did for did, meta in zip(doc_ids, doc_metas) if meta.get("doc_name") == doc_cfg["filename"]]
        filtered_texts = [txt for txt, meta in zip(doc_texts, doc_metas) if meta.get("doc_name") == doc_cfg["filename"]]
        doc_chunks = filtered_texts
        # 回填缓存
        chunks_dict[doc_id] = doc_chunks
        _save_chunks(chunks_dict)

    total = len(doc_chunks)
    co = cfg.get("chunk_overlap", 64)
    previews = []
    for i, txt in enumerate(doc_chunks):
        overlap = min(co, len(txt))
        previews.append(DocChunkPreview(
            index=i,
            chunk_id=f"{doc_cfg['filename']}-{i}",
            text=txt,
            length=len(txt),
            overlap_with_next=overlap,
        ))
    return ChunksPreviewResponse(
        doc_id=doc_id,
        filename=doc_cfg["filename"],
        total_chunks=total,
        strategy=cfg.get("strategy", "recursive"),
        chunk_size=cfg.get("chunk_size", 512),
        chunk_overlap=cfg.get("chunk_overlap", 64),
        chunks=previews,
    )


@router.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    if req.stream:
        return StreamingResponse(
            _sse_stream(req),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )
    answer = ""
    async for event in _sse_stream(req):
        payload = json.loads(event.removeprefix("data: "))
        if payload["type"] == "token":
            answer = payload["data"]
    return QueryResponse(answer=answer, latency_ms=0.0)


async def _sse_stream(req: QueryRequest) -> AsyncGenerator[str, None]:
    """纯向量检索：问题 → embedding → ChromaDB top-k → source 事件流。"""
    t0 = time.perf_counter()
    q_vec = get_embedder().encode([req.question])[0]
    results = get_vector_store().search(q_vec, top_k=req.top_k)

    for r in results:
        payload = json.dumps({
            "type": "source",
            "data": {
                "doc_name": r.doc_name,
                "text": r.text,
                "score": round(r.score, 4),
            },
        }, ensure_ascii=False)
        yield f"data: {payload}\n\n"

    elapsed = (time.perf_counter() - t0) * 1000
    if results:
        answer = (
            f"🔍 检索到 {len(results)} 个相关切片（耗时 {elapsed:.0f} ms，"
            f"最高相似度 {results[0].score:.2%}）。"
            "配置 LLM 后将生成完整回答 —— 见 Phase 3。"
        )
    else:
        answer = "未检索到相关内容，请先上传并入库文档。"
    yield (f'data: {json.dumps({"type": "token", "data": answer}, ensure_ascii=False)}\n\n')
    yield 'data: {"type": "done", "data": null}\n\n'


@router.post("/documents/{doc_id}/rechunk", response_model=RechunkResult)
async def rechunk_document(doc_id: str, req: RechunkRequest):
    """用新参数重新切片，全量重算 embedding（切法变了切片内容必然不同）。"""
    docs = _load_docs()
    if doc_id not in docs:
        raise HTTPException(404, "文档不存在")

    doc_cfg = docs[doc_id]
    filename = doc_cfg["filename"]
    old_config = DocConfig(**doc_cfg.get("config", {}))

    # 找到源文件
    search_dirs = [Path("data/test_docs"), Path("data")]
    src_path = None
    for d in search_dirs:
        found = list(d.glob(filename))
        if found:
            src_path = found[0]
            break
    if src_path is None:
        raise HTTPException(404, f"未找到源文件: {filename}")

    t0 = time.perf_counter()

    try:
        # 1. 删除旧向量
        store = get_vector_store()
        store.delete(filename)

        # 2. 删除旧缓存
        _save_chunks({k: v for k, v in _load_chunks().items() if k != doc_id})
        _save_embeddings({k: v for k, v in _load_embeddings().items() if k != doc_id})

        # 3. 重新切分
        from src.ingestion.embedder import get_embedder
        text = load(src_path)
        chunks = split_text(
            text,
            doc_name=filename,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
            strategy=req.strategy,
        )
        if not chunks:
            raise ValueError("切片后无有效内容")

        # 4. 编码（切法变了，无法复用旧 embedding）
        new_texts = [c.text for c in chunks]
        embeddings = get_embedder().encode(new_texts)

        # 5. 写入
        chunk_ids = store.add(filename, new_texts, embeddings)
        _save_chunks({doc_id: new_texts})
        _save_embeddings({doc_id: [_truncate_embed(e) for e in embeddings]})

        new_config = DocConfig(
            strategy=req.strategy,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
        )
        latency_ms = (time.perf_counter() - t0) * 1000

        docs[doc_id].update({
            "status": "ready",
            "chunks": len(chunk_ids),
            "latency_ms": round(latency_ms, 1),
            "config": {"strategy": req.strategy, "chunk_size": req.chunk_size, "chunk_overlap": req.chunk_overlap},
            "error": None,
        })
        _save_docs(docs)

        return RechunkResult(
            doc_id=doc_id,
            filename=filename,
            old_chunks=doc_cfg.get("chunks", 0),
            new_chunks=len(chunk_ids),
            old_config=old_config,
            new_config=new_config,
            latency_ms=round(latency_ms, 1),
            success=True,
            reused_embeddings=0,
            new_embeddings=len(chunk_ids),
        )
    except Exception as e:
        docs[doc_id]["status"] = "failed"
        docs[doc_id]["error"] = str(e)
        _save_docs(docs)
        return RechunkResult(
            doc_id=doc_id,
            filename=filename,
            old_chunks=doc_cfg.get("chunks", 0),
            new_chunks=0,
            old_config=old_config,
            new_config=DocConfig(strategy=req.strategy, chunk_size=req.chunk_size, chunk_overlap=req.chunk_overlap),
            latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            success=False,
            error=str(e),
        )


@router.get("/documents", response_model=list[DocInfo])
async def list_documents():
    _rebuild_docs_index()
    docs = _load_docs()
    return [
        DocInfo(
            id=d_id,
            filename=d["filename"],
            chunks=d.get("chunks", 0),
            status=d.get("status", "unknown"),
        )
        for d_id, d in docs.items()
    ]


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    docs     = _load_docs()
    if doc_id not in docs:
        raise HTTPException(404, "文档不存在")
    store    = get_vector_store()
    store.delete(docs[doc_id]["filename"])  # 删除向量库中对应文档
    del docs[doc_id]
    _save_docs(docs)
    return {"ok": True}
