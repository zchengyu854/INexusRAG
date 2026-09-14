"use client"

import { useState } from "react"
import { SlidersHorizontal, X } from "lucide-react"

import {
  ADVANCED_FEATURE_KEYS,
  CORE_FEATURE_KEYS,
  FEATURE_OPTIONS,
  featureOptionsOf,
  selectedFeatures,
  type FeatureOption,
} from "@/components/chat/feature-toggle"
import { Button } from "@/components/ui/button"
import type { QueryMode, RerankStrategy } from "@/lib/api"
import { cn } from "@/lib/utils"

export interface FilterRow {
  key: string
  value: string
}

export type RerankChoice = RerankStrategy | "auto"

export interface RetrievalConfig {
  /** 检索范式：pipeline 单轮多通道 / agent 自主多轮。 */
  mode: QueryMode
  /** agent 模式下的最大步数，后端限制 1–12。 */
  maxSteps: number
  features: Record<string, boolean>
  topK: number
  rerankStrategy: RerankChoice
  filters: FilterRow[]
}

export const DEFAULT_RETRIEVAL_CONFIG: RetrievalConfig = {
  mode: "pipeline",
  maxSteps: 6,
  features: {},
  topK: 5,
  rerankStrategy: "auto",
  filters: [],
}

const RERANK_OPTIONS: { value: RerankChoice; label: string; hint: string }[] = [
  { value: "auto", label: "跟随环境变量", hint: "由 RERANK_STRATEGY 决定，缺省 rrf" },
  { value: "rrf", label: "rrf", hint: "直接用融合分排序，无额外开销" },
  { value: "cross", label: "cross", hint: "CrossEncoder 打分，质量最好也最慢" },
  { value: "llm", label: "llm", hint: "LLM 批量打分，一次调用" },
  { value: "colbert", label: "colbert", hint: "Late Interaction，需预下载模型" },
]

/** 把界面上的字符串行转成后端要的 filters 对象：true/false 转布尔、纯数字转数值，其余按字符串。 */
export function filtersToRecord(rows: FilterRow[]): Record<string, string | number | boolean> | null {
  const out: Record<string, string | number | boolean> = {}
  for (const row of rows) {
    const key = row.key.trim()
    if (!key) continue
    const raw = row.value.trim()
    if (raw === "true") out[key] = true
    else if (raw === "false") out[key] = false
    else if (raw !== "" && !Number.isNaN(Number(raw))) out[key] = Number(raw)
    else out[key] = raw
  }
  return Object.keys(out).length > 0 ? out : null
}

export function retrievalSummary(config: RetrievalConfig): string {
  const suffix: string[] = [`top ${config.topK}`]
  if (config.filters.length > 0) suffix.push(`过滤 ${config.filters.length}`)
  if (config.mode === "agent") return [`Agent ${config.maxSteps}步`, ...suffix].join(" · ")
  const count = selectedFeatures(config.features).length
  if (config.rerankStrategy !== "auto") suffix.unshift(`重排 ${config.rerankStrategy}`)
  return [`${count}/${FEATURE_OPTIONS.length}`, ...suffix].join(" · ")
}

/**
 * 检索设置面板：特性开关 + top_k + 元数据过滤 + 重排策略。
 *
 * 放在提问框旁的可展开浮层里（而非平铺在主界面），配合「复杂度按需展开」的定位：
 * 主流程保持干净，需要调参的人两次点击可达。
 */
