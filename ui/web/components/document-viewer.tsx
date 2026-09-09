"use client"

import { useCallback, useEffect, useState } from "react"
import { getChunks, previewRechunk, rechunkDocument, type Chunk, type Doc, type PreviewResult, type RechunkResult } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { ArrowLeft, RefreshCw, Eye, Settings, Trash2 } from "lucide-react"

interface DocumentViewerProps {
  doc: Doc
  onBack: () => void
  onDeleted: () => void
  onRefresh: () => void
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
    }).catch((error) => {
      if (!cancelled) setError(error instanceof Error ? error.message : "Failed to load chunks")
    }).finally(() => {
      if (!cancelled) setLoading(false)
    })
    return () => { cancelled = true }
  }, [doc.id])

  async function handlePreview() {
    setPreviewLoading(true)
    setError(null)
    try {
      const data = await previewRechunk(doc.id, config)
      setPreview(data)
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
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="w-4 h-4 mr-1" />
          Back
        </Button>
        <div className="flex-1">
          <h2 className="text-xl font-semibold">{doc.filename}</h2>
          <p className="text-sm text-muted-foreground">{doc.id}</p>
        </div>
        <Button variant="outline" size="sm" onClick={loadChunks} disabled={loading}>
          <RefreshCw className="w-4 h-4 mr-1" />
          Refresh
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-4">
            <p className="text-2xl font-bold">{totalChunks}</p>
            <p className="text-sm text-muted-foreground">Indexed chunks</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-2xl font-bold">{config.chunk_size}</p>
            <p className="text-sm text-muted-foreground">Oversize fallback limit</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-2xl font-bold">{config.chunk_overlap}</p>
            <p className="text-sm text-muted-foreground">Overlap</p>
          </CardContent>
        </Card>
      </div>

      {/* Chunks List */}
      <Card>
        <CardHeader>
          <CardTitle>Indexed chunks ({totalChunks})</CardTitle>
          <p className="text-sm text-muted-foreground">Historical result currently stored in PostgreSQL</p>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="text-center py-8 text-muted-foreground">Loading...</div>
          ) : chunks.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">No chunks found</div>
          ) : (
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {chunks.map((chunk) => (
                <div key={chunk.index} className="p-3 bg-muted rounded-lg">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-mono text-muted-foreground">
                      #{chunk.index} · {chunk.length} chars{chunk.page != null ? ` · p.${chunk.page}` : ""}
                    </span>
                  </div>
                  <p className="text-sm whitespace-pre-wrap break-words">{chunk.text}</p>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {preview && (
        <Card className="border-primary/30">
          <CardHeader>
            <CardTitle className="flex items-center justify-between gap-3">
              <span>New rule preview ({preview.total_chunks})</span>
              <span className="text-sm font-normal text-muted-foreground">not indexed</span>
            </CardTitle>
            <p className="text-sm text-muted-foreground">
              Markdown headings, paragraphs, lists, and code blocks stay as semantic boundaries.
            </p>
          </CardHeader>
          <CardContent>
            <div className="mb-3 rounded-md bg-primary/5 px-3 py-2 text-sm text-muted-foreground">
              Current indexed chunks: {totalChunks} · Embeddings on rechunk: {preview.total_chunks}
            </div>
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {preview.chunks.slice(0, 20).map((chunk) => (
                <div key={chunk.index} className="rounded-lg bg-muted p-3">
                  <div className="mb-1 text-sm font-mono text-muted-foreground">
                    #{chunk.index} · {chunk.length} chars{chunk.page != null ? ` · p.${chunk.page}` : ""}
                  </div>
                  <p className="text-sm whitespace-pre-wrap break-words">{chunk.text}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Rechunk Section */}
      <Separator />
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold flex items-center gap-2">
          <Settings className="w-5 h-5" />
          Rechunk
        </h3>
        <Button variant="ghost" size="sm" onClick={() => setShowRechunk(!showRechunk)}>
          {showRechunk ? "Hide" : "Show"}
        </Button>
      </div>

      {showRechunk && (
        <Card>
          <CardContent className="p-6 space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium">Chunk Size</label>
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
              <div className="space-y-2">
                <label className="text-sm font-medium">Overlap</label>
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
              <div className="space-y-2">
                <label className="text-sm font-medium">Rule</label>
                <div className="flex h-9 items-center rounded-md border border-input bg-muted/40 px-3 text-sm text-muted-foreground">
                  Markdown semantic boundaries
                </div>
              </div>
            </div>

            <div className="flex gap-2">
              <Button variant="outline" onClick={handlePreview} disabled={loading || previewLoading}>
                {previewLoading ? <RefreshCw className="w-4 h-4 mr-1 animate-spin" /> : <Eye className="w-4 h-4 mr-1" />}
                {previewLoading ? "Previewing..." : "Preview"}
              </Button>
              <Button onClick={handleRechunk} disabled={loading || !preview}>
                <RefreshCw className="w-4 h-4 mr-1" />
                Rechunk
              </Button>
            </div>

            {rechunkResult && (
              <Alert>
                <AlertDescription>
                  {rechunkResult.success
                    ? `✅ ${rechunkResult.old_chunks} → ${rechunkResult.new_chunks} chunks (${rechunkResult.latency_ms.toFixed(0)}ms)`
                    : `❌ ${rechunkResult.error ?? ""}`}
                </AlertDescription>
              </Alert>
            )}
          </CardContent>
        </Card>
      )}

      {/* Delete */}
      <div className="flex justify-end">
        <Button variant="destructive" size="sm" onClick={() => {
          if (confirm(`Delete ${doc.filename}?`)) {
            onDeleted()
          }
        }}>
          <Trash2 className="w-4 h-4 mr-1" />
          Delete
        </Button>
      </div>
    </div>
  )
}
