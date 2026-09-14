"use client"

import { Sparkles, Workflow } from "lucide-react"

import type { QueryMode } from "@/lib/api"
import { cn } from "@/lib/utils"

export const MODE_OPTIONS: { value: QueryMode; label: string; hint: string }[] = [
  {
    value: "pipeline",
    label: "管线",
    hint: "固定单轮多通道检索，快且稳定，适合简单事实型问题",
  },
  {
    value: "agent",
    label: "Agent",
    hint: "自主多轮检索：边查边判断，适合跨文档的多步问题，延迟约为管线模式数倍",
  },
]

export function modeLabel(mode: QueryMode | null | undefined): string {
  return MODE_OPTIONS.find((option) => option.value === mode)?.label ?? "管线"
}

/**
 * 切换范式时同步调整特性开关。
 *
 * Agent 模式下 features 的语义变成「允许 Agent 使用的工具子集」，而后端在
 * features 不含 graph 时不挂载 search_graph。为了让 Agent 默认拿到全部工具
 * （设计文档 §7.1 的「默认全开」），切到 agent 时顺带打开「图谱」开关。
 */
export function applyMode<T extends { features: Record<string, boolean> }>(
  config: T,
  mode: QueryMode
): T {
  if (mode !== "agent") return { ...config, mode }
  return { ...config, mode, features: { ...config.features, graph: true } }
}

/** 范式选择器：管线 / Agent 互斥，常驻在输入框上方，避免藏在二级面板里。 */
export function ModeToggle({
  value,
  onChange,
  disabled,
}: {
  value: QueryMode
  onChange: (next: QueryMode) => void
  disabled?: boolean
}) {
  const active = MODE_OPTIONS.find((option) => option.value === value) ?? MODE_OPTIONS[0]

  return (
    <div
      className={cn(
        "flex h-6 items-center gap-0.5 rounded-md border border-border p-0.5",
        disabled && "pointer-events-none opacity-50"
      )}
      role="group"
      aria-label="检索范式"
    >
      {MODE_OPTIONS.map((option) => {
        const selected = option.value === value
        const Icon = option.value === "agent" ? Sparkles : Workflow
        return (
          <button
            key={option.value}
            type="button"
            disabled={disabled}
            aria-pressed={selected}
            title={option.hint}
            onClick={() => onChange(option.value)}
            className={cn(
              "flex h-full items-center gap-1 rounded-[5px] px-1.5 text-meta transition-colors",
              selected
                ? "bg-primary/12 font-medium text-primary"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            )}
          >
            <Icon className="size-3" />
            {option.label}
          </button>
        )
      })}
      <span className="sr-only">当前范式：{active.label}</span>
    </div>
  )
}
