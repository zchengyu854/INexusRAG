"use client"

import { useCallback, useEffect, useState } from "react"
import { Loader2, Play, Plus } from "lucide-react"

import { DEFAULT_FEATURES } from "@/components/chat/feature-toggle"
import { Button } from "@/components/ui/button"
import { Metric } from "@/components/ui/metric"
import { addEvalCase, getEvalCases, runEval, seedEvalCases, type EvalCase, type EvalRow } from "@/lib/api"
import { cn } from "@/lib/utils"

/**
 * 配置矩阵与后端 `_default_eval_configs()` 对齐。
 * 后端的 "all" 一档与 "+graph+rerank" 特性集完全相同（ALL_FEATURES 就是默认集加这两项），
 * 因此这里不再重复列出，避免给出两组数值一样的结果。
 */
const CONFIG_MATRIX: { label: string; features: string[] | null; hint: string }[] = [
  { label: "纯向量", features: [], hint: "仅向量通道，作为对比基线" },
  { label: "默认组合", features: null, hint: "路由 + 关键词 + 规划类特性" },
  { label: "+ 图谱", features: [...DEFAULT_FEATURES, "graph"], hint: "叠加图谱多跳通道" },
  { label: "+ 图谱 + 重排", features: [...DEFAULT_FEATURES, "graph", "rerank"], hint: "再叠加末端重排" },
]

const GRID = "grid grid-cols-[minmax(0,1fr)_64px_64px_64px] items-center gap-2"

