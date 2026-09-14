from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# 检索特性开关；None（不传）= 默认全开除 rerank，显式传 = 只开列出的
FeatureName = Literal["routing", "keywords", "decompose", "stepback", "hyde", "rewrite", "rerank", "graph"]

# 重排策略；None（不传）= 用环境变量 RERANK_STRATEGY，默认 rrf
RerankStrategy = Literal["rrf", "cross", "llm", "colbert"]

# 检索范式。pipeline = 现有单轮多通道管线；agent = Agentic 自主多轮循环。
# Agentic 是编排层而非检索通道，故用顶层 mode 而非塞进 features。
QueryMode = Literal["pipeline", "agent"]


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(5, ge=1, le=50)
    conversation_id: str | None = Field(None, min_length=1, max_length=100)
    # 元数据过滤（JSONB 包含）：如 {"page": 5}、{"figure": true}；None 表示不过滤
    filters: dict[str, Any] | None = Field(None, max_length=8)
    # 上限须与 FeatureName 选项数一致（routing/keywords/decompose/stepback/hyde/rewrite/rerank/graph = 8）；
    # 加入新特性时这里要同步，否则全选会被 422 拒掉
    features: list[FeatureName] | None = Field(None, max_length=8)
    # 请求级重排策略覆盖；None 时回退环境变量
    rerank_strategy: RerankStrategy | None = None
    # 检索范式；默认 pipeline，行为与接入 Agentic 前完全一致
    mode: QueryMode = "pipeline"
    # agent 模式下的最大步数（仅 agent 生效）
    max_steps: int = Field(6, ge=1, le=12)
    # 请求检索 trace（检视面板用）。默认关闭，关闭时检索路径零额外开销
    debug: bool = False


class Source(BaseModel):
    doc_name: str
    chunk_index: int | None = None
    page: int | None = None
    text: str
    score: float | None = None  # 余弦相似度（1 - distance）


class ChatMessage(BaseModel):
    id: str
    role: str
    content: str
    sources: list[Source] = []
    created_at: str


class ConversationSummary(BaseModel):
    id: str
    title: str
    message_count: int
    updated_at: str


class TraceChannel(BaseModel):
    """单条检索通道的贡献量。"""

    name: str  # 机器名，如 routing / keywords / vector / hyde / graph
    label: str  # 展示名
    hits: int  # 该通道返回的块数（routing 为命中的文档数）
    detail: str | None = None  # 补充说明，如「已兜底全局」


class TraceSkip(BaseModel):
    """请求了但未真正生效的特性，附原因。"""

    name: str
    reason: str


class TracePlan(BaseModel):
    """LLM 检索规划的输出。"""

    subs: list[str] = Field(default_factory=list)
    step_back: str | None = None
    hyde: str | None = None
    queries: list[str] = Field(default_factory=list)  # 实际参与检索的查询集合
    # 确定性 query 改写的产物（去后缀/归一法条/拼实体词）；未生效时为 None
    rewritten: str | None = None


class TraceRouting(BaseModel):
    """路由层的判定细节。"""

    routed_docs: int = 0
    top_score: float = 0.0
    fallback: bool = False  # 是否追加了全局向量兜底
    min_score: float = 0.0


class TraceParams(BaseModel):
    """本次请求实际使用的检索参数。"""

    top_k: int = 0
    filters: dict[str, Any] = Field(default_factory=dict)
    rerank_strategy: str | None = None


class TraceFusion(BaseModel):
    """RRF 融合与重排的规模变化。"""

    channels: int = 0
    pre_merge: int = 0  # 融合前去重块数
    post_merge: int = 0  # 融合后保留块数
    rerank: str | None = None  # 重排策略，未启用为 None
    final: int = 0


class TraceTimings(BaseModel):
    """耗时分解（毫秒）。"""

    plan_ms: float = 0.0
    retrieve_ms: float = 0.0
    generate_ms: float = 0.0


class AgentStep(BaseModel):
    """Agent 循环中的一步：Thought → 工具(参数) → 观测。"""

    step: int
    thought: str | None = None  # 模型的推理文本，模型未输出则为 None
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    observation: str | None = None  # 本步观测摘要（回灌给下一步 + 前端展示）
    new_chunks: int = 0  # 本步新增证据数（判断边际收益）
    error: str | None = None
    latency_ms: float = 0.0


class AgentTrace(BaseModel):
    """Agentic 循环的过程快照，仅 mode=agent 且成功时返回。"""

    steps: list[AgentStep] = Field(default_factory=list)
    termination: str | None = None  # answered | budget | max_steps | stagnant | error
    budget: dict[str, Any] = Field(default_factory=dict)
    evidence_chunks: int = 0
    tools: list[str] = Field(default_factory=list)


class QueryTrace(BaseModel):
    """检索过程快照，仅在 debug=true 时返回。"""

    features: list[str] = Field(default_factory=list)  # 请求的特性集
    applied: list[str] = Field(default_factory=list)  # 真正生效的特性集
    skipped: list[TraceSkip] = Field(default_factory=list)  # 请求了但空转的特性
    params: TraceParams = Field(default_factory=TraceParams)
    plan: TracePlan = Field(default_factory=TracePlan)
    routing: TraceRouting = Field(default_factory=TraceRouting)
    channels: list[TraceChannel] = Field(default_factory=list)
    fusion: TraceFusion = Field(default_factory=TraceFusion)
    timings: TraceTimings = Field(default_factory=TraceTimings)
    agent: "AgentTrace | None" = None  # 仅 mode=agent 且未降级时非空
    # 请求了 agent 但降级为管线时的原因（LLM 失败 / 无证据 / 一步收敛 …）；未降级时为 None
    agent_degraded_reason: str | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[Source] = []
    figures: list["Figure"] = []  # 命中图片切片时按页列出的嵌入图（url 按需拉取 PNG）
    latency_ms: float = 0.0
    conversation_id: str | None = None
    trace: "QueryTrace | None" = None  # 仅 debug=true 时返回


