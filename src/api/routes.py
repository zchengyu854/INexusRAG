from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response, StreamingResponse

from src.api.schemas import (
    ChunksPreviewResponse,
    ChatMessage,
    ConversationSummary,
    DocChunkPreview,
    DocConfig,
    DocInfo,
    EvalCase,
    EvalCaseIn,
    EvalRunRequest,
    EvalRunResult,
    EvalRow,
    GraphChunkRef,
    GraphEdge,
    GraphEntity,
    GraphEntityDetail,
    GraphLink,
    GraphNode,
    GraphStats,
    GraphSubgraph,
    HealthDatabase,
    HealthEmbedding,
    HealthLLM,
    HealthStatusResponse,
    AgentTrace,
    QueryRequest,
    QueryResponse,
    QueryTrace,
    RechunkRequest,
    RechunkResult,
    Source,
    SystemStats,
    LLMProviderIn,
    LLMProviderOut,
)
from src.config import embedding_dimension
from src.evaluation import (
    add_case as add_eval_case,
    default_eval_configs,
    load_cases as load_eval_cases,
    run_ablation,
)
from src.ingestion.embedder import get_embedder
from src.ingestion.splitter import split_document
from src.llm.client import LLMClient, get_llm
from src.retrieval import index_document_route, multi_query_search
from src.storage.database import (
    create_document,
    delete_document as delete_document_record,
    entity_edges,
    entity_evidence_chunks,
    get_chunks as get_database_chunks,
    get_document,
    get_entity,
    graph_kind_counts,
    graph_stats,
    graph_subgraph,
    list_documents as list_database_documents,
    list_conversations,
    replace_chunks,
    search_entities_by_text,
    stats as database_stats,
    update_document,
    delete_messages,
    get_messages,
    save_message,
    list_llm_providers as list_llm_provider_rows,
    get_llm_provider as get_llm_provider_row,
    get_active_llm_provider as get_active_llm_provider_row,
    upsert_llm_provider as upsert_llm_provider_row,
    activate_llm_provider as activate_llm_provider_row,
    delete_llm_provider as delete_llm_provider_row,
)

router = APIRouter(prefix="/api")
_UPLOAD_DIR = Path("data/uploads")
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _file_ext(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def _valid_types(ext: str) -> bool:
    return ext in ("pdf", "md", "markdown", "txt")


def _doc_config(doc: dict) -> DocConfig:
    return DocConfig(**(doc.get("config") or {}))


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[union-attr]
    return str(value)


def _doc_info(doc: dict) -> DocInfo:
    return DocInfo(
        id=doc["id"],
        filename=doc["filename"],
        chunks=doc.get("chunks", 0),
        status=doc.get("status", "unknown"),
        created_at=_iso(doc.get("created_at")),
        updated_at=_iso(doc.get("updated_at")),
    )


def _source_path(doc: dict) -> Path:
    stored = Path(doc.get("source_path", ""))
    if stored.exists():
        return stored
    raise HTTPException(404, f"未找到源文件: {doc['filename']}")


def _read_and_split(doc: dict, config: DocConfig):
    chunks = split_document(
        _source_path(doc),
        doc_name=doc["filename"],
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
    )
    if not chunks:
        raise ValueError("切片后无有效内容")
    return chunks


def _chunk_previews(doc: dict, chunks: list[dict], config: DocConfig) -> list[DocChunkPreview]:
    return [
        DocChunkPreview(
            index=chunk["chunk_index"],
            chunk_id=f"{doc['filename']}-{chunk['chunk_index']}",
            text=chunk["text"],
            length=len(chunk["text"]),
            overlap_with_next=min(config.chunk_overlap, len(chunk["text"])),
            page=(chunk.get("metadata") or {}).get("page"),
        )
        for chunk in chunks
    ]


@router.get("/stats", response_model=SystemStats)
def get_stats():
    current = database_stats()
    return SystemStats(
        total_documents=current["total_documents"],
        total_chunks=current["total_chunks"],
        embedding_dimension=current["embedding_dimension"],
        total_size_kb=round(current["text_bytes"] / 1024, 1),
    )


def _ingest_document(doc_id: str) -> None:
    doc = get_document(doc_id)
    if not doc:
        return
    config = _doc_config(doc)
    try:
        chunks = _read_and_split(doc, config)
        texts = [chunk.text for chunk in chunks]
        embeddings = get_embedder().encode(texts)
        replace_chunks(doc_id, doc["filename"], texts, embeddings, [chunk.metadata or {} for chunk in chunks])
        index_document_route(doc_id, doc["filename"], chunks, get_embedder().encode)
        update_document(
            doc_id,
            status="ready",
            chunks=len(texts),
            latency_ms=0,
            config=config.model_dump(),
            error=None,
        )
        _maybe_build_graph(doc_id)
    except Exception as exc:
        update_document(doc_id, status="failed", error=str(exc))


def _auto_build_graph_enabled() -> bool:
    return os.getenv("AUTO_BUILD_GRAPH", "").strip().lower() in {"1", "true", "yes"}


def _maybe_build_graph(doc_id: str) -> None:
    """入库/重切后可选按文档增量建图（需 AUTO_BUILD_GRAPH=1）；失败不影响文档 ready。"""
    if not _auto_build_graph_enabled():
        return
    try:
        from src.graph import build_document

        n = build_document(doc_id, resume=True)
        print(f"[graph] auto-build doc={doc_id} chunks={n}")
    except Exception as exc:
        print(f"[graph] auto-build failed doc={doc_id}: {exc}")


def _build_graph_job(doc_id: str) -> None:
    """后台按文档建图（不 wipe 全库）；供 API 显式触发。"""
    try:
        from src.graph import build_document

        n = build_document(doc_id, resume=True)
        print(f"[graph] build doc={doc_id} chunks={n}")
    except Exception as exc:
        print(f"[graph] build failed doc={doc_id}: {exc}")


@router.post("/upload", response_model=dict)
async def upload(file: UploadFile = File(...)):
    filename = Path(file.filename or "").name
    ext = _file_ext(filename)
    if not filename or not _valid_types(ext):
        raise HTTPException(400, "不支持的文件类型，支持 PDF / MD / TXT")

    doc_id = f"{datetime.now().isoformat(timespec='seconds')}_{uuid.uuid4().hex[:8]}"
    destination = _UPLOAD_DIR / f"{doc_id}_{filename}"
    content = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, "文件不能超过 50 MB")
    destination.write_bytes(content)
    try:
        create_document(doc_id, filename, str(destination))
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return {"id": doc_id, "filename": filename, "status": "indexing"}


