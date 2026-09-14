"use client"

import { Check, ChevronRight, GitBranch, Search } from "lucide-react"

import { cn } from "@/lib/utils"
import type { AgentStep, AgentTrace } from "@/lib/api"

/** 终止原因：后端 termination 字段 → 展示文案与语义色。 */
const TERMINATION: Record<string, { label: string; tone: string; desc: string }> = {
  answered: { label: "证据充足", tone: "text-primary", desc: "Agent 判定证据足够，主动收敛" },
  budget: { label: "预算耗尽", tone: "text-warning", desc: "LLM 调用数或时间触顶，强制收敛" },
  max_steps: { label: "到达步数上限", tone: "text-warning", desc: "跑满 max_steps 后强制收敛" },
  stagnant: { label: "边际收益为 0", tone: "text-warning", desc: "连续两步未新增证据，提前收敛" },
  error: { label: "中途出错", tone: "text-destructive", desc: "LLM 调用异常，改用已收集证据作答" },
}

const TOOL_META: Record<string, { label: string; Icon: typeof Search }> = {
  search_knowledge: { label: "知识库检索", Icon: Search },
  search_graph: { label: "图谱多跳", Icon: GitBranch },
  answer: { label: "终止检索", Icon: Check },
}

function toolMeta(tool: string) {
  return TOOL_META[tool] ?? { label: tool, Icon: Search }
}

function formatMs(value: number): string {
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${Math.round(value)}ms`
}

/** budget 是后端透传的字典，字段名可能与版本不一致，取值一律容错。 */
function readNumber(source: Record<string, unknown>, ...keys: string[]): number | null {
  for (const key of keys) {
    const value = source[key]
    if (typeof value === "number" && Number.isFinite(value)) return value
  }
  return null
}

function StepRow({ step, defaultOpen }: { step: AgentStep; defaultOpen: boolean }) {
  const meta = toolMeta(step.tool)
  const query = typeof step.args?.query === "string" ? step.args.query : null
  const reason = typeof step.args?.reason === "string" ? step.args.reason : null
  const hasDetail = Boolean(step.thought || step.observation || step.error || reason)

  return (
    <li className="relative pl-6">
      <span className="absolute left-0 top-0.5 flex size-4 items-center justify-center rounded-full bg-muted">
        <meta.Icon className="size-2.5 text-muted-foreground" />
      </span>

      {hasDetail ? (
        <details open={defaultOpen}>
          <summary className="cursor-pointer list-none">
            <StepHeadline step={step} query={query} />
          </summary>
          <div className="mt-1 space-y-1 border-l border-border pl-2">
            {step.thought ? (
              <p className="text-meta leading-snug text-muted-foreground">{step.thought}</p>
            ) : null}
            {reason ? (
              <p className="text-meta leading-snug text-muted-foreground">理由：{reason}</p>
            ) : null}
            {step.observation ? (
              <p className="rounded-md bg-muted/50 px-2 py-1 font-mono text-meta leading-snug text-muted-foreground">
                {step.observation}
              </p>
            ) : null}
            {step.error ? (
              <p className="text-meta leading-snug text-destructive">失败：{step.error}</p>
            ) : null}
          </div>
        </details>
      ) : (
        <StepHeadline step={step} query={query} />
      )}
    </li>
  )
}

function StepHeadline({ step, query }: { step: AgentStep; query: string | null }) {
  const meta = toolMeta(step.tool)
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="shrink-0 font-mono text-meta text-muted-foreground">{step.step}</span>
      <span className="shrink-0 text-meta font-medium">{meta.label}</span>
      {query ? (
        <span className="min-w-0 flex-1 truncate text-meta text-muted-foreground" title={query}>
          {query}
        </span>
      ) : null}
      <span className="ml-auto flex shrink-0 items-center gap-1.5">
        {step.new_chunks > 0 ? (
          <span className="rounded border border-primary/40 px-1 font-mono text-meta text-primary">
            +{step.new_chunks}
          </span>
        ) : null}
        {step.latency_ms > 0 ? (
          <span className="font-mono text-meta text-muted-foreground">
            {formatMs(step.latency_ms)}
          </span>
        ) : null}
      </span>
    </div>
  )
}

/**
 * Agent 轨迹时间线：把 ReAct 循环的每一步摊开——选了什么工具、拿到什么观测、
 * 新增了多少证据。步数由 Agent 自己决定，所以这里也是判断它有没有空转的依据。
 */
export function AgentTimeline({ trace }: { trace: AgentTrace }) {
  const termination = trace.termination ? TERMINATION[trace.termination] : null
  const llmCalls = readNumber(trace.budget, "llm_calls")
  const maxCalls = readNumber(trace.budget, "max_steps_llm_calls", "max_llm_calls")
  const elapsed = readNumber(trace.budget, "elapsed_ms")
  const lastStep = trace.steps[trace.steps.length - 1]
  const searched = trace.steps.filter((step) => step.tool !== "answer").length

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1">
        <span
          className={cn(
            "rounded-md border border-border px-1.5 py-0.5 text-meta",
            termination?.tone ?? "text-muted-foreground"
          )}
          title={termination?.desc}
        >
          {termination?.label ?? trace.termination ?? "未知"}
        </span>
        <span className="rounded-md border border-border px-1.5 py-0.5 font-mono text-meta text-muted-foreground">
          检索 {searched} 步
        </span>
        <span className="rounded-md border border-border px-1.5 py-0.5 font-mono text-meta text-muted-foreground">
          证据 {trace.evidence_chunks} 块
        </span>
        {trace.rerank ? (
          <span
            className="rounded-md border border-border px-1.5 py-0.5 font-mono text-meta text-muted-foreground"
            title="检索循环结束后对累积证据池做了一次终排"
          >
            终排 {trace.rerank}
          </span>
        ) : null}
        {llmCalls != null ? (
          <span className="rounded-md border border-border px-1.5 py-0.5 font-mono text-meta text-muted-foreground">
            LLM {llmCalls}
            {maxCalls != null ? `/${maxCalls}` : ""}
          </span>
        ) : null}
        {elapsed != null ? (
          <span className="rounded-md border border-border px-1.5 py-0.5 font-mono text-meta text-muted-foreground">
            {formatMs(elapsed)}
          </span>
        ) : null}
      </div>

      {termination ? (
        <p className="text-meta leading-snug text-muted-foreground">{termination.desc}</p>
      ) : null}

      {trace.steps.length === 0 ? (
        <p className="text-meta leading-snug text-muted-foreground">本次没有留下任何步骤记录。</p>
      ) : (
        <ol className="space-y-2">
          {trace.steps.map((step) => (
            <StepRow key={step.step} step={step} defaultOpen={step.step === lastStep?.step} />
          ))}
        </ol>
      )}

      {trace.tools.length > 0 ? (
        <p className="flex flex-wrap items-center gap-1 text-meta text-muted-foreground">
          <span className="shrink-0">可用工具</span>
          {trace.tools.map((tool) => (
            <span
              key={tool}
              className="rounded border border-border px-1 font-mono text-meta text-muted-foreground"
            >
              {tool}
            </span>
          ))}
        </p>
      ) : null}
    </div>
  )
}

export function AgentTimelineEmpty({ hint }: { hint: string }) {
  return (
    <p className="flex items-start gap-1.5 text-meta leading-relaxed text-muted-foreground">
      <ChevronRight className="mt-0.5 size-3 shrink-0" />
      {hint}
    </p>
  )
}
