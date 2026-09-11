"use client"

import Link from "next/link"
import { Loader2 } from "lucide-react"

import { kindColor, kindLabel } from "@/components/graph/kind-meta"
import { Panel, PanelBody, PanelHeader, PanelSection } from "@/components/ui/panel"
import type { GraphEdge, GraphEntityDetail } from "@/lib/api"

function EdgeList({ edges, onSelect }: { edges: GraphEdge[]; onSelect: (id: string) => void }) {
  return (
    <ul className="space-y-1">
      {edges.map((edge, index) => (
        <li key={`${edge.entity_id}-${index}`}>
          <button
            type="button"
            onClick={() => onSelect(edge.entity_id)}
            className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left transition-colors hover:bg-muted"
          >
            <span className="shrink-0 rounded bg-muted px-1 py-0.5 font-mono text-meta text-muted-foreground">
              {edge.norm_rel}
            </span>
            <span className="min-w-0 flex-1 truncate text-body">{edge.name}</span>
            <span className="shrink-0 font-mono text-meta text-muted-foreground">×{edge.weight}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}

export function EntityDetail({
  detail,
  loading,
  onSelect,
  onExpand,
}: {
  detail: GraphEntityDetail | null
  loading: boolean
  onSelect: (entityId: string) => void
  onExpand: (entityId: string) => void
}) {
  return (
    <Panel className="w-[212px] shrink-0">
      <PanelHeader title="实体详情" />
      <PanelBody className="space-y-3.5">
        {loading ? (
          <p className="flex items-center gap-2 text-meta text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            加载中…
          </p>
        ) : null}

        {!detail && !loading ? (
          <p className="text-meta leading-relaxed text-muted-foreground">
            在画布中点击任意节点查看它的类型、关系与证据切片；双击节点可切换展开中心。
          </p>
        ) : null}

        {detail ? (
          <>
            <div>
              <h3 className="break-words text-body font-medium">{detail.entity.name}</h3>
              <div className="mt-1 flex items-center gap-1.5">
                <span
                  className="rounded px-1.5 py-0.5 text-meta"
                  style={{ background: "color-mix(in oklch, " + kindColor(detail.entity.kind) + " 18%, transparent)", color: kindColor(detail.entity.kind) }}
                >
                  {kindLabel(detail.entity.kind)}
                </span>
                <span className="font-mono text-meta text-muted-foreground">
                  被提及 {detail.entity.mentions} 次
                </span>
              </div>
              {detail.entity.description ? (
                <p className="mt-1.5 text-meta leading-snug text-muted-foreground">{detail.entity.description}</p>
              ) : null}
              <button
                type="button"
                onClick={() => onExpand(detail.entity.entity_id)}
                className="mt-1.5 rounded-md border border-border px-1.5 py-0.5 text-meta text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                以此为中心展开
              </button>
            </div>

            <PanelSection label={`出边（${detail.out_edges.length}）`}>
              {detail.out_edges.length === 0 ? (
                <p className="text-meta text-muted-foreground">无</p>
              ) : (
                <EdgeList edges={detail.out_edges} onSelect={onSelect} />
              )}
            </PanelSection>

            <PanelSection label={`入边（${detail.in_edges.length}）`}>
              {detail.in_edges.length === 0 ? (
                <p className="text-meta text-muted-foreground">无</p>
              ) : (
                <EdgeList edges={detail.in_edges} onSelect={onSelect} />
              )}
            </PanelSection>

            <PanelSection label={`证据切片（${detail.evidence.length}）`}>
              {detail.evidence.length === 0 ? (
                <p className="text-meta text-muted-foreground">无</p>
              ) : (
                <ul className="space-y-1">
                  {detail.evidence.map((ref) => (
                    <li key={ref.chunk_id} className="rounded-md bg-muted/50 p-1.5">
                      <div className="flex items-center gap-1 font-mono text-meta text-muted-foreground">
                        <span className="min-w-0 flex-1 truncate">{ref.doc_name}</span>
                        <span>#{ref.chunk_index}</span>
                        {ref.page != null ? <span>p.{ref.page}</span> : null}
                      </div>
                      <p className="mt-0.5 line-clamp-2 text-meta leading-snug text-muted-foreground">{ref.text}</p>
                    </li>
                  ))}
                </ul>
              )}
              <Link
                href="/documents"
                className="mt-1 inline-block text-meta text-primary hover:underline"
              >
                前往文档页查看原文
              </Link>
            </PanelSection>
          </>
        ) : null}
      </PanelBody>
    </Panel>
  )
}