@router.post("/ingest/{doc_id}", response_model=DocInfo)
async def trigger_ingest(doc_id: str, background_tasks: BackgroundTasks):
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    update_document(doc_id, status="indexing", error=None)
    background_tasks.add_task(_ingest_document, doc_id)
    return _doc_info(get_document(doc_id))


@router.get("/documents", response_model=list[DocInfo])
async def list_documents():
    return [_doc_info(doc) for doc in list_database_documents()]


@router.get("/documents/{doc_id}/chunks", response_model=ChunksPreviewResponse)
async def get_chunks_preview(doc_id: str):
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    config = _doc_config(doc)
    chunks = get_database_chunks(doc_id)
    return ChunksPreviewResponse(
        doc_id=doc_id,
        filename=doc["filename"],
        total_chunks=len(chunks),
        strategy="recursive",
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        chunks=_chunk_previews(doc, chunks, config),
    )


@router.post("/documents/{doc_id}/preview", response_model=ChunksPreviewResponse)
def preview_rechunk(doc_id: str, request: RechunkRequest):
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    config = DocConfig(**request.model_dump())
    try:
        chunks = _read_and_split(doc, config)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    previews = [
        DocChunkPreview(
            index=index,
            chunk_id=f"{doc['filename']}-{index}",
            text=chunk.text,
            length=len(chunk.text),
            page=(chunk.metadata or {}).get("page"),
            overlap_with_next=min(config.chunk_overlap, len(chunk.text)),
        )
        for index, chunk in enumerate(chunks)
    ]
    return ChunksPreviewResponse(
        doc_id=doc_id,
        filename=doc["filename"],
        total_chunks=len(previews),
        strategy="recursive",
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        chunks=previews,
    )


