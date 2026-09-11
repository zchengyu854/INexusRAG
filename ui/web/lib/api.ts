"use client"

import { API_BASE } from "./constants"

export interface ChatMessage {
  id: string
  role: "user" | "assistant"
  content: string
  sources: Source[]
  created_at: string
}

export interface ConversationSummary {
  id: string
  title: string
  message_count: number
  updated_at: string
}

export interface Doc {
  id: string
  filename: string
  chunks: number
  status: string
  created_at?: string | null
  updated_at?: string | null
}

/** 原件预览地址：PDF 可拼接 #page=N 直接定位到页。 */
export function documentFileUrl(docId: string, page?: number | null): string {
  const base = `${API_BASE}/documents/${encodeURIComponent(docId)}/file`
  return page ? `${base}#page=${page}` : base
}

export interface Chunk {
  index: number
  chunk_id: string
  text: string
  length: number
  overlap_with_next: number
  page?: number
}

export interface DocConfig {
  chunk_size: number
  chunk_overlap: number
}

export interface Source {
  doc_name: string
  chunk_index?: number
  page?: number
  text: string
  score?: number
}

export interface Figure {
  page: number
  width: number
  height: number
  data_uri: string
}

export interface PreviewResult {
  total_chunks: number
  chunks: Chunk[]
}

export interface RechunkResult {
  doc_id: string
  filename: string
  success: boolean
  old_chunks: number
  new_chunks: number
  old_config: DocConfig
  new_config: DocConfig
  latency_ms: number
  error?: string
}

export interface Stats {
  total_documents: number
  total_chunks: number
  embedding_dimension: number
  total_size_kb: number
}

export interface LLMProvider {
  id: string
  name: string
  model: string
  base_url: string
  api_key: string
  timeout: number
  active: boolean
  created_at: string
}

export type LLMProviderDraft = Omit<LLMProvider, "id" | "created_at">

// ---- 检索 trace（仅 debug=true 时后端返回）----

export type RerankStrategy = "rrf" | "cross" | "llm" | "colbert"

export interface TraceChannel {
  name: string
  label: string
  hits: number
  detail?: string | null
}

export interface TraceSkip {
  name: string
  reason: string
}

export interface TracePlan {
  subs: string[]
  step_back: string | null
  hyde: string | null
  queries: string[]
}

export interface TraceRouting {
  routed_docs: number
  top_score: number
  fallback: boolean
  min_score: number
}

export interface TraceParams {
  top_k: number
  filters: Record<string, unknown>
  rerank_strategy: string | null
}

export interface TraceFusion {
  channels: number
  pre_merge: number
  post_merge: number
  rerank: string | null
  final: number
}

export interface TraceTimings {
  plan_ms: number
  retrieve_ms: number
  generate_ms: number
}

export interface QueryTrace {
  features: string[]   // 请求的特性集
  applied: string[]    // 真正生效的特性集
  skipped: TraceSkip[] // 请求了但空转的特性
  params: TraceParams
  plan: TracePlan
  routing: TraceRouting
  channels: TraceChannel[]
  fusion: TraceFusion
  timings: TraceTimings
}

// ---- 健康状态 ----

export interface HealthStatus {
  status: "ok" | "degraded"
  version: string
  database: { ok: boolean; latency_ms?: number | null; error?: string | null }
  llm: { configured: boolean; source: "database" | "env" | "none"; name?: string | null; model?: string | null }
  embedding: { provider: string; model: string; dimension: number }
  documents: number
  chunks: number
}

// ---- 图谱 ----

export interface GraphStats {
  entities: number
  relations: number
  links: number
  orphan_entities: number
  kinds: Record<string, number>
}

export interface GraphEntity {
  entity_id: string
  name: string
  norm: string
  kind: string
  description: string
  mentions: number
}

export interface GraphEdge {
  rel: string
  norm_rel: string
  weight: number
  entity_id: string
  name: string
  kind: string
  evidence_chunk_id?: string | null
}

export interface GraphChunkRef {
  chunk_id: string
  document_id: string
  doc_name: string
  chunk_index: number
  text: string
  page?: number | null
}

export interface GraphEntityDetail {
  entity: GraphEntity
  out_edges: GraphEdge[]
  in_edges: GraphEdge[]
  evidence: GraphChunkRef[]
}

export interface GraphNode {
  entity_id: string
  name: string
  kind: string
  mentions: number
  hop: number
}

export interface GraphLink {
  src: string
  dst: string
  rel: string
  norm_rel: string
  weight: number
}

