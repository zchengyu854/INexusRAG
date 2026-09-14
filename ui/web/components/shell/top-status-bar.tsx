"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useState } from "react"

import {
  activateProvider,
  fetchProviders,
  getHealth,
  type HealthStatus,
  type LLMProvider,
} from "@/lib/api"
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
  const [providers, setProviders] = useState<LLMProvider[]>([])
  const [switching, setSwitching] = useState(false)

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

  useEffect(() => {
    // 只用于「手动切换模型」下拉；失败不影响状态展示
    fetchProviders()
      .then(setProviders)
      .catch(() => setProviders([]))
  }, [])

  async function handleSwitch(providerId: string) {
    setSwitching(true)
    try {
      await activateProvider(providerId)
      // 切换后立刻重取健康状态：LLM 的真实可用性要马上反映出来，而不是等下一轮轮询
      const [nextHealth, nextProviders] = await Promise.all([getHealth(), fetchProviders()])
      setHealth(nextHealth)
      setProviders(nextProviders)
      setReachable(true)
    } catch {
      // 切换失败不改动既有展示，用户可去设置页看具体原因
    } finally {
      setSwitching(false)
    }
  }

  const pageTitle = title ?? PAGE_TITLES[pathname] ?? "NexusRAG"
  const dbOk = reachable && health?.database.ok !== false
  const llm = health?.llm
  // 三态：未验证 / 不可用 / 可用。以前只判断 configured，于是 provider 被拒时依旧是绿灯
  const llmState = !llm?.configured
    ? "unconfigured"
    : llm.ok === false
      ? "down"
      : llm.ok === true
        ? "up"
        : "unverified"
  const llmText =
    llmState === "unconfigured"
      ? "未配置 LLM"
      : llmState === "down"
        ? "LLM 不可用"
        : llmState === "unverified"
          ? "LLM 未验证"
          : (llm?.model ?? "")
  const llmTitle =
    llmState === "down"
      ? [llm?.reason, llm?.hint ? `建议：${llm.hint}` : null].filter(Boolean).join("\n")
      : llmState === "unverified"
        ? "本次启动后还没有成功调用过模型，点右侧下拉切换或去设置页测试连接"
        : `${llm?.source ?? ""} / ${llm?.model ?? ""}`

  const activeProvider = providers.find((provider) => provider.active)
  const llmChipClass = cn(
    "flex items-center gap-1.5 rounded-md border px-1.5 py-0.5 text-meta",
    llmState === "down"
      ? "border-destructive/40 text-destructive"
      : llmState === "up"
        ? "border-border text-muted-foreground"
        : "border-warning/40 text-warning"
  )
  const llmChip = (
    <span className={llmChipClass} title={llmTitle}>
      <span
        className={cn(
          "size-[7px] rounded-full",
          llmState === "down" ? "bg-destructive" : llmState === "up" ? "bg-success" : "bg-warning"
        )}
      />
      <span className="max-w-[160px] truncate font-mono">{llmText}</span>
    </span>
  )

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
          {!reachable ? "后端不可达" : dbOk ? "服务正常" : "数据库异常"}
        </span>

        {llmState === "up" ? (
          llmChip
        ) : (
          // 不可用/未验证/未配置时点一下直接去设置页——否则用户不知道下一步该做什么
          <Link href="/settings" className="transition-opacity hover:opacity-80">
            {llmChip}
          </Link>
        )}

        {providers.length > 0 ? (
          <select
            value={activeProvider?.id ?? ""}
            disabled={switching}
            onChange={(event) => void handleSwitch(event.target.value)}
            title="切换生效的模型（立即生效）"
            className="h-6 max-w-[200px] rounded-md border border-border bg-background px-1 font-mono text-meta text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/40 disabled:opacity-50"
          >
            {!activeProvider ? <option value="">（未指定生效项）</option> : null}
            {providers.map((provider) => (
              <option key={provider.id} value={provider.id}>
                {provider.name} · {provider.model}
              </option>
            ))}
          </select>
        ) : (
          <Link
            href="/settings"
            className="font-mono text-meta text-muted-foreground underline-offset-2 hover:underline"
            title="还没有配置任何 provider：去设置页填入 base_url 与密钥后即可切换"
          >
            去配置
          </Link>
        )}

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