@router.post("/documents/{doc_id}/rechunk", response_model=RechunkResult)
def rechunk_document(doc_id: str, request: RechunkRequest):
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    old_config = _doc_config(doc)
    new_config = DocConfig(**request.model_dump())
    t0 = time.perf_counter()
    try:
        chunks = _read_and_split(doc, new_config)
        texts = [chunk.text for chunk in chunks]
        # Prepare embeddings before replacing anything in PostgreSQL.
        embeddings = get_embedder().encode(texts)
        replace_chunks(doc_id, doc["filename"], texts, embeddings, [chunk.metadata or {} for chunk in chunks])
        index_document_route(doc_id, doc["filename"], chunks, get_embedder().encode)
        latency_ms = (time.perf_counter() - t0) * 1000
        update_document(
            doc_id,
            status="ready",
            chunks=len(texts),
            latency_ms=round(latency_ms, 1),
            config=new_config.model_dump(),
            error=None,
        )
        _maybe_build_graph(doc_id)
        return RechunkResult(
            doc_id=doc_id,
            filename=doc["filename"],
            old_chunks=doc["chunks"],
            new_chunks=len(texts),
            old_config=old_config,
            new_config=new_config,
            latency_ms=round(latency_ms, 1),
            success=True,
        )
    except Exception as exc:
        update_document(doc_id, status=doc["status"], error=str(exc))
        return RechunkResult(
            doc_id=doc_id,
            filename=doc["filename"],
            old_chunks=doc["chunks"],
            new_chunks=0,
            old_config=old_config,
            new_config=new_config,
            latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            success=False,
            error=str(exc),
        )


@router.post("/documents/{doc_id}/build-graph", response_model=dict)
async def build_document_graph(doc_id: str, background_tasks: BackgroundTasks):
    """按文档增量建图（不 wipe 全库）。入库后也可设 AUTO_BUILD_GRAPH=1 自动触发。"""
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    if doc.get("status") != "ready":
        raise HTTPException(400, "文档未就绪，请先完成入库")
    background_tasks.add_task(_build_graph_job, doc_id)
    return {
        "doc_id": doc_id,
        "status": "building",
        "message": "已在后台按文档增量建图（resume，不清空其他文档的图）",
    }


@router.get("/conversations", response_model=list[ConversationSummary])
async def conversations():
    return [
        ConversationSummary(
            id=conversation["id"],
            title=conversation["title"][:80],
            message_count=conversation["message_count"],
            updated_at=conversation["updated_at"].isoformat(),
        )
        for conversation in list_conversations()
    ]


@router.get("/conversations/{conversation_id}/messages", response_model=list[ChatMessage])
async def conversation_history(conversation_id: str):
    if not conversation_id.strip():
        raise HTTPException(400, "conversation_id 不能为空")
    return [
        ChatMessage(
            id=message["id"],
            role=message["role"],
            content=message["content"],
            sources=[Source(**source) for source in (message.get("sources") or [])],
            created_at=message["created_at"].isoformat(),
        )
        for message in get_messages(conversation_id)
    ]


@router.delete("/conversations/{conversation_id}/messages")
async def clear_conversation(conversation_id: str):
    delete_messages(conversation_id)
    return {"ok": True}


def _run_agent_or_none(
    request: QueryRequest,
    on_step: Callable[[dict], None] | None = None,
) -> dict | None:
    """Agentic 检索；任何异常都静默返回 None，由调用方退回单轮管线（绝不整体失败）。"""
    try:
        from src.agent import run_agent

        return run_agent(
            request.question,
            top_k=request.top_k,
            filters=request.filters,
            max_steps=request.max_steps,
            features=request.features,
            rerank_strategy=request.rerank_strategy,
            on_step=on_step,
        )
    except Exception:  # agentic 只是锦上添花，出错必须能安静退回已验证的单轮管线
        return None


def _list_figures(results: list[dict]) -> list[dict]:
    figures: list[dict] = []
    fig_pages: dict[str, list[int]] = {}
    for result in results:
        meta = result.get("metadata") or {}
        if meta.get("figure") and result.get("document_id") and meta.get("page"):
            fig_pages.setdefault(result["document_id"], []).append(int(meta["page"]))
    if not fig_pages:
        return figures
    try:
        from src.ingestion.loaders import list_page_images
        for doc_id, page_list in fig_pages.items():
            doc = get_document(doc_id)
            src = (doc or {}).get("source_path", "")
            if not src or not Path(src).exists():
                continue
            for img in list_page_images(src, page_list):
                figures.append({
                    "page": img["page"],
                    "width": img["width"],
                    "height": img["height"],
                    "url": (
                        f"/api/documents/{doc_id}/pages/{img['page']}"
                        f"/images/{img['index']}"
                    ),
                })
    except Exception:
        return figures
    return figures


