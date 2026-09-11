"use client"

import { FileText } from "lucide-react"

import type { Source } from "@/lib/api"
import { cn } from "@/lib/utils"

export function sourceAnchorId(index: number) {
  return `evidence-${index}`
}

/** 证据 chip：展示来源与分数，悬停预览原文；被引用点击时高亮。 */
export function SourceChip({
  source,
  index,
  active,
}: {
  source: Source
  index: number
  active?: boolean
}) {
  return (
    <div
      id={sourceAnchorId(index)}
      className={cn(
        "group relative flex cursor-default items-center gap-1.5 rounded-md bg-muted px-2 py-0.5 text-meta transition-colors",
        active && "ring-1 ring-primary"
      )}
    >
      <span className="w-3 shrink-0 text-center font-mono text-primary">{index}</span>
      <FileText className="size-3 shrink-0 text-muted-foreground" />
      <span className="max-w-44 truncate font-medium">{source.doc_name}</span>
      {source.page != null ? <span className="font-mono text-muted-foreground">p.{source.page}</span> : null}
      {source.chunk_index != null ? (
        <span className="font-mono text-muted-foreground">#{source.chunk_index}</span>
      ) : null}
      {source.score != null ? (
        <span className="font-mono text-muted-foreground">{source.score.toFixed(2)}</span>
      ) : null}

      <div className="pointer-events-none absolute bottom-full left-0 z-20 mb-1.5 hidden w-72 rounded-lg border border-border bg-popover p-2.5 shadow-lg group-hover:block">
        <p className="mb-1 text-xs font-medium">{source.doc_name}</p>
        <p className="line-clamp-6 whitespace-pre-wrap text-xs text-muted-foreground">{source.text}</p>
      </div>
    </div>
  )
}