export interface GraphSubgraph {
  nodes: GraphNode[]
  edges: GraphLink[]
}

// ---- 评测 ----

export interface EvalCase {
  id: number
  question: string
  expected_refs: string
  reference_answer?: string | null
}

export interface EvalRow {
  label: string
  hit_at_k: number
  mrr: number
}

export interface EvalRunResult {
  k: number
  case_count: number
  rows: EvalRow[]
}

export interface EvalConfigInput {
  label: string
  features: string[] | null
}

export async function fetchDocs(): Promise<Doc[]> {
  const res = await fetch(`${API_BASE}/documents`)
  if (!res.ok) throw new Error("Failed to fetch documents")
  return res.json()
}

export async function uploadFile(file: File): Promise<{ id: string; filename: string; status: string }> {
  const formData = new FormData()
  formData.append("file", file)
  const res = await fetch(`${API_BASE}/upload`, { method: "POST", body: formData })
  if (!res.ok) throw new Error("Upload failed")
  return res.json()
}

export async function ingestDocument(docId: string): Promise<{ id: string; filename: string; chunks: number; status: string }> {
  const res = await fetch(`${API_BASE}/ingest/${docId}`, { method: "POST" })
  if (!res.ok) throw new Error("Ingest failed")
  return res.json()
}

export async function getChunks(docId: string, pageSize = 20): Promise<{ chunks: Chunk[]; total: number; config: DocConfig }> {
  const res = await fetch(`${API_BASE}/documents/${docId}/chunks`)
  if (!res.ok) throw new Error("Failed to fetch chunks")
  const data = await res.json()
  return {
    chunks: data.chunks.slice(0, pageSize),
    total: data.total_chunks,
    config: {
      chunk_size: data.chunk_size,
      chunk_overlap: data.chunk_overlap,
    },
  }
}

export async function previewRechunk(docId: string, params: { chunk_size: number; chunk_overlap: number }): Promise<PreviewResult> {
  const res = await fetch(`${API_BASE}/documents/${docId}/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  })
  if (!res.ok) throw new Error("Preview failed")
  const data = await res.json()
  return { total_chunks: data.total_chunks, chunks: data.chunks }
}

export async function rechunkDocument(docId: string, params: { chunk_size: number; chunk_overlap: number }): Promise<RechunkResult> {
  const res = await fetch(`${API_BASE}/documents/${docId}/rechunk`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  })
  if (!res.ok) throw new Error("Rechunk failed")
  return res.json()
}

export async function deleteDocument(docId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/documents/${docId}`, { method: "DELETE" })
  if (!res.ok) throw new Error("Delete failed")
}

export async function getConversations(): Promise<ConversationSummary[]> {
  const res = await fetch(`${API_BASE}/conversations`)
  if (!res.ok) throw new Error("Failed to fetch conversations")
  return res.json()
}

export interface QueryResult {
  answer: string
  sources: Source[]
  figures: Figure[]
  conversation_id: string
  latency_ms: number
  trace?: QueryTrace | null
}

export interface QueryOptions {
  conversationId: string
  topK?: number
  filters?: Record<string, string | number | boolean> | null
  features?: string[] | null
  rerankStrategy?: RerankStrategy | null
  debug?: boolean
}

export async function queryDoc(question: string, options: QueryOptions): Promise<QueryResult> {
  const { conversationId, topK = 5, filters, features, rerankStrategy, debug = false } = options
  const hasFilters = filters && Object.keys(filters).length > 0
  const res = await fetch(`${API_BASE}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      conversation_id: conversationId,
      top_k: topK,
      ...(hasFilters ? { filters } : {}),
      ...(features ? { features } : {}),
      ...(rerankStrategy ? { rerank_strategy: rerankStrategy } : {}),
      ...(debug ? { debug: true } : {}),
    }),
  })
  if (!res.ok) throw new Error(`问答请求失败（HTTP ${res.status}）`)
  return res.json()
}

export async function getConversationMessages(conversationId: string): Promise<ChatMessage[]> {
  const res = await fetch(`${API_BASE}/conversations/${encodeURIComponent(conversationId)}/messages`)
  if (!res.ok) throw new Error("Failed to fetch conversation")
  return res.json()
}

export async function clearConversation(conversationId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/conversations/${encodeURIComponent(conversationId)}/messages`, { method: "DELETE" })
  if (!res.ok) throw new Error("Failed to clear conversation")
}