def _run_query(
    request: QueryRequest,
    emit: Callable[[str, dict], None] | None = None,
) -> QueryResponse:
    """问答主路径。emit(event, payload) 用于 SSE；缺省时行为与原来的同步 /query 一致。"""

    def _emit(event: str, payload: dict | None = None) -> None:
        if emit is not None:
            emit(event, payload or {})

    t0 = time.perf_counter()
    conversation_id = request.conversation_id or str(uuid.uuid4())
    history = get_messages(conversation_id, limit=10)
    save_message(conversation_id, "user", request.question)

    if database_stats()["total_chunks"] == 0:
        answer = "未检索到相关内容，请先上传并入库文档。"
        save_message(conversation_id, "assistant", answer)
        response = QueryResponse(
            answer=answer,
            sources=[],
            latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            conversation_id=conversation_id,
        )
        _emit("done", response.model_dump())
        return response

    results: list[dict] = []
    trace_data: dict | None = None
    agent_trace: dict | None = None

    if request.mode == "agent":
        _emit("stage", {"stage": "agent", "detail": "自主多轮检索"})
        outcome = _run_agent_or_none(request, on_step=lambda rec: _emit("agent_step", rec))
        if outcome is not None:
            results, agent_trace = outcome["results"], outcome["trace"]

    if not results:  # pipeline 模式，或 agent 未产出（静默降级）
        _emit("stage", {"stage": "retrieve", "detail": "检索知识库"})
        raw = multi_query_search(
            request.question,
            top_k=request.top_k,
            filters=request.filters,
            features=request.features,
            rerank_strategy=request.rerank_strategy,
            debug=request.debug,
        )
        if request.debug and isinstance(raw, dict):
            trace_data = raw["trace"]
            results = raw["results"]
        else:
            results = raw
    t_retrieved = time.perf_counter()
    if not results:
        answer = "未检索到相关内容，请先上传并入库文档。"
        save_message(conversation_id, "assistant", answer)
        response = QueryResponse(
            answer=answer,
            sources=[],
            latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            conversation_id=conversation_id,
        )
        _emit("done", response.model_dump())
        return response

    sources = [
        Source(
            doc_name=result["doc_name"],
            chunk_index=result["chunk_index"],
            page=(result.get("metadata") or {}).get("page"),
            text=result["text"],
            score=round(float(result["score"]), 4),
        )
        for result in results
    ]
    figures = _list_figures(results)
    _emit("sources", {
        "sources": [s.model_dump() for s in sources],
        "figures": figures,
    })
    _emit("stage", {"stage": "generate", "detail": "生成回答"})
    generation_error: str | None = None
    try:
        llm = get_llm()
        if emit is not None:
            parts: list[str] = []
            for token in llm.generate_stream(request.question, results, history=history):
                parts.append(token)
                _emit("token", {"text": token})
            answer = "".join(parts).strip() or "模型没有返回内容。"
        else:
            answer = llm.generate(request.question, results, history=history)
    except Exception as exc:
        # 检索已经拿到结果，不应因为 LLM 不可用（key 失效/限流/超时）把整轮问答打成 500：
        # 降级为提示文案 + 保留命中来源，用户仍能看到检索到了什么。
        generation_error = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        answer = (
            "检索已完成，但生成回答时调用大模型失败，下面仅列出命中的原文片段。\n\n"
            f"错误：{generation_error}"
        )
        _emit("token", {"text": answer})
    t_generated = time.perf_counter()
    source_data = [source.model_dump() for source in sources]
    save_message(conversation_id, "assistant", answer, source_data)
    latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    trace = None
    if request.debug:
        if trace_data is None:
            trace_data = {}
        trace_data.setdefault("timings", {})["generate_ms"] = round(
            (t_generated - t_retrieved) * 1000, 1
        )
        trace = QueryTrace(**trace_data)
        if agent_trace is not None:
            trace.agent = AgentTrace(**agent_trace)

    response = QueryResponse(
        answer=answer,
        sources=sources,
        figures=figures,
        latency_ms=latency_ms,
        conversation_id=conversation_id,
        trace=trace,
    )
    _emit("done", response.model_dump())
    return response


@router.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    # 同步检索/生成可跑几十秒；扔进线程池，避免堵死事件循环。
    return await run_in_threadpool(_query_sync, request)


def _query_sync(request: QueryRequest) -> QueryResponse:
    return _run_query(request)


