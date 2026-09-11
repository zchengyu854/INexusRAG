"use client"

import { useEffect, useMemo, useState } from "react"
import { ExternalLink } from "lucide-react"

import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel"
import { documentFileUrl, type Chunk, type Doc } from "@/lib/api"

/** 在原文里定位切片：整段命中率受换行影响，逐步降级用更短的前缀匹配。 */
function locate(raw: string, text: string): { start: number; end: number } | null {
  const normalized = text.trim()
  if (!normalized) return null
  for (const length of [400, 200, 120, 60, 30]) {
    const needle = normalized.slice(0, length)
    if (needle.length < 8) break
    const start = raw.indexOf(needle)
    if (start >= 0) return { start, end: start + needle.length }
  }
  return null
}

export function SourcePreview({ doc, chunk }: { doc: Doc; chunk: Chunk | null }) {
  const isPdf = doc.filename.toLowerCase().endsWith(".pdf")
  const [raw, setRaw] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (isPdf) return
    let cancelled = false
    fetch(documentFileUrl(doc.id))
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.text()
      })
      .then((text) => {
        if (!cancelled) setRaw(text)
      })
      .catch(() => {
        if (!cancelled) setError("无法读取源文件")
      })
    return () => {
      cancelled = true
    }
  }, [doc.id, isPdf])

  const located = useMemo(() => {
    if (!raw || !chunk) return null
    return locate(raw, chunk.text)
  }, [raw, chunk])

  return (
    <Panel className="w-[384px] shrink-0">
      <PanelHeader
        title="原件预览"
        actions={
          <a
            href={documentFileUrl(doc.id)}
            target="_blank"
            rel="noreferrer"
            title="在新标签打开原件"
            className="flex h-6 items-center gap-1 rounded-md px-1.5 text-meta text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <ExternalLink className="size-3" />
            打开
          </a>
        }
      />
      <PanelBody className="space-y-2 p-3">
        {isPdf ? (
          <>
            <p className="text-meta text-muted-foreground">
              {chunk?.page != null ? `已定位到第 ${chunk.page} 页` : "在左侧点击切片可定位到对应页"}
            </p>
            <iframe
              key={chunk?.page ?? "first"}
              src={documentFileUrl(doc.id, chunk?.page ?? 1)}
              title={`${doc.filename} 预览`}
              className="h-[calc(100%-1.75rem)] min-h-[420px] w-full rounded-md border border-border bg-background"
            />
          </>
        ) : error ? (
          <p className="text-body text-destructive">{error}</p>
        ) : raw === null ? (
          <p className="text-body text-muted-foreground">读取中…</p>
        ) : (
          <>
            <p className="text-meta text-muted-foreground">
              {chunk ? `已高亮切片 #${chunk.index}` : "在左侧点击切片可高亮对应原文"}
            </p>
            <pre className="scroll-thin max-h-full overflow-auto rounded-md border border-border bg-muted/30 p-2.5 font-mono text-xs leading-relaxed whitespace-pre-wrap break-words">
              {located ? (
                <>
                  {raw.slice(0, located.start)}
                  <mark className="rounded-sm bg-primary/25 text-foreground">
                    {raw.slice(located.start, located.end)}
                  </mark>
                  {raw.slice(located.end)}
                </>
              ) : (
                raw
              )}
            </pre>
          </>
        )}
      </PanelBody>
    </Panel>
  )
}