export function EvalPage() {
  const [cases, setCases] = useState<EvalCase[]>([])
  const [k, setK] = useState(5)
  const [enabled, setEnabled] = useState<boolean[]>(() => CONFIG_MATRIX.map(() => true))
  const [rows, setRows] = useState<EvalRow[] | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [draftQuestion, setDraftQuestion] = useState("")
  const [draftRefs, setDraftRefs] = useState("")
  const [adding, setAdding] = useState(false)

  const loadCases = useCallback(async () => {
    try {
      setCases(await getEvalCases())
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载评测集失败")
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadCases()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadCases])

  async function handleRun() {
    setRunning(true)
    setError(null)
    setNotice(null)
    try {
      const configs = CONFIG_MATRIX.filter((_, index) => enabled[index]).map((item) => ({
        label: item.label,
        features: item.features,
      }))
      const result = await runEval(k, configs.length ? configs : undefined)
      setRows(result.rows)
      setNotice(`已跑完 ${result.case_count} 条评测例 × ${result.rows.length} 组配置`)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "运行评测失败")
    } finally {
      setRunning(false)
    }
  }

  async function handleSeed() {
    try {
      const result = await seedEvalCases()
      setNotice(result.added > 0 ? `新增 ${result.added} 条内置评测例` : "内置评测例已存在，无需重复播种")
      await loadCases()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "播种失败")
    }
  }

  async function handleAddCase() {
    if (!draftQuestion.trim() || !draftRefs.trim()) return
    setAdding(true)
    setError(null)
    try {
      await addEvalCase({ question: draftQuestion.trim(), expected_refs: draftRefs.trim() })
      setDraftQuestion("")
      setDraftRefs("")
      await loadCases()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "新增评测例失败")
    } finally {
      setAdding(false)
    }
  }

  const baseline = rows && rows.length > 0 ? rows[0].mrr : 0

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-[288px] shrink-0 flex-col gap-2.5 overflow-y-auto border-r border-border p-2.5">
        <div className="flex items-center justify-between">
          <h2 className="text-body font-medium">评测集（{cases.length}）</h2>
          <Button variant="ghost" size="xs" onClick={() => void handleSeed()}>
            播种内置
          </Button>
        </div>

        <div className="space-y-1">
          {cases.length === 0 ? (
            <p className="rounded-md bg-muted/50 px-2 py-2 text-meta text-muted-foreground">
              还没有评测例。可以点「播种内置」加入 6 条多跳评测例，或在下方手动新增。
            </p>
          ) : (
            cases.map((item) => (
              <div key={item.id} className="rounded-md border border-border p-2">
                <p className="line-clamp-2 text-body">{item.question}</p>
                <p className="mt-1 font-mono text-meta text-muted-foreground">{item.expected_refs}</p>
              </div>
            ))
          )}
        </div>

        <div className="mt-1 border-t border-border pt-2">
          <p className="mb-1.5 text-body font-medium">新增评测例</p>
          <textarea
            value={draftQuestion}
            onChange={(event) => setDraftQuestion(event.target.value)}
            placeholder="问题"
            rows={2}
            className="mb-1.5 w-full resize-none rounded-md border border-border bg-background px-2 py-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
          />
          <input
            value={draftRefs}
            onChange={(event) => setDraftRefs(event.target.value)}
            placeholder="期望引用，如 RAG.pdf:155|RAG.pdf:277"
            className="mb-1.5 w-full rounded-md border border-border bg-background px-2 py-1.5 font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
          />
          <Button
            variant="outline"
            size="sm"
            className="w-full"
            onClick={() => void handleAddCase()}
            disabled={adding || !draftQuestion.trim() || !draftRefs.trim()}
          >
            <Plus />
            添加
          </Button>
          <p className="mt-1.5 text-meta text-muted-foreground">
            引用格式为 <code className="font-mono">文件名:切片序号</code>，多个用 | 分隔。
          </p>
        </div>
      </aside>

      <section className="scroll-thin min-h-0 flex-1 overflow-y-auto p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-medium">消融评测</h2>
            <p className="mt-0.5 text-meta text-muted-foreground">
              对同一组评测例跑不同特性组合，比较 Hit@K 与 MRR。指标为检索级，不依赖 LLM 判官。
            </p>
          </div>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1.5 text-body text-muted-foreground">
              K
              <input
                type="number"
                min={1}
                max={20}
                value={k}
                onChange={(event) => setK(Math.min(20, Math.max(1, Number(event.target.value) || 5)))}
                className="h-7 w-14 rounded-md border border-border bg-background px-2 text-center font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
              />
            </label>
            <Button size="sm" onClick={() => void handleRun()} disabled={running || cases.length === 0}>
              {running ? <Loader2 className="animate-spin" /> : <Play />}
              {running ? "运行中…" : "运行消融"}
            </Button>
          </div>
        </div>

        <div className="mb-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Metric label="评测例" value={cases.length} />
          <Metric label="K" value={k} />
          <Metric label="配置组" value={enabled.filter(Boolean).length} />
          <Metric label="已跑结果" value={rows ? rows.length : "—"} />
        </div>

        <section className="mb-3 rounded-md border border-border p-3">
          <p className="mb-1.5 text-body font-medium">配置矩阵</p>
          <div className="space-y-0.5">
            {CONFIG_MATRIX.map((item, index) => (
              <label
                key={item.label}
                className="flex cursor-pointer items-center gap-2.5 rounded-md px-1.5 py-1 transition-colors hover:bg-muted"
              >
                <input
                  type="checkbox"
                  checked={enabled[index]}
                  onChange={(event) =>
                    setEnabled((previous) => previous.map((value, i) => (i === index ? event.target.checked : value)))
                  }
                  className="size-3.5 shrink-0 rounded border-border accent-primary"
                />
                <span className="w-28 shrink-0 text-body font-medium">{item.label}</span>
                <span className="text-meta text-muted-foreground">{item.hint}</span>
              </label>
            ))}
          </div>
        </section>

        {error ? (
          <p className="mb-3 rounded-md border border-destructive/30 px-2.5 py-1.5 text-body text-destructive">
            {error}
          </p>
        ) : null}
        {notice ? (
          <p className="mb-3 rounded-md bg-muted/60 px-2.5 py-1.5 text-body text-muted-foreground">{notice}</p>
        ) : null}

        {running ? (
          <div className="flex items-center justify-center gap-2 py-14 text-body text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" />
            正在逐组运行。每组都要对全部评测例做一次检索，耗时与评测例数量成正比，请稍候…
          </div>
        ) : rows ? (
          <div className="overflow-hidden rounded-md border border-border">
            <div className={`${GRID} border-b border-border bg-muted/40 px-3 py-2 text-meta text-muted-foreground`}>
              <span>配置</span>
              <span className="text-right">Hit@{k}</span>
              <span className="text-right">MRR</span>
              <span className="text-right">Δ MRR</span>
            </div>
            <ul className="divide-y divide-border">
              {rows.map((row, index) => {
                const delta = row.mrr - baseline
                return (
                  <li key={`${row.label}-${index}`} className={cn(GRID, "px-3 py-2")}>
                    <span className="truncate text-body">{row.label}</span>
                    <span className="text-right font-mono text-xs tabular-nums">{row.hit_at_k.toFixed(2)}</span>
                    <span className="text-right font-mono text-xs tabular-nums">{row.mrr.toFixed(3)}</span>
                    <span
                      className={cn(
                        "text-right font-mono text-xs tabular-nums",
                        index === 0 ? "text-muted-foreground" : delta > 0 ? "text-success" : delta < 0 ? "text-destructive" : "text-muted-foreground"
                      )}
                    >
                      {index === 0 ? "基线" : `${delta >= 0 ? "+" : ""}${delta.toFixed(3)}`}
                    </span>
                  </li>
                )
              })}
            </ul>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center rounded-md border border-dashed border-border py-16 text-center">
            <p className="text-body text-muted-foreground">
              选择配置后点「运行消融」查看结果。若评测集为空，先点左侧「播种内置」。
            </p>
          </div>
        )}
      </section>
    </div>
  )
}