@router.post("/query/stream")
async def query_stream(request: QueryRequest):
    """SSE：stage / agent_step / sources / token / done。前端可 AbortController 取消读取。"""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

    def emit(event: str, payload: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (event, payload))

    def produce() -> None:
        try:
            _run_query(request, emit=emit)
        except Exception as exc:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                ("error", {"message": f"{type(exc).__name__}: {exc}"}),
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=produce, daemon=True).start()

    async def events():
        while True:
            item = await queue.get()
            if item is None:
                break
            event, payload = item
            yield f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    source_path = Path(doc["source_path"])
    delete_document_record(doc_id)
    if source_path.exists():
        source_path.unlink()
    return {"ok": True}


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: str):
    """回传原始文件，供文档详情页做原件预览（PDF 可按 #page=N 定位）。"""
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    path = Path(doc["source_path"])
    if not path.exists():
        raise HTTPException(404, "源文件已丢失，请重新上传")
    return FileResponse(path, filename=doc["filename"], content_disposition_type="inline")


@router.get("/documents/{doc_id}/pages/{page}/images/{index}")
def document_page_image(doc_id: str, page: int, index: int):
    """按页按序号回传嵌入图 PNG，避免把 base64 塞进 /query JSON。"""
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    path = Path(doc["source_path"])
    if not path.exists():
        raise HTTPException(404, "源文件已丢失，请重新上传")
    from src.ingestion.loaders import extract_page_image_png

    png = extract_page_image_png(path, page, index)
    if not png:
        raise HTTPException(404, "该页没有对应图片")
    return Response(content=png, media_type="image/png")


# ---- LLM providers：在 UI 中管理并选择 LLM，active 的 provider 驱动 get_llm() ----


def _llm_provider_out(row: dict) -> LLMProviderOut:
    return LLMProviderOut(
        id=row["id"],
        name=row["name"],
        model=row["model"],
        base_url=row["base_url"],
        api_key=row["api_key"],
        timeout=float(row["timeout"]),
        active=bool(row["active"]),
        created_at=row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
    )


@router.get("/llm/providers", response_model=list[LLMProviderOut])
def list_llm_providers():
    return [_llm_provider_out(row) for row in list_llm_provider_rows()]


@router.get("/llm/active")
def active_llm_provider():
    row = get_active_llm_provider_row()
    return {"provider": _llm_provider_out(row) if row else None}


@router.post("/llm/providers", response_model=LLMProviderOut, status_code=200)
def upsert_llm_provider(payload: LLMProviderIn):
    """按 name 插入或更新 provider。"""
    row = upsert_llm_provider_row(payload.model_dump())
    return _llm_provider_out(row)


@router.delete("/llm/providers/{provider_id}")
def delete_llm_provider(provider_id: str):
    if not delete_llm_provider_row(provider_id):
        raise HTTPException(404, "LLM provider 不存在")
    return {"ok": True}


@router.post("/llm/providers/{provider_id}/activate", response_model=LLMProviderOut)
def activate_llm_provider(provider_id: str):
    """将目标 provider 设为 active（互斥）。"""
    row = activate_llm_provider_row(provider_id)
    if row is None:
        raise HTTPException(404, "LLM provider 不存在")
    return _llm_provider_out(row)


@router.post("/llm/providers/{provider_id}/test")
def test_llm_provider(provider_id: str):
    """用该 provider 的配置发起一次最小补全，验证 key/base_url 可用。"""
    row = get_llm_provider_row(provider_id)
    if row is None:
        raise HTTPException(404, "LLM provider 不存在")
    client = LLMClient(
        api_key=row["api_key"],
        base_url=row["base_url"],
        model=row["model"],
        timeout=float(row["timeout"]),
    )
    try:
        if not client.enabled:
            return {"ok": False, "detail": "未设置 API Key"}
        client.generate("Reply with a single word: ok", sources=[])
        return {"ok": True, "detail": "连接成功"}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


# ---- 健康检查：让前端顶部状态条能反映真实可用性，而不是只 ping 到进程 ----


@router.get("/health", response_model=HealthStatusResponse)
def health():
    import os as _os

    t0 = time.perf_counter()
    database = HealthDatabase(ok=True)
    documents = 0
    chunks = 0
    try:
        current = database_stats()
        documents = current["total_documents"]
        chunks = current["total_chunks"]
    except Exception as exc:
        database = HealthDatabase(ok=False, error=str(exc))
    database.latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    try:
        provider_row = get_active_llm_provider_row()
    except Exception:
        provider_row = None
    if provider_row:
        llm = HealthLLM(
            configured=bool(provider_row.get("api_key")),
            source="database",
            name=provider_row.get("name"),
            model=provider_row.get("model"),
        )
    else:
        env_key = _os.getenv("LLM_API_KEY", "").strip()
        llm = HealthLLM(
            configured=bool(env_key),
            source="env" if env_key else "none",
            name=None,
            model=_os.getenv("LLM_MODEL", "gpt-4o-mini"),
        )

    # 不实例化 Embedder：本地模式会加载模型，健康检查不能有此副作用
    provider = _os.getenv("EMBEDDING_PROVIDER", "openai").lower()
    model = (
        _os.getenv("LOCAL_EMBEDDING_MODEL", "BAAI/bge-m3")
        if provider == "local"
        else _os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    )
    embedding = HealthEmbedding(provider=provider, model=model, dimension=embedding_dimension())

    return HealthStatusResponse(
        status="ok" if database.ok else "degraded",
        version="0.1.0",
        database=database,
        llm=llm,
        embedding=embedding,
        documents=documents,
        chunks=chunks,
    )