export function RetrievalSettings({
  value,
  onChange,
  disabled,
}: {
  value: RetrievalConfig
  onChange: (next: RetrievalConfig) => void
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)

  function patch(part: Partial<RetrievalConfig>) {
    onChange({ ...value, ...part })
  }

  const isAgent = value.mode === "agent"

  const renderFeatureRows = (options: FeatureOption[]) => (
    <div className="space-y-0.5">
      {options.map((option) => {
        // agent 模式下 features 的语义：graph = 是否挂载 search_graph 工具；
        // rerank = 是否对累积证据池做终排；其余开关不影响工具集。
        const relevant = !isAgent || option.key === "graph" || option.key === "rerank"
        return (
          <label
            key={option.key}
            title={option.key}
            className={cn(
              "flex cursor-pointer items-start gap-2.5 rounded-md px-2 py-1.5 transition-colors hover:bg-muted",
              !relevant && "cursor-not-allowed opacity-50 hover:bg-transparent"
            )}
          >
            <input
              type="checkbox"
              checked={value.features[option.key] ?? false}
              disabled={!relevant}
              onChange={(event) => patch({ features: { ...value.features, [option.key]: event.target.checked } })}
              className="mt-0.5 size-3.5 shrink-0 rounded border-border accent-primary"
            />
            <span className="w-14 shrink-0 text-body font-medium">{option.label}</span>
            <span className="text-meta leading-tight text-muted-foreground">{option.desc}</span>
          </label>
        )
      })}
    </div>
  )

  return (
    <div className="relative">
      <Button
        variant="ghost"
        size="xs"
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        title="检索设置"
        className="text-muted-foreground"
      >
        <SlidersHorizontal />
        检索设置
        <span className="font-mono text-meta text-muted-foreground">{retrievalSummary(value)}</span>
      </Button>

      {open ? (
        <>
          <button
            type="button"
            aria-label="关闭检索设置"
            className="fixed inset-0 z-40 cursor-default"
            onClick={() => setOpen(false)}
          />
          <div className="scroll-thin absolute bottom-full left-0 z-50 mb-2 max-h-[70vh] w-[340px] overflow-y-auto rounded-lg border border-border bg-popover p-3 shadow-lg">
            {isAgent ? (
              <section className="border-b border-border pb-2.5">
                <div className="mb-1.5 flex items-center justify-between">
                  <p className="text-meta text-muted-foreground">最大步数 max_steps</p>
                  <span className="font-mono text-meta text-muted-foreground">{value.maxSteps} 步</span>
                </div>
                <input
                  type="range"
                  min={1}
                  max={12}
                  step={1}
                  value={value.maxSteps}
                  onChange={(event) => patch({ maxSteps: Number(event.target.value) })}
                  className="h-1.5 w-full accent-primary"
                />
                <p className="mt-1.5 text-meta leading-snug text-muted-foreground">
                  每步至少消耗一次大模型调用。步数越多越可能补齐跨文档线索，但延迟与成本同步上升；
                  连续两步拿不到新证据时会提前收敛，不一定跑满。
                </p>
                <p className="mt-1.5 rounded-md bg-warning/10 px-2 py-1.5 text-meta leading-snug text-warning">
                  Agent 失败或没拿到证据时会静默退回管线模式，回答形态不变，只在检视面板里标注。
                </p>
              </section>
            ) : null}

            <section className={isAgent ? "mt-3" : undefined}>
              <p className="mb-1.5 text-meta text-muted-foreground">
                {isAgent ? "Agent 可用工具" : "检索特性"}
              </p>
              {isAgent ? (
                renderFeatureRows(FEATURE_OPTIONS)
              ) : (
                <>
                  <p className="mb-1 text-meta font-medium text-foreground/80">
                    基础装置 <span className="font-normal text-muted-foreground">· 默认开启，开销小</span>
                  </p>
                  {renderFeatureRows(featureOptionsOf(CORE_FEATURE_KEYS))}
                  <p className="mb-1 mt-2.5 text-meta font-medium text-foreground/80">
                    进阶装置 <span className="font-normal text-muted-foreground">· 默认关闭，较慢或需额外资源</span>
                  </p>
                  {renderFeatureRows(featureOptionsOf(ADVANCED_FEATURE_KEYS))}
                </>
              )}
              <p className="mt-1.5 rounded-md bg-muted/60 px-2 py-1.5 text-meta leading-snug text-muted-foreground">
                {isAgent
                  ? "Agent 模式下这里决定工具集与终排：勾「图谱」挂载 search_graph，勾「重排」在循环结束后对证据池终排一次；检索本身恒可用，通道选择由 Agent 自主决定。"
                  : "全部关闭并不等于「不检索」：向量通道始终会跑，此时相当于纯向量基线。"}
              </p>
            </section>

            <section
              className="mt-3 border-t border-border pt-2.5"
            >
              <p className="mb-1.5 text-meta text-muted-foreground">重排策略</p>
              <div className="space-y-0.5">
                {RERANK_OPTIONS.map((option) => (
                  <label
                    key={option.value}
                    className={cn(
                      "flex cursor-pointer items-start gap-2.5 rounded-md px-2 py-1.5 transition-colors hover:bg-muted",
                      !value.features.rerank && "opacity-50"
                    )}
                    title={!value.features.rerank ? "需先开启「重排」特性" : option.hint}
                  >
                    <input
                      type="radio"
                      name="rerank-strategy"
                      checked={value.rerankStrategy === option.value}
                      disabled={!value.features.rerank}
                      onChange={() => patch({ rerankStrategy: option.value })}
                      className="mt-0.5 size-3.5 shrink-0 border-border accent-primary"
                    />
                    <span className="w-20 shrink-0 font-mono text-meta">{option.label}</span>
                    <span className="text-meta leading-tight text-muted-foreground">{option.hint}</span>
                  </label>
                ))}
              </div>
              {isAgent ? (
                <p className="mt-1.5 text-meta leading-snug text-muted-foreground">
                  Agent 模式下重排在整个检索循环结束后对累积证据池做一次终排，而非每步都排。
                </p>
              ) : null}
            </section>

            <section className="mt-3 border-t border-border pt-2.5">
              <div className="mb-1.5 flex items-center justify-between">
                <p className="text-meta text-muted-foreground">召回条数 top_k</p>
                <span className="font-mono text-meta text-muted-foreground">1–50</span>
              </div>
              <input
                type="number"
                min={1}
                max={50}
                value={value.topK}
                onChange={(event) => {
                  const next = Number(event.target.value)
                  patch({ topK: Number.isFinite(next) ? Math.min(50, Math.max(1, next || 5)) : 5 })
                }}
                className="h-7 w-20 rounded-md border border-border bg-background px-2 text-center font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
              />
              <p className="mt-1 text-meta leading-snug text-muted-foreground">
                进入回答上下文的证据条数。调大能提高召回，但会变慢并可能引入噪声。
              </p>
            </section>

            <section className="mt-3 border-t border-border pt-2.5">
              <div className="mb-1.5 flex items-center justify-between">
                <p className="text-meta text-muted-foreground">元数据过滤</p>
                <button
                  type="button"
                  onClick={() => patch({ filters: [...value.filters, { key: "", value: "" }] })}
                  className="rounded-md px-1.5 py-0.5 text-meta text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  + 添加
                </button>
              </div>
              {value.filters.length === 0 ? (
                <p className="text-meta leading-snug text-muted-foreground">
                  按切片元数据过滤，如 <code className="font-mono">page</code> = <code className="font-mono">5</code>、
                  <code className="font-mono">figure</code> = <code className="font-mono">true</code>。留空表示不过滤。
                </p>
              ) : (
                <div className="space-y-1">
                  {value.filters.map((row, index) => (
                    <div key={index} className="flex items-center gap-1.5">
                      <input
                        value={row.key}
                        placeholder="键"
                        onChange={(event) =>
                          patch({
                            filters: value.filters.map((item, i) =>
                              i === index ? { ...item, key: event.target.value } : item
                            ),
                          })
                        }
                        className="h-7 min-w-0 flex-1 rounded-md border border-border bg-background px-2 font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                      />
                      <input
                        value={row.value}
                        placeholder="值"
                        onChange={(event) =>
                          patch({
                            filters: value.filters.map((item, i) =>
                              i === index ? { ...item, value: event.target.value } : item
                            ),
                          })
                        }
                        className="h-7 min-w-0 flex-1 rounded-md border border-border bg-background px-2 font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                      />
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        title="移除"
                        onClick={() => patch({ filters: value.filters.filter((_, i) => i !== index) })}
                      >
                        <X />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        </>
      ) : null}
    </div>
  )
}
