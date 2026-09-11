"use client"

import { ChevronRight, Loader2 } from "lucide-react"

import { featureLabel } from "@/components/chat/feature-toggle"
import { BarRow } from "@/components/ui/metric"
import { Panel, PanelBody, PanelHeader, PanelSection } from "@/components/ui/panel"
import type { QueryTrace, Source } from "@/lib/api"

function formatMs(value: number): string {
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${Math.round(value)}ms`
}

function Chip({
  children,
  title,
  tone = "muted",
}: {
  children: React.ReactNode
  title?: string
  tone?: "muted" | "primary"
}) {
  const toneClass = tone === "primary" ? "border-primary/40 text-primary" : "border-border text-muted-foreground"
  return (
    <span
      title={title}
      className={`max-w-full truncate rounded-md border px-1.5 py-0.5 font-mono text-meta ${toneClass}`}
    >
      {children}
    </span>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-2 text-meta">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="min-w-0 truncate text-right font-mono text-muted-foreground">{children}</span>
    </div>
  )
}

/** 检索检视面板：把 multi_query_search 的内部过程摊开。默认收起，由问答页控制显隐。 */
export function RetrievalInspector({
  trace,
  sources,
  loading,
  onClose,
}: {
  trace: QueryTrace | null
  sources: Source[]
  loading: boolean
  onClose: () => void
}) {
  const maxHits = trace ? Math.max(...trace.channels.map((channel) => channel.hits), 1) : 1
  const filterEntries = trace ? Object.entries(trace.params.filters ?? {}) : []

  return (
    <Panel className="w-[264px] shrink-0">
      <PanelHeader
        title="检索检视"
        actions={
          <button
            type="button"
            onClick={onClose}
            title="收起面板"
            className="flex h-6 items-center gap-0.5 rounded-md px-1.5 text-meta text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            收起
            <ChevronRight className="size-3" />
          </button>
        }
      />
      <PanelBody className="space-y-3.5">
        {loading ? (
          <p className="flex items-center gap-2 text-meta text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            检索中…
          </p>
        ) : null}

        {!trace && !loading ? (
          <p className="text-meta leading-relaxed text-muted-foreground">
            提问后这里会显示本次检索的规划结果、各通道命中量、融合规模与耗时分解，并标出哪些特性实际生效。
          </p>
        ) : null}

        {trace ? (
          <>
            <PanelSection label="本次参数">
              <div className="space-y-0.5">
                <Row label="top_k">{trace.params.top_k}</Row>
                <Row label="重排策略">{trace.params.rerank_strategy ?? "未启用"}</Row>
                <Row label="元数据过滤">
                  {filterEntries.length === 0
                    ? "无"
                    : filterEntries.map(([key, value]) => `${key}=${String(value)}`).join(", ")}
                </Row>
              </div>
            </PanelSection>

            <PanelSection label="生效特性">
              <div className="flex flex-wrap gap-1">
                {trace.applied.length === 0 ? (
                  <span className="text-meta text-muted-foreground">无（仅向量通道）</span>
                ) : (
                  trace.applied.map((name) => (
                    <Chip key={name} tone="primary">
                      {featureLabel(name)}
                    </Chip>
                  ))
                )}
              </div>
            </PanelSection>

            {trace.skipped.length > 0 ? (
              <PanelSection label={`未生效（${trace.skipped.length}）`}>
                <ul className="space-y-1.5">
                  {trace.skipped.map((item) => (
                    <li key={item.name} className="rounded-md bg-muted/50 px-2 py-1.5">
                      <p className="text-meta font-medium text-warning">{featureLabel(item.name)}</p>
                      <p className="mt-0.5 text-meta leading-snug text-muted-foreground">{item.reason}</p>
                    </li>
                  ))}
                </ul>
              </PanelSection>
            ) : null}

            <PanelSection label="规划输出">
              <div className="flex flex-wrap gap-1">
                <Chip title={trace.plan.subs.join("\n") || undefined}>子问题 ×{trace.plan.subs.length}</Chip>
                <Chip>退步 ×{trace.plan.step_back ? 1 : 0}</Chip>
                <Chip>HyDE ×{trace.plan.hyde ? 1 : 0}</Chip>
                <Chip>查询 ×{trace.plan.queries.length}</Chip>
              </div>
              {trace.plan.subs.length > 0 ? (
                <ol className="mt-1.5 space-y-1 text-meta leading-snug text-muted-foreground">
                  {trace.plan.subs.slice(0, 5).map((sub, index) => (
                    <li key={index} className="line-clamp-2">
                      {index + 1}. {sub}
                    </li>
                  ))}
                </ol>
              ) : null}
              {trace.plan.step_back ? (
                <p className="mt-1 line-clamp-2 text-meta leading-snug text-muted-foreground">
                  退步：{trace.plan.step_back}
                </p>
              ) : null}
              {trace.plan.hyde ? (
                <details className="mt-1">
                  <summary className="cursor-pointer text-meta text-muted-foreground">假想文档</summary>
                  <p className="mt-1 line-clamp-6 text-meta leading-snug text-muted-foreground">{trace.plan.hyde}</p>
                </details>
              ) : null}
            </PanelSection>

            <PanelSection label="通道命中（融合前候选）">
              <div className="space-y-1">
                {trace.channels.map((channel) => (
                  <BarRow
                    key={channel.name}
                    label={channel.label}
                    value={channel.hits}
                    max={maxHits}
                    display={String(channel.hits)}
                  />
                ))}
              </div>
              {trace.channels.some((channel) => channel.detail) ? (
                <ul className="mt-1 space-y-0.5">
                  {trace.channels
                    .filter((channel) => channel.detail)
                    .map((channel) => (
                      <li key={channel.name} className="text-meta text-muted-foreground">
                        {channel.label}：{channel.detail}
                      </li>
                    ))}
                </ul>
              ) : null}
            </PanelSection>

            <PanelSection label="路由判定">
              <div className="space-y-0.5">
                <Row label="命中文档">{trace.routing.routed_docs} 篇</Row>
                <Row label="最高分 / 阈值">
                  {trace.routing.top_score.toFixed(3)} / {trace.routing.min_score}
                </Row>
                <Row label="全局兜底">{trace.routing.fallback ? "已追加" : "未追加"}</Row>
              </div>
            </PanelSection>

            <PanelSection label="融合与重排">
              <div className="space-y-0.5">
                <Row label="融合输入组数">{trace.fusion.channels}</Row>
                <Row label="融合前去重">{trace.fusion.pre_merge}</Row>
                <Row label="融合后">{trace.fusion.post_merge}</Row>
                {trace.fusion.rerank ? <Row label="重排">{trace.fusion.rerank}</Row> : null}
                <Row label="最终返回">{trace.fusion.final}</Row>
              </div>
            </PanelSection>

            <PanelSection label="耗时分解">
              <div className="space-y-0.5">
                <Row label="规划">{formatMs(trace.timings.plan_ms)}</Row>
                <Row label="检索">{formatMs(trace.timings.retrieve_ms)}</Row>
                <Row label="生成">{formatMs(trace.timings.generate_ms)}</Row>
              </div>
            </PanelSection>
          </>
        ) : null}

        {sources.length > 0 ? (
          <PanelSection label={`证据（${sources.length}）`}>
            <ol className="space-y-1.5">
              {sources.map((source, index) => (
                <li key={index} className="rounded-md bg-muted/50 p-2">
                  <div className="flex items-center gap-1.5 text-meta">
                    <span className="font-mono text-primary">{index + 1}</span>
                    <span className="min-w-0 flex-1 truncate font-medium">{source.doc_name}</span>
                    {source.score != null ? (
                      <span className="font-mono text-muted-foreground">{source.score.toFixed(3)}</span>
                    ) : null}
                  </div>
                  <div className="mt-0.5 font-mono text-meta text-muted-foreground">
                    {source.page != null ? `p.${source.page} · ` : null}
                    {source.chunk_index != null ? `#${source.chunk_index}` : null}
                  </div>
                  <p className="mt-1 line-clamp-3 whitespace-pre-wrap text-meta leading-snug text-muted-foreground">
                    {source.text}
                  </p>
                </li>
              ))}
            </ol>
          </PanelSection>
        ) : null}
      </PanelBody>
    </Panel>
  )
}