# ---- 图谱浏览：graph.py 只有 CLI，这里补只读查询能力 ----


@router.get("/graph/stats", response_model=GraphStats)
def graph_stats_endpoint():
    return GraphStats(**graph_stats(), kinds=graph_kind_counts())


@router.get("/graph/search", response_model=list[GraphEntity])
def graph_search(q: str = "", kind: str | None = None, limit: int = 20):
    rows = search_entities_by_text(q, kind=kind, limit=min(max(limit, 1), 100))
    return [GraphEntity(**row) for row in rows]


@router.get("/graph/entities/{entity_id}", response_model=GraphEntityDetail)
def graph_entity_detail(entity_id: str, limit: int = 50):
    row = get_entity(entity_id)
    if not row:
        raise HTTPException(404, "实体不存在")
    edges = entity_edges(entity_id, limit=min(max(limit, 1), 200))
    evidence = entity_evidence_chunks(entity_id, limit=10)
    return GraphEntityDetail(
        entity=GraphEntity(**row),
        out_edges=[GraphEdge(**edge) for edge in edges["out"]],
        in_edges=[GraphEdge(**edge) for edge in edges["in"]],
        evidence=[
            GraphChunkRef(
                chunk_id=item["chunk_id"],
                document_id=item["document_id"],
                doc_name=item["doc_name"],
                chunk_index=item["chunk_index"],
                text=item["text"],
                page=(item.get("metadata") or {}).get("page"),
            )
            for item in evidence
        ],
    )


@router.get("/graph/subgraph", response_model=GraphSubgraph)
def graph_subgraph_view(entity_id: str, hops: int = 2, limit: int = 150):
    data = graph_subgraph([entity_id], hops=min(max(hops, 1), 3), limit=min(max(limit, 1), 400))
    return GraphSubgraph(
        nodes=[GraphNode(**node) for node in data["nodes"]],
        edges=[GraphLink(**edge) for edge in data["edges"]],
    )


# ---- 评测：把 evaluation.py 的消融矩阵暴露给界面 ----


@router.get("/eval/cases", response_model=list[EvalCase])
def eval_cases():
    return [
        EvalCase(
            id=case["id"],
            question=case["question"],
            expected_refs=case["expected_refs"],
            reference_answer=case["reference_answer"],
        )
        for case in load_eval_cases()
    ]


@router.post("/eval/cases", response_model=EvalCase)
def eval_add_case_endpoint(payload: EvalCaseIn):
    case_id = add_eval_case(payload.question, payload.expected_refs, payload.reference_answer)
    return EvalCase(
        id=case_id,
        question=payload.question,
        expected_refs=payload.expected_refs,
        reference_answer=payload.reference_answer,
    )


@router.post("/eval/run", response_model=EvalRunResult)
def eval_run(request: EvalRunRequest):
    """同步跑消融矩阵。评测例与配置数变大时耗时会线性增长，必要时再改后台任务。"""
    cases = load_eval_cases()
    if not cases:
        raise HTTPException(400, "评测集为空，请先添加评测例（或调用 seed-multihop 播种）")
    if request.configs:
        configs: list[tuple] = [
            (item.label, list(item.features) if item.features is not None else None)
            for item in request.configs
        ]
    else:
        configs = default_eval_configs()
    rows = run_ablation(configs, top_k=request.k)
    return EvalRunResult(
        k=request.k,
        case_count=len(cases),
        rows=[EvalRow(label=row["label"], hit_at_k=row["hit@k"], mrr=row["mrr"]) for row in rows],
    )


@router.post("/eval/seed", response_model=dict)
def eval_seed_multihop():
    from src.evaluation import seed_multihop_cases

    return {"added": seed_multihop_cases()}