class Figure(BaseModel):
    page: int
    width: int
    height: int
    url: str
    data_uri: str | None = None  # 兼容旧客户端；新路径只填 url


class DocInfo(BaseModel):
    id: str
    filename: str
    chunks: int = 0
    status: str = "ready"  # pending | indexing | ready | failed
    created_at: str | None = None
    updated_at: str | None = None


class DocConfig(BaseModel):
    strategy: str = "recursive"  # Deprecated; the Markdown splitter has one strategy.
    chunk_size: int = 512
    chunk_overlap: int = 64


class RechunkRequest(BaseModel):
    chunk_size: int = Field(512, ge=64, le=4096)
    chunk_overlap: int = Field(64, ge=0, lt=4096)
    strategy: str = "recursive"  # Deprecated; accepted for client compatibility.

    @model_validator(mode="after")
    def validate_overlap(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")
        return self


class RechunkResult(BaseModel):
    doc_id: str
    filename: str
    old_chunks: int
    new_chunks: int
    old_config: DocConfig
    new_config: DocConfig
    latency_ms: float
    success: bool
    error: str | None = None


class DocChunkPreview(BaseModel):
    index: int
    chunk_id: str
    text: str
    length: int
    page: int | None = None
    overlap_with_next: int = 0  # 与下一块的 overlap 字符数


class ChunksPreviewResponse(BaseModel):
    doc_id: str
    filename: str
    total_chunks: int
    strategy: str = "recursive"  # Deprecated; retained for API compatibility.
    chunk_size: int
    chunk_overlap: int
    chunks: list[DocChunkPreview]


class SystemStats(BaseModel):
    total_documents: int
    total_chunks: int
    embedding_dimension: int
    total_size_kb: float


class LLMProviderIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    model: str = Field(..., min_length=1)
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    timeout: float = Field(60, ge=1, le=600)
    active: bool = False


class LLMProviderOut(LLMProviderIn):
    id: str
    created_at: str


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"


# ---- 健康检查：反映 DB / LLM / Embedding 的真实可用性 ----


class HealthDatabase(BaseModel):
    ok: bool
    latency_ms: float | None = None
    error: str | None = None


class HealthLLM(BaseModel):
    configured: bool
    source: str  # database | env | none
    name: str | None = None
    model: str | None = None
    # 运行时真实可用性：None = 尚未验证（进程刚起或还没调用过），False = 最近一次调用失败
    ok: bool | None = None
    reason: str | None = None
    hint: str | None = None
    status_code: int | None = None
    checked_at: str | None = None


class HealthEmbedding(BaseModel):
    provider: str
    model: str
    dimension: int


class HealthStatusResponse(BaseModel):
    status: str  # ok | degraded
    version: str
    database: HealthDatabase
    llm: HealthLLM
    embedding: HealthEmbedding
    documents: int = 0
    chunks: int = 0


# ---- 图谱浏览 ----


class GraphStats(BaseModel):
    entities: int
    relations: int
    links: int
    orphan_entities: int
    kinds: dict[str, int] = Field(default_factory=dict)


class GraphEntity(BaseModel):
    entity_id: str
    name: str
    norm: str
    kind: str
    description: str
    mentions: int


class GraphEdge(BaseModel):
    rel: str
    norm_rel: str
    weight: float
    entity_id: str  # 对端实体
    name: str
    kind: str
    evidence_chunk_id: str | None = None


class GraphChunkRef(BaseModel):
    chunk_id: str
    document_id: str
    doc_name: str
    chunk_index: int
    text: str
    page: int | None = None


class GraphEntityDetail(BaseModel):
    entity: GraphEntity
    out_edges: list[GraphEdge] = Field(default_factory=list)
    in_edges: list[GraphEdge] = Field(default_factory=list)
    evidence: list[GraphChunkRef] = Field(default_factory=list)


class GraphNode(BaseModel):
    entity_id: str
    name: str
    kind: str
    mentions: int
    hop: int


class GraphLink(BaseModel):
    src: str
    dst: str
    rel: str
    norm_rel: str
    weight: float


class GraphSubgraph(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphLink] = Field(default_factory=list)


# ---- 评测 / 消融 ----


class EvalCase(BaseModel):
    id: int
    question: str
    expected_refs: str
    reference_answer: str | None = None


class EvalCaseIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    expected_refs: str = Field(..., min_length=1, max_length=2000)
    reference_answer: str | None = Field(None, max_length=4000)


class EvalConfigIn(BaseModel):
    label: str = Field(..., min_length=1, max_length=64)
    features: list[FeatureName] | None = None  # None = 默认特性集


class EvalRunRequest(BaseModel):
    k: int = Field(5, ge=1, le=20)
    configs: list[EvalConfigIn] | None = Field(None, max_length=12)


class EvalRow(BaseModel):
    label: str
    hit_at_k: float
    mrr: float


class EvalRunResult(BaseModel):
    k: int
    case_count: int
    rows: list[EvalRow] = Field(default_factory=list)