export async function getStats(): Promise<Stats> {
  const res = await fetch(`${API_BASE}/stats`, { cache: "no-store" })
  if (!res.ok) throw new Error("Failed to fetch stats")
  return res.json()
}

export async function fetchProviders(): Promise<LLMProvider[]> {
  const res = await fetch(`${API_BASE}/llm/providers`)
  if (!res.ok) throw new Error("Failed to fetch LLM providers")
  return res.json()
}

export async function getActiveProvider(): Promise<LLMProvider | null> {
  const res = await fetch(`${API_BASE}/llm/active`)
  if (!res.ok) return null
  const data = await res.json()
  return data.provider ?? null
}

export async function upsertProvider(draft: LLMProviderDraft): Promise<LLMProvider> {
  const res = await fetch(`${API_BASE}/llm/providers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(draft),
  })
  if (!res.ok) throw new Error("Save provider failed")
  return res.json()
}

export async function deleteProvider(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/llm/providers/${encodeURIComponent(id)}`, { method: "DELETE" })
  if (!res.ok) throw new Error("Delete provider failed")
}

export async function activateProvider(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/llm/providers/${encodeURIComponent(id)}/activate`, { method: "POST" })
  if (!res.ok) throw new Error("Activate provider failed")
}

export async function testProvider(id: string): Promise<{ ok: boolean; detail: string }> {
  const res = await fetch(`${API_BASE}/llm/providers/${encodeURIComponent(id)}/test`, { method: "POST" })
  if (!res.ok) throw new Error("Test provider failed")
  return res.json()
}

// ---- 健康检查 ----

export async function getHealth(): Promise<HealthStatus> {
  const res = await fetch(`${API_BASE}/health`, { cache: "no-store" })
  if (!res.ok) throw new Error(`健康检查失败（HTTP ${res.status}）`)
  return res.json()
}

// ---- 图谱 ----

export async function getGraphStats(): Promise<GraphStats> {
  const res = await fetch(`${API_BASE}/graph/stats`, { cache: "no-store" })
  if (!res.ok) throw new Error("获取图谱统计失败")
  return res.json()
}

export async function searchGraphEntities(q: string, kind?: string, limit = 20): Promise<GraphEntity[]> {
  const params = new URLSearchParams()
  if (q.trim()) params.set("q", q.trim())
  if (kind) params.set("kind", kind)
  params.set("limit", String(limit))
  const res = await fetch(`${API_BASE}/graph/search?${params.toString()}`)
  if (!res.ok) throw new Error("搜索实体失败")
  return res.json()
}

export async function getGraphEntity(entityId: string): Promise<GraphEntityDetail> {
  const res = await fetch(`${API_BASE}/graph/entities/${encodeURIComponent(entityId)}`)
  if (!res.ok) throw new Error("获取实体详情失败")
  return res.json()
}

export async function getSubgraph(entityId: string, hops = 2, limit = 150): Promise<GraphSubgraph> {
  const params = new URLSearchParams({ entity_id: entityId, hops: String(hops), limit: String(limit) })
  const res = await fetch(`${API_BASE}/graph/subgraph?${params.toString()}`)
  if (!res.ok) throw new Error("获取子图失败")
  return res.json()
}

// ---- 评测 ----

export async function getEvalCases(): Promise<EvalCase[]> {
  const res = await fetch(`${API_BASE}/eval/cases`, { cache: "no-store" })
  if (!res.ok) throw new Error("获取评测集失败")
  return res.json()
}

export async function addEvalCase(payload: {
  question: string
  expected_refs: string
  reference_answer?: string | null
}): Promise<EvalCase> {
  const res = await fetch(`${API_BASE}/eval/cases`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error("新增评测例失败")
  return res.json()
}

export async function seedEvalCases(): Promise<{ added: number }> {
  const res = await fetch(`${API_BASE}/eval/seed`, { method: "POST" })
  if (!res.ok) throw new Error("播种评测例失败")
  return res.json()
}

export async function runEval(k: number, configs?: EvalConfigInput[]): Promise<EvalRunResult> {
  const res = await fetch(`${API_BASE}/eval/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ k, ...(configs && configs.length ? { configs } : {}) }),
  })
  if (!res.ok) {
    let detail = `运行评测失败（HTTP ${res.status}）`
    try {
      const body = await res.json()
      if (body?.detail) detail = String(body.detail)
    } catch {
      // 响应体不是 JSON 时保留默认提示
    }
    throw new Error(detail)
  }
  return res.json()
}
