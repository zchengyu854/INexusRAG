"use client"

import Link from "next/link"
import { useEffect, useState } from "react"

import { buttonVariants } from "@/components/ui/button"
import { KeyValueRow, Metric } from "@/components/ui/metric"
import { getGraphStats, getHealth, getStats, type GraphStats, type HealthStatus, type Stats } from "@/lib/api"
import { cn } from "@/lib/utils"

const QUICK_ACTIONS: { href: string; label: string; hint: string }[] = [
  { href: "/chat", label: "开始提问", hint: "基于知识库回答并给出引用" },
  { href: "/documents", label: "上传并入库文档", hint: "支持 PDF / Markdown / TXT" },
  { href: "/graph", label: "浏览知识图谱", hint: "实体与关系的多跳线索" },
  { href: "/eval", label: "运行消融评测", hint: "对比不同检索特性的效果" },
]

function formatNumber(value: number | undefined): string {
  if (value === undefined) return "—"
  return value.toLocaleString("zh-CN")
}

export function OverviewPage() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [graph, setGraph] = useState<GraphStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    Promise.allSettled([getStats(), getHealth(), getGraphStats()]).then(([statsResult, healthResult, graphResult]) => {
      if (cancelled) return
      setStats(statsResult.status === "fulfilled" ? statsResult.value : null)
      setHealth(healthResult.status === "fulfilled" ? healthResult.value : null)
      setGraph(graphResult.status === "fulfilled" ? graphResult.value : null)
      setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const dbOk = health?.database.ok ?? false
  const llm = health?.llm
  const graphTotal = graph ? graph.entities : 0

  return (
    <div className="scroll-thin h-full overflow-y-auto p-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label="文档数" value={loading ? "—" : formatNumber(stats?.total_documents)} />
        <Metric label="切片数" value={loading ? "—" : formatNumber(stats?.total_chunks)} />
        <Metric label="向量维度" value={loading ? "—" : formatNumber(stats?.embedding_dimension)} />
        <Metric
          label="存储占用"
          value={loading ? "—" : stats ? `${stats.total_size_kb.toFixed(1)} KB` : "—"}
        />
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <section className="rounded-md border border-border p-3">
          <h2 className="mb-1.5 text-body font-medium">系统健康</h2>
          <div className="divide-y divide-border">
            <KeyValueRow label="后端响应">{health ? `${health.database.latency_ms ?? 0} ms` : "不可达"}</KeyValueRow>
            <KeyValueRow label="数据库">
              {dbOk ? "连接正常" : health?.database.error ? "查询失败" : "不可达"}
            </KeyValueRow>
            <KeyValueRow label="活跃 LLM">
              {llm?.configured ? `${llm.model ?? "—"}（${llm.source === "database" ? "数据库配置" : "环境变量"}）` : "未配置"}
            </KeyValueRow>
            <KeyValueRow label="嵌入模型">
              {health ? `${health.embedding.model} · ${health.embedding.dimension}d` : "—"}
            </KeyValueRow>
            <KeyValueRow label="图谱规模">
              {graph ? `${graphTotal} 实体 · ${graph.relations} 关系` : "未构建"}
            </KeyValueRow>
          </div>
          {dbOk && graphTotal === 0 ? (
            <p className="mt-2 rounded-md bg-muted/60 px-2.5 py-1.5 text-meta text-muted-foreground">
              图谱尚未构建。运行 <code className="font-mono">python -m src.graph build</code> 后此处会显示规模，
              图谱通道也才会生效。
            </p>
          ) : null}
        </section>

        <section className="rounded-md border border-border p-3">
          <h2 className="mb-1.5 text-body font-medium">快捷入口</h2>
          <div className="grid gap-1.5">
            {QUICK_ACTIONS.map((action) => (
              <Link
                key={action.href}
                href={action.href}
                className={cn(
                  buttonVariants({ variant: "ghost", size: "sm" }),
                  "h-auto flex-col items-start gap-0 py-1.5 text-left whitespace-normal"
                )}
              >
                <span className="text-body font-medium text-foreground">{action.label}</span>
                <span className="text-meta font-normal text-muted-foreground">{action.hint}</span>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}
