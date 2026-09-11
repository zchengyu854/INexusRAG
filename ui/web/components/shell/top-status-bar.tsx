"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useState } from "react"

import { getHealth, type HealthStatus } from "@/lib/api"
import { buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const PAGE_TITLES: Record<string, string> = {
  "/overview": "概览",
  "/chat": "问答",
  "/documents": "文档",
  "/graph": "图谱",
  "/eval": "评测",
  "/settings": "设置",
}

const POLL_MS = 8000

export function TopStatusBar({ title }: { title?: string }) {
  const pathname = usePathname()
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [reachable, setReachable] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function poll() {
      try {
        const data = await getHealth()
        if (!cancelled) {
          setHealth(data)
          setReachable(true)
        }
      } catch {
        if (!cancelled) {
          setHealth(null)
          setReachable(false)
        }
      }
    }
    void poll()
    const timer = window.setInterval(poll, POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])

  const pageTitle = title ?? PAGE_TITLES[pathname] ?? "NexusRAG"
  const dbOk = reachable && health?.database.ok !== false
  const llmConfigured = health?.llm.configured ?? false
  const modelLabel = health?.llm.model ?? "未配置模型"

  return (
    <header className="flex h-11 shrink-0 items-center justify-between gap-3 border-b border-border px-4">
      <h1 className="text-base font-medium tracking-tight">{pageTitle}</h1>

      <div className="flex items-center gap-3">
        <span className="flex items-center gap-1.5 text-meta text-muted-foreground">
          <span
            className={cn(
              "size-[7px] rounded-full",
              !reachable ? "bg-destructive" : dbOk ? "bg-success" : "bg-warning"
            )}
          />
          {!reachable ? "后端不可达" : dbOk ? "后端正常" : "数据库异常"}
        </span>

        <span
          className={cn(
            "max-w-[200px] truncate font-mono text-meta",
            llmConfigured ? "text-muted-foreground" : "text-warning"
          )}
          title={llmConfigured ? `${health?.llm.source ?? ""} / ${modelLabel}` : "未配置 LLM，问答将只返回检索结果"}
        >
          {llmConfigured ? modelLabel : "未配置 LLM"}
        </span>

        {health ? (
          <span className="hidden font-mono text-meta text-muted-foreground sm:inline">
            {health.documents}d · {health.chunks}c
          </span>
        ) : null}

        <Link href="/documents" className={cn(buttonVariants({ variant: "outline", size: "xs" }))}>
          上传文档
        </Link>
      </div>
    </header>
  )
}
