"use client"

import { useCallback, useEffect, useState } from "react"
import { ArrowLeft, Check, Eye, RefreshCw, Trash2, X } from "lucide-react"

import { SourcePreview } from "@/components/documents/source-preview"
import { Button } from "@/components/ui/button"
import { Metric } from "@/components/ui/metric"
import {
  buildDocumentGraph,
  getChunks,
  previewRechunk,
  rechunkDocument,
  type Chunk,
  type Doc,
  type DocConfig,
  type PreviewResult,
  type RechunkResult,
} from "@/lib/api"
import { cn } from "@/lib/utils"

function chunkMeta(chunk: Chunk): string {
  const parts = [`#${chunk.index}`, `${chunk.length} 字`]
  if (chunk.page != null) parts.push(`p.${chunk.page}`)
  return parts.join(" · ")
}

export function DocumentDetail({
  doc,
  onBack,
  onRefresh,
  onDelete,
}: {
  doc: Doc
  onBack: () => void
  onRefresh: () => Promise<unknown>
  onDelete: () => void
}) {
  const [chunks, setChunks] = useState<Chunk[]>([])
  const [totalChunks, setTotalChunks] = useState(0)
  const [config, setConfig] = useState<DocConfig>({ chunk_size: 512, chunk_overlap: 64 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showRechunk, setShowRechunk] = useState(false)
  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [rechunkResult, setRechunkResult] = useState<RechunkResult | null>(null)
  const [activeIndex, setActiveIndex] = useState<number | null>(null)
  const [graphBuilding, setGraphBuilding] = useState(false)
  const [graphMessage, setGraphMessage] = useState<string | null>(null)

  const loadChunks = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getChunks(doc.id, 500)
      setChunks(data.chunks)
      setTotalChunks(data.total)
      setConfig(data.config)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载切片失败")
    } finally {
      setLoading(false)
    }
  }, [doc.id])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadChunks()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadChunks])

  async function handlePreview() {
    setPreviewLoading(true)
    setError(null)
    try {
      setPreview(await previewRechunk(doc.id, config))
      setRechunkResult(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "预览失败")
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
        setActiveIndex(null)
        await loadChunks()
        await onRefresh()
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "重新切片失败")
    }
  }

  async function handleBuildGraph() {
    setGraphBuilding(true)
    setGraphMessage(null)
    setError(null)
    try {
      const result = await buildDocumentGraph(doc.id)
      setGraphMessage(result.message || "已开始后台建图")
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "建图失败")
    } finally {
      setGraphBuilding(false)
    }
  }

  const activeChunk = activeIndex != null ? chunks.find((chunk) => chunk.index === activeIndex) ?? null : null

  return (
    <div className="flex h-full min-h-0">
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto p-4">
        <div className="mb-3 flex items-start gap-3">
          <Button variant="ghost" size="icon-sm" onClick={onBack} title="返回列表">
            <ArrowLeft />
          </Button>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-base font-medium">{doc.filename}</h2>
            <p className="truncate font-mono text-meta text-muted-foreground">{doc.id}</p>
          </div>
          <Button variant="outline" size="xs" onClick={() => void loadChunks()} disabled={loading}>
            <RefreshCw className={cn(loading && "animate-spin")} />
            刷新
          </Button>
          <Button
            variant="outline"
            size="xs"
            onClick={() => void handleBuildGraph()}
            disabled={graphBuilding || doc.status !== "ready" || totalChunks === 0}
            title="按本文档增量抽取实体关系（不清空其他文档的图）"
          >
            {graphBuilding ? <RefreshCw className="animate-spin" /> : null}
            构建图谱
          </Button>
        </div>

        {graphMessage ? (
          <p className="mb-3 rounded-md border border-border bg-muted/40 px-2.5 py-1.5 text-body text-muted-foreground">
            {graphMessage}
          </p>
        ) : null}

        {error ? (
          <p className="mb-3 rounded-md border border-destructive/30 px-2.5 py-1.5 text-body text-destructive">
            {error}
          </p>
        ) : null}

        <div className="grid grid-cols-3 gap-3">
          <Metric label="已入库切片" value={totalChunks} />
          <Metric label="chunk size" value={config.chunk_size} />
          <Metric label="overlap" value={config.chunk_overlap} />
        </div>

        <section className="mt-3">
          <div className="mb-1.5 flex items-center justify-between">
            <h3 className="text-body font-medium">切片列表（{totalChunks}）</h3>
            <span className="text-meta text-muted-foreground">
              已加载 {chunks.length} 条{activeChunk ? " · 点击可在右侧定位" : ""}
            </span>
          </div>

          {loading ? (
            <p className="py-8 text-center text-body text-muted-foreground">加载中…</p>
          ) : chunks.length === 0 ? (
            <p className="py-8 text-center text-body text-muted-foreground">暂无切片</p>
          ) : (
            <div className="space-y-1">
              {chunks.map((chunk) => (
                <button
                  key={chunk.index}
                  type="button"
                  onClick={() => setActiveIndex(chunk.index === activeIndex ? null : chunk.index)}
                  className={cn(
                    "w-full rounded-md border px-2.5 py-2 text-left transition-colors",
                    chunk.index === activeIndex
                      ? "border-primary/40 bg-primary/8"
                      : "border-transparent bg-muted/40 hover:bg-muted"
                  )}
                >
                  <span className="block font-mono text-meta text-muted-foreground">{chunkMeta(chunk)}</span>
                  <span className="mt-1 line-clamp-3 block whitespace-pre-wrap break-words text-body">
                    {chunk.text}
                  </span>
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="mt-3">
          <button
            type="button"
            onClick={() => setShowRechunk((value) => !value)}
            className="flex w-full items-center justify-between rounded-md border border-border px-3 py-2 text-left text-body transition-colors hover:bg-muted/50"
          >
            <span className="font-medium">重新切片</span>
            <span className="font-mono text-meta text-muted-foreground">
              {config.chunk_size} / {config.chunk_overlap}
            </span>
          </button>

          {showRechunk ? (
            <div className="animate-fade-up space-y-3 border-x border-b border-border p-3">
              <div className="grid grid-cols-2 gap-3">
                <label className="space-y-1">
                  <span className="text-meta text-muted-foreground">chunk size（64–4096）</span>
                  <input
                    type="number"
                    min={64}
                    max={4096}
                    step={64}
                    value={config.chunk_size}
                    onChange={(event) => {
                      setPreview(null)
                      setConfig({ ...config, chunk_size: Number(event.target.value) || 512 })
                    }}
                    className="h-7 w-full rounded-md border border-border bg-background px-2 text-body outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-meta text-muted-foreground">overlap（0–4095）</span>
                  <input
                    type="number"
                    min={0}
                    max={4095}
                    step={32}
                    value={config.chunk_overlap}
                    onChange={(event) => {
                      setPreview(null)
                      setConfig({ ...config, chunk_overlap: Number(event.target.value) || 0 })
                    }}
                    className="h-7 w-full rounded-md border border-border bg-background px-2 text-body outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                  />
                </label>
              </div>

              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => void handlePreview()} disabled={previewLoading}>
                  <Eye className={cn(previewLoading && "animate-pulse")} />
                  {previewLoading ? "预览中…" : "预览"}
                </Button>
                <Button size="sm" onClick={() => void handleRechunk()} disabled={!preview}>
                  <RefreshCw />
                  应用重新切片
                </Button>
              </div>

              {rechunkResult ? (
                <p
                  className={cn(
                    "flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-body",
                    rechunkResult.success ? "bg-success/12 text-success" : "bg-destructive/12 text-destructive"
                  )}
                >
                  {rechunkResult.success ? <Check className="size-3.5" /> : <X className="size-3.5" />}
                  {rechunkResult.success
                    ? `${rechunkResult.old_chunks} → ${rechunkResult.new_chunks} 片（${rechunkResult.latency_ms.toFixed(0)}ms）`
                    : rechunkResult.error ?? "重新切片失败"}
                </p>
              ) : null}

              {preview ? (
                <div className="rounded-md border border-primary/30 p-2.5">
                  <p className="mb-1.5 text-meta text-muted-foreground">
                    预计生成 {preview.total_chunks} 片（当前 {totalChunks} 片），应用后会重新向量化
                  </p>
                  <div className="space-y-1">
                    {preview.chunks.slice(0, 8).map((chunk) => (
                      <div key={chunk.index} className="rounded bg-muted/50 px-2 py-1.5">
                        <span className="block font-mono text-meta text-muted-foreground">{chunkMeta(chunk)}</span>
                        <span className="mt-0.5 line-clamp-2 block text-meta">{chunk.text}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              <p className="text-meta text-muted-foreground">
                注意：重新切片会重建该文档的向量，图谱不会自动重建，需重新运行
                <code className="mx-1 font-mono">python -m src.graph build</code>。
              </p>
            </div>
          ) : null}
        </section>

        <div className="mt-4 flex justify-end">
          <Button
            variant="destructive"
            size="sm"
            onClick={() => {
              if (window.confirm(`删除「${doc.filename}」？`)) onDelete()
            }}
          >
            <Trash2 />
            删除文档
          </Button>
        </div>
      </div>

      {/* key 让切换文档时组件重挂载，省去在 effect 里同步重置状态 */}
      <SourcePreview key={doc.id} doc={doc} chunk={activeChunk} />
    </div>
  )
}
