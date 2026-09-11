"use client"

import { Bot, Loader2, ScanText } from "lucide-react"

import { SourceChip, sourceAnchorId } from "@/components/chat/source-chip"
import { featureLabels } from "@/components/chat/feature-toggle"
import { Markdown } from "@/components/ui/markdown"
import type { Figure, QueryTrace, Source } from "@/lib/api"
import { cn } from "@/lib/utils"

export interface ChatMessageView {
  id: string
  role: "user" | "assistant"
  content: string
  sources?: Source[]
  figures?: Figure[]
  features?: string[] | null
  latency_ms?: number
  trace?: QueryTrace | null
  pending?: boolean
}

export const STAGES = ["规划检索…", "检索知识库…", "生成回答…"] as const

function metaLine(message: ChatMessageView): string | null {
  const parts: string[] = []
  const labels = featureLabels(message.features)
  if (labels) parts.push(labels)
  if (message.latency_ms != null) parts.push(`${(message.latency_ms / 1000).toFixed(1)}s`)
  return parts.length ? parts.join(" · ") : null
}

function highlightAnchor(index: number) {
  const element = document.getElementById(sourceAnchorId(index))
  if (!element) return
  element.scrollIntoView({ behavior: "smooth", block: "center" })
  element.classList.add("ring-1", "ring-primary")
  window.setTimeout(() => element.classList.remove("ring-1", "ring-primary"), 1600)
}

export function MessageThread({
  messages,
  loading,
  stage,
  error,
  onInspect,
  inspectingId,
}: {
  messages: ChatMessageView[]
  loading: boolean
  stage: string
  error: string | null
  onInspect: (messageId: string) => void
  inspectingId: string | null
}) {
  return (
    <div className="space-y-4">
      {messages.map((message) => {
        if (message.role === "user") {
          return (
            <div key={message.id} className="flex animate-fade-up justify-end">
              <div className="max-w-[78%] rounded-lg bg-primary px-3 py-2 text-body whitespace-pre-wrap break-words text-primary-foreground">
                {message.content}
              </div>
            </div>
          )
        }

        const meta = metaLine(message)
        const hasTrace = Boolean(message.trace)

        return (
          <div key={message.id} className="flex animate-fade-up items-start gap-2.5">
            <span className="mt-1 flex size-6 shrink-0 items-center justify-center rounded-md bg-primary/12">
              <Bot className="size-3.5 text-primary" />
            </span>
            <div className="min-w-0 flex-1 space-y-2 rounded-lg border border-border bg-card px-3 py-2.5">
              <Markdown content={message.content} onCite={highlightAnchor} />

              {message.figures && message.figures.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {message.figures.map((figure, index) => (
                    <figure key={index} className="max-w-[220px] rounded-md border border-border p-1">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={figure.data_uri}
                        alt={`第 ${figure.page} 页的图片`}
                        width={Math.min(figure.width, 220)}
                        height={Math.round((figure.height / Math.max(figure.width, 1)) * Math.min(figure.width, 220))}
                        className="rounded-sm"
                      />
                      <figcaption className="mt-0.5 font-mono text-meta text-muted-foreground">
                        p.{figure.page}
                      </figcaption>
                    </figure>
                  ))}
                </div>
              ) : null}

              {message.sources && message.sources.length > 0 ? (
                <div className="flex flex-wrap gap-1">
                  {message.sources.map((source, index) => (
                    <SourceChip key={index} source={source} index={index + 1} />
                  ))}
                </div>
              ) : null}

              {meta || hasTrace ? (
                <div className="flex items-center justify-between gap-2 border-t border-border pt-1.5">
                  <span className="min-w-0 truncate font-mono text-meta text-muted-foreground">{meta ?? ""}</span>
                  {hasTrace ? (
                    <button
                      type="button"
                      onClick={() => onInspect(message.id)}
                      className={cn(
                        "flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-meta transition-colors",
                        inspectingId === message.id
                          ? "bg-primary/12 text-primary"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground"
                      )}
                    >
                      <ScanText className="size-3" />
                      查看检索过程
                    </button>
                  ) : null}
                </div>
              ) : null}
            </div>
          </div>
        )
      })}

      {loading ? (
        <div className="flex animate-fade-up items-start gap-2.5">
          <span className="mt-1 flex size-6 shrink-0 items-center justify-center rounded-md bg-primary/12">
            <Bot className="size-3.5 text-primary" />
          </span>
          <div className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2.5 text-body text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" />
            {stage}
          </div>
        </div>
      ) : null}

      {error ? (
        <div className="flex items-start gap-2.5">
          <span className="mt-1 flex size-6 shrink-0 items-center justify-center rounded-md bg-destructive/12">
            <Bot className="size-3.5 text-destructive" />
          </span>
          <p className="rounded-lg border border-destructive/30 px-3 py-2 text-body text-destructive">{error}</p>
        </div>
      ) : null}
    </div>
  )
}
