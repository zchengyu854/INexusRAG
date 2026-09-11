"use client"

import { useState } from "react"
import { SlidersHorizontal } from "lucide-react"

import { Button } from "@/components/ui/button"

/**
 * 检索特性开关。开关名必须与后端 schemas.FeatureName、retrieval.ALL_FEATURES 三处同步。
 */
export const FEATURE_OPTIONS: { key: string; label: string; desc: string }[] = [
  { key: "routing", label: "路由", desc: "先定位相关文档，缩小检索范围" },
  { key: "keywords", label: "关键词", desc: "精确匹配专有名词、代号、数字" },
  { key: "decompose", label: "分解", desc: "将复杂问题拆成子问题分别检索" },
  { key: "stepback", label: "退步", desc: "先把细节问题抽象为概念问题" },
  { key: "hyde", label: "假想文档", desc: "生成假想答案段落辅助语义检索" },
  { key: "rerank", label: "重排", desc: "对候选结果精细排序（较慢）" },
  { key: "graph", label: "图谱", desc: "图谱多跳检索，串联分散线索" },
]

export const DEFAULT_FEATURES = ["routing", "keywords", "decompose", "stepback", "hyde"]

export function initialFeatureState(features?: string[] | null): Record<string, boolean> {
  const active = features ?? DEFAULT_FEATURES
  return Object.fromEntries(FEATURE_OPTIONS.map((option) => [option.key, active.includes(option.key)]))
}

export function selectedFeatures(checked: Record<string, boolean>): string[] {
  return FEATURE_OPTIONS.filter((option) => checked[option.key]).map((option) => option.key)
}

export function featureLabels(keys: string[] | null | undefined): string | null {
  if (!keys || keys.length === 0) return null
  return keys.map((key) => FEATURE_OPTIONS.find((option) => option.key === key)?.label ?? key).join(" · ")
}

export function FeatureToggle({
  checked,
  onChange,
}: {
  checked: Record<string, boolean>
  onChange: (next: Record<string, boolean>) => void
}) {
  const [open, setOpen] = useState(false)
  const count = selectedFeatures(checked).length

  return (
    <div className="relative">
      <Button
        variant="ghost"
        size="xs"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        title="检索特性"
        className="text-muted-foreground"
      >
        <SlidersHorizontal />
        检索特性
        <span className="font-mono text-meta text-muted-foreground">{count}/7</span>
      </Button>

      {open ? (
        <>
          <button
            type="button"
            aria-label="关闭特性面板"
            className="fixed inset-0 z-40 cursor-default"
            onClick={() => setOpen(false)}
          />
          <div className="absolute bottom-full left-0 z-50 mb-2 w-80 rounded-lg border border-border bg-popover p-3 shadow-lg">
            <p className="mb-2 text-meta text-muted-foreground">检索特性</p>
            <div className="space-y-0.5">
              {FEATURE_OPTIONS.map((option) => (
                <label
                  key={option.key}
                  title={option.key}
                  className="flex cursor-pointer items-start gap-2.5 rounded-md px-2 py-1.5 transition-colors hover:bg-muted"
                >
                  <input
                    type="checkbox"
                    checked={checked[option.key] ?? false}
                    onChange={(event) => onChange({ ...checked, [option.key]: event.target.checked })}
                    className="mt-0.5 size-3.5 shrink-0 rounded border-border accent-primary"
                  />
                  <span className="w-14 shrink-0 text-body font-medium">{option.label}</span>
                  <span className="text-meta leading-tight text-muted-foreground">{option.desc}</span>
                </label>
              ))}
            </div>
          </div>
        </>
      ) : null}
    </div>
  )
}
