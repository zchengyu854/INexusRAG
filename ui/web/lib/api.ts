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

export async function queryDoc(question: string, conversationId: string, topK = 5): Promise<{ answer: string; sources: Source[]; conversation_id: string }> {
  const res = await fetch(`${API_BASE}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, conversation_id: conversationId, top_k: topK }),
  })
  if (!res.ok) throw new Error("Query failed")
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
