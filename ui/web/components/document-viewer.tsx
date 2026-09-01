"use client"

import { useState } from "react"
import { getChunks, previewRechunk, rechunkDocument } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { ArrowLeft, RefreshCw, Eye, Settings, Trash2 } from "lucide-react"

interface Doc {
  id: string
  filename: string
  chunks: number
  status: string
}

interface DocumentViewerProps {
  doc: Doc
  onBack: () => void
  onDeleted: () => void
  onRefresh: () => void
}

export function DocumentViewer({ doc, onBack, onDeleted, onRefresh }: DocumentViewerProps) {
  const [chunks, setChunks] = useState<{ text: string; length: number; index: number }[]>([])
  const [totalChunks, setTotalChunks] = useState(0)
  const [config, setConfig] = useState({ chunk_size: 512, chunk_overlap: 64, strategy: "recursive" })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showRechunk, setShowRechunk] = useState(false)
  const [rechunkResult, setRechunkResult] = useState<any>(null)

  async function loadChunks() {
    setLoading(true)
    setError(null)
    try {
      const data = await getChunks(doc.id)
      setChunks(data.chunks.map((c: any) => ({ text: c.text, length: c.length, index: c.index })))
      setTotalChunks(data.total)
      setConfig({
        chunk_size: data.config.chunk_size,
        chunk_overlap: data.config.chunk_overlap,
        strategy: data.config.strategy,
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load chunks")
    } finally {
      setLoading(false)
    }
  }

  useState(() => {
    loadChunks()
  })

  async function handlePreview() {
    try {
      const data = await previewRechunk(doc.id, config)
      alert(`Preview: ${data.total_chunks} chunks (size=${config.chunk_size}, overlap=${config.chunk_overlap})`)
    } catch (e) {
      alert(`Preview failed: ${e}`)
    }
  }

  async function handleRechunk() {
    try {
      const result = await rechunkDocument(doc.id, config)
      setRechunkResult(result)
      if (result.success) {
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
            <p className="text-sm text-muted-foreground">Total Chunks</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-2xl font-bold">{config.chunk_size}</p>
            <p className="text-sm text-muted-foreground">Chunk Size</p>
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
          <CardTitle>Chunks ({totalChunks})</CardTitle>
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
                      #{chunk.index} · {chunk.length} chars
                    </span>
                  </div>
                  <p className="text-sm whitespace-pre-wrap break-words">{chunk.text}</p>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

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
            <div className="grid grid-cols-3 gap-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">Chunk Size</label>
                <Input
                  type="number"
                  value={config.chunk_size}
                  onChange={(e) => setConfig({ ...config, chunk_size: parseInt(e.target.value) || 512 })}
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
                  onChange={(e) => setConfig({ ...config, chunk_overlap: parseInt(e.target.value) || 64 })}
                  min={0}
                  max={4095}
                  step={32}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Strategy</label>
                <Select
                  value={config.strategy}
                  onValueChange={(v: string | null) => setConfig({ ...config, strategy: v || "recursive" })}
                >
                  <SelectTrigger>
                    <SelectValue placeholder={config.strategy} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="recursive">Recursive</SelectItem>
                    <SelectItem value="sentence">Sentence</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="flex gap-2">
              <Button variant="outline" onClick={handlePreview}>
                <Eye className="w-4 h-4 mr-1" />
                Preview
              </Button>
              <Button onClick={handleRechunk}>
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
