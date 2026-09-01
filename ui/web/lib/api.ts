"use client"

import { API_BASE } from "./constants"
import { useState, useEffect } from "react"

interface Doc {
  id: string
  filename: string
  chunks: number
  status: string
}

interface Chunk {
  index: number
  chunk_id: string
  text: string
  length: number
  overlap_with_next: number
}

interface DocConfig {
  strategy: string
  chunk_size: number
  chunk_overlap: number
  embedding_model: string
  embedding_dimension: number
}

interface ChunkDetail {
  id: string
  filename: string
  status: string
  chunks: number
  latency_ms: number
  config: DocConfig
  error: string | null
  embeddings: number[][]
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
      strategy: data.strategy,
      chunk_size: data.chunk_size,
      chunk_overlap: data.chunk_overlap,
      embedding_model: "",
      embedding_dimension: 0,
    },
  }
}

export async function getDocDetail(docId: string): Promise<ChunkDetail> {
  const res = await fetch(`${API_BASE}/documents/${docId}/detail`)
  if (!res.ok) throw new Error("Failed to fetch detail")
  return res.json()
}

export async function previewRechunk(docId: string, params: { chunk_size: number; chunk_overlap: number; strategy: string }): Promise<{ total_chunks: number; chunks: Chunk[] }> {
  const res = await fetch(`${API_BASE}/documents/${docId}/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  })
  if (!res.ok) throw new Error("Preview failed")
  const data = await res.json()
  return { total_chunks: data.total_chunks, chunks: data.chunks.slice(0, 10) }
}

export async function rechunkDocument(docId: string, params: { chunk_size: number; chunk_overlap: number; strategy: string }): Promise<{
  success: boolean
  old_chunks: number
  new_chunks: number
  latency_ms: number
  error?: string
}> {
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

export async function queryDoc(question: string, topK = 5): Promise<{ answer: string; sources: any[] }> {
  const res = await fetch(`${API_BASE}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, stream: false, top_k: topK }),
  })
  if (!res.ok) throw new Error("Query failed")
  return res.json()
}

export async function getStats(): Promise<{ total_documents: number; total_chunks: number; embedding_dimension: number; total_size_kb: number }> {
  const res = await fetch(`${API_BASE}/stats`)
  if (!res.ok) throw new Error("Failed to fetch stats")
  return res.json()
}
