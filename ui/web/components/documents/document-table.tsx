"use client"

import { ArrowUpRight, FileText, Loader2, Trash2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import type { Doc } from "@/lib/api"

const GRID = "grid grid-cols-[minmax(0,1fr)_72px_88px_132px_64px] items-center gap-3"

function StatusBadge({ status }: { status: string }) {
  if (status === "ready") {
    return <Badge className="bg-success/15 text-success hover:bg-success/15">就绪</Badge>
  }
  if (status === "indexing") {
    return <Badge className="bg-warning/15 text-warning hover:bg-warning/15">入库中</Badge>
  }
  if (status === "failed") {
    return <Badge variant="destructive">失败</Badge>
  }
  return <Badge variant="outline">{status}</Badge>
}

function shortTime(iso?: string | null): string {
  if (!iso) return "—"
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return "—"
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function DocumentTable({
  docs,
  onOpen,
  onDelete,
}: {
  docs: Doc[]
  onOpen: (doc: Doc) => void
  onDelete: (docId: string) => void
}) {
  return (
    <div className="overflow-hidden rounded-md border border-border">
      <div className={`${GRID} border-b border-border bg-muted/40 px-3 py-2 text-meta text-muted-foreground`}>
        <span>文件名</span>
        <span className="text-right">切片数</span>
        <span>状态</span>
        <span>入库时间</span>
        <span />
      </div>
      <ul className="divide-y divide-border">
        {docs.map((doc) => (
          <li key={doc.id}>
            <div
              role="button"
              tabIndex={0}
              onClick={() => onOpen(doc)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault()
                  onOpen(doc)
                }
              }}
              className={`${GRID} cursor-pointer px-3 py-2 transition-colors hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:outline-none`}
            >
              <div className="flex min-w-0 items-center gap-2">
                {doc.status === "indexing" ? (
                  <Loader2 className="size-3.5 shrink-0 animate-spin text-warning" />
                ) : (
                  <FileText className="size-3.5 shrink-0 text-muted-foreground" />
                )}
                <span className="truncate text-body font-medium">{doc.filename}</span>
              </div>
              <span className="text-right font-mono text-xs tabular-nums text-muted-foreground">
                {doc.chunks || "—"}
              </span>
              <span>
                <StatusBadge status={doc.status} />
              </span>
              <span className="font-mono text-meta text-muted-foreground">{shortTime(doc.updated_at ?? doc.created_at)}</span>
              <div className="flex justify-end gap-0.5" onClick={(event) => event.stopPropagation()}>
                <Button variant="ghost" size="icon-xs" title="查看详情" onClick={() => onOpen(doc)}>
                  <ArrowUpRight />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  title="删除"
                  className="text-muted-foreground hover:text-destructive"
                  onClick={() => {
                    if (window.confirm(`删除「${doc.filename}」？该文档的切片与图谱连线会一并移除。`)) {
                      onDelete(doc.id)
                    }
                  }}
                >
                  <Trash2 />
                </Button>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
