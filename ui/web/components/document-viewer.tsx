"use client"

import { useCallback, useEffect, useState } from "react"
import { getChunks, previewRechunk, rechunkDocument, type Chunk, type Doc, type PreviewResult, type RechunkResult } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { ArrowLeft, RefreshCw, Eye, Trash2, Check, X } from "lucide-react"

interface DocumentViewerProps {
  doc: Doc
  onBack: () => void
  onDeleted: () => void
  onRefresh: () => void
}

function chunkMeta(chunk: { index: number; length: number; page?: number | null }) {
  const parts = [`#${chunk.index}`, `${chunk.length} chars`]
  if (chunk.page != null) parts.push(`p.${chunk.page}`)
  return parts.join(", ")
}

export function DocumentViewer({ doc, onBack, onDeleted, onRefresh }: DocumentViewerProps) {
  const [chunks, setChunks] = useState<Chunk[]>([])
  const [totalChunks, setTotalChunks] = useState(0)
  const [config, setConfig] = useState({ chunk_size: 512, chunk_overlap: 64 })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showRechunk, setShowRechunk] = useState(false)
  const [rechunkResult, setRechunkResult] = useState<RechunkResult | null>(null)
  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  const loadChunks = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getChunks(doc.id)
      setChunks(data.chunks)
      setTotalChunks(data.total)
      setConfig({
        chunk_size: data.config.chunk_size,
        chunk_overlap: data.config.chunk_overlap,
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load chunks")
    } finally {
      setLoading(false)
    }
  }, [doc.id])

  useEffect(() => {
    let cancelled = false
    getChunks(doc.id).then((data) => {
      if (cancelled) return
      setChunks(data.chunks)
      setTotalChunks(data.total)
      setConfig({
        chunk_size: data.config.chunk_size,
        chunk_overlap: data.config.chunk_overlap,
      })
    }).catch((err) => {
      if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load chunks")
    }).finally(() => {
      if (!cancelled) setLoading(false)
    })
    return () => { cancelled = true }
  }, [doc.id])

  async function handlePreview() {
    setPreviewLoading(true)
    setError(null)
    try {
      setPreview(await previewRechunk(doc.id, config))
      setRechunkResult(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Preview failed")
    } finally {
      setPreviewLoading(false)
    }
  }

  async function handleRechunk() {
    if (!preview) return
    try {
      const result = await rechunkDocument(doc.id, config)
      setRechunkResult(result)
      if (result.success) {
        setPreview(null)
        await loadChunks()
        onRefresh()
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Rechunk failed")
    }
  }

  return (
    <div className="mx-auto max-w-[1100px] space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="mr-1 h-4 w-4" />
          Back
        </Button>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-2xl font-semibold tracking-tight">{doc.filename}</h2>
          <p className="truncate font-mono text-xs text-muted-foreground">{doc.id}</p>
        </div>
        <Button variant="outline" size="sm" onClick={loadChunks} disabled={loading}>
          <RefreshCw className="mr-1 h-4 w-4" />
          Refresh
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-3 gap-6 border-b pb-6">
        {[
          { value: totalChunks, label: "Indexed chunks" },
          { value: config.chunk_size, label: "Chunk size" },
          { value: config.chunk_overlap, label: "Overlap" },
        ].map((stat) => (
          <div key={stat.label}>
            <p className="font-mono text-3xl font-semibold tracking-tight">{stat.value}</p>
            <p className="mt-1 text-sm text-muted-foreground">{stat.label}</p>
          </div>
        ))}
      </div>

      <section className="rounded-lg border bg-card">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <h3 className="font-medium">Indexed chunks ({totalChunks})</h3>
          <span className="text-xs text-muted-foreground">
            {Math.min(chunks.length, totalChunks)} of {totalChunks} shown
          </span>
        </div>
        {loading ? (
          <div className="py-10 text-center text-sm text-muted-foreground">Loading…</div>
        ) : chunks.length === 0 ? (
          <div className="py-10 text-center text-sm text-muted-foreground">No chunks found</div>
        ) : (
          <div className="max-h-96 space-y-2 overflow-y-auto p-3">
            {chunks.map((chunk) => (
              <div key={chunk.index} className="rounded-md bg-muted/50 p-3">
                <p className="mb-1 font-mono text-xs text-muted-foreground">{chunkMeta(chunk)}</p>
                <p className="whitespace-pre-wrap break-words text-sm">{chunk.text}</p>
              </div>
            ))}
          </div>
        )}
      </section>

      {preview && (
        <section className="rounded-lg border border-primary/30 bg-card">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <h3 className="font-medium">New chunking preview ({preview.total_chunks})</h3>
            <span className="text-xs text-muted-foreground">not indexed</span>
          </div>
          <div className="space-y-2 p-3">
            <div className="rounded-md bg-primary/5 px-3 py-2 text-sm text-muted-foreground">
              Current: {totalChunks} chunks. Rechunk will embed {preview.total_chunks} chunks.
            </div>
            {preview.chunks.slice(0, 20).map((chunk) => (
              <div key={chunk.index} className="rounded-md bg-muted/50 p-3">
                <p className="mb-1 font-mono text-xs text-muted-foreground">{chunkMeta(chunk)}</p>
                <p className="whitespace-pre-wrap break-words text-sm">{chunk.text}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      <Separator />

      <div>
        <button
          onClick={() => setShowRechunk(!showRechunk)}
          className="flex w-full items-center justify-between rounded-lg border bg-card px-4 py-3 text-left text-sm font-medium transition-colors hover:bg-muted/50"
        >
          <span>Rechunk settings</span>
          <span className="font-mono text-xs text-muted-foreground">
            {config.chunk_size} / {config.chunk_overlap}
          </span>
        </button>

        {showRechunk && (
          <div className="animate-fade-up space-y-4 border-t bg-card p-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Chunk size (64-4096)</label>
                <Input
                  type="number"
                  value={config.chunk_size}
                  onChange={(e) => {
                    setPreview(null)
                    setConfig({ ...config, chunk_size: parseInt(e.target.value) || 512 })
                  }}
                  min={64}
                  max={4096}
                  step={64}
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Overlap (0-4095)</label>
                <Input
                  type="number"
                  value={config.chunk_overlap}
                  onChange={(e) => {
                    setPreview(null)
                    setConfig({ ...config, chunk_overlap: parseInt(e.target.value) || 64 })
                  }}
                  min={0}
                  max={4095}
                  step={32}
                />
              </div>
            </div>

            <div className="flex gap-2">
              <Button variant="outline" onClick={handlePreview} disabled={loading || previewLoading}>
                {previewLoading ? <RefreshCw className="mr-1 h-4 w-4 animate-spin" /> : <Eye className="mr-1 h-4 w-4" />}
                {previewLoading ? "Previewing…" : "Preview"}
              </Button>
              <Button onClick={handleRechunk} disabled={loading || !preview}>
                <RefreshCw className="mr-1 h-4 w-4" />
                Rechunk
              </Button>
            </div>

            {rechunkResult && (
              <Alert variant={rechunkResult.success ? "default" : "destructive"}>
                <AlertDescription className="flex items-center gap-2">
                  {rechunkResult.success ? (
                    <>
                      <Check className="size-4 text-primary" />
                      <span>
                        {rechunkResult.old_chunks} to {rechunkResult.new_chunks} chunks (
                        {rechunkResult.latency_ms.toFixed(0)}ms)
                      </span>
                    </>
                  ) : (
                    <>
                      <X className="size-4 text-destructive" />
                      <span>{rechunkResult.error ?? "Rechunk failed"}</span>
                    </>
                  )}
                </AlertDescription>
              </Alert>
            )}
          </div>
        )}
      </div>

      <div className="flex justify-end">
        <Button
          variant="destructive"
          size="sm"
          onClick={() => {
            if (confirm(`Delete ${doc.filename}?`)) {
              onDeleted()
            }
          }}
        >
          <Trash2 className="mr-1 h-4 w-4" />
          Delete
        </Button>
      </div>
    </div>
  )
}
