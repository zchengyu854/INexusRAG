"use client"

import dynamic from "next/dynamic"
import { useCallback, useEffect, useState } from "react"
import { Loader2, RefreshCw, Search } from "lucide-react"

import { EntityDetail } from "@/components/graph/entity-detail"
import { kindLabel } from "@/components/graph/kind-meta"
import { Button } from "@/components/ui/button"
import {
  getGraphEntity,
  getGraphStats,
  getSubgraph,
  searchGraphEntities,
  type GraphEntity,
  type GraphEntityDetail,
  type GraphStats,
  type GraphSubgraph,
} from "@/lib/api"
import { cn } from "@/lib/utils"

const KIND_ORDER = ["concept", "method", "metric", "product", "org", "person", "other"]

/** three.js 依赖 WebGL，服务端渲染没有意义且会触发 hydration 警告，故只在客户端加载。 */
const GraphCanvas = dynamic(
  () => import("@/components/graph/graph-canvas").then((m) => m.GraphCanvas),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center gap-2 text-body text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" />
        正在加载三维画布…
      </div>
    ),
  },
)

export function GraphPage() {
  const [stats, setStats] = useState<GraphStats | null>(null)
  const [entities, setEntities] = useState<GraphEntity[]>([])
  const [query, setQuery] = useState("")
  const [kind, setKind] = useState<string | null>(null)
  const [hops, setHops] = useState(2)
  const [anchorId, setAnchorId] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [subgraph, setSubgraph] = useState<GraphSubgraph | null>(null)
  const [detail, setDetail] = useState<GraphEntityDetail | null>(null)
  const [loadingGraph, setLoadingGraph] = useState(false)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.allSettled([getGraphStats(), searchGraphEntities("", undefined, 30)]).then(
      ([statsResult, entitiesResult]) => {
        if (cancelled) return
        if (statsResult.status === "fulfilled") setStats(statsResult.value)
        if (entitiesResult.status === "fulfilled") {
          setEntities(entitiesResult.value)
          const first = entitiesResult.value[0]
          if (first) {
            setAnchorId(first.entity_id)
            setSelectedId(first.entity_id)
          }
        } else {
          setError("无法加载实体列表，请确认后端已启动")
        }
      }
    )
    return () => {
      cancelled = true
    }
  }, [])

  const loadSubgraph = useCallback(async (entityId: string, depth: number) => {
    setLoadingGraph(true)
    try {
      setSubgraph(await getSubgraph(entityId, depth, 150))
      setError(null)
    } catch (caught) {
      setSubgraph(null)
      setError(caught instanceof Error ? caught.message : "加载子图失败")
    } finally {
      setLoadingGraph(false)
    }
  }, [])

  useEffect(() => {
    if (!anchorId) return
    const timer = window.setTimeout(() => {
      void loadSubgraph(anchorId, hops)
    }, 0)
    return () => window.clearTimeout(timer)
  }, [anchorId, hops, loadSubgraph])

  useEffect(() => {
    if (!selectedId) return
    let cancelled = false
    const timer = window.setTimeout(() => {
      void (async () => {
        setLoadingDetail(true)
        try {
          const data = await getGraphEntity(selectedId)
          if (!cancelled) setDetail(data)
        } catch {
          if (!cancelled) setDetail(null)
        } finally {
          if (!cancelled) setLoadingDetail(false)
        }
      })()
    }, 0)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [selectedId])

  async function runSearch(nextQuery: string, nextKind: string | null) {
    try {
      const rows = await searchGraphEntities(nextQuery, nextKind ?? undefined, 30)
      setEntities(rows)
      setError(null)
    } catch (caught) {
      setEntities([])
      setError(caught instanceof Error ? caught.message : "搜索失败")
    }
  }

  const totalEntities = stats?.entities ?? 0
  const empty = totalEntities === 0

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-[152px] shrink-0 flex-col gap-2.5 overflow-y-auto border-r border-border p-2.5">
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2 size-3 -translate-y-1/2 text-muted-foreground" />
          <input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              void runSearch(event.target.value, kind)
            }}
            placeholder="搜索实体"
            className="h-7 w-full rounded-md border border-border bg-background pr-2 pl-6.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
          />
        </div>

        <div>
          <p className="mb-1 text-meta text-muted-foreground">类型</p>
          <div className="space-y-0.5">
            <button
              type="button"
              onClick={() => {
                setKind(null)
                void runSearch(query, null)
              }}
              className={cn(
                "flex w-full items-center justify-between rounded-md px-1.5 py-1 text-body transition-colors",
                kind === null ? "bg-primary/12 text-primary" : "text-muted-foreground hover:bg-muted"
              )}
            >
              <span>全部</span>
              <span className="font-mono text-meta">{totalEntities}</span>
            </button>
            {KIND_ORDER.filter((name) => stats?.kinds?.[name]).map((name) => (
              <button
                key={name}
                type="button"
                onClick={() => {
                  setKind(name)
                  void runSearch(query, name)
                }}
                className={cn(
                  "flex w-full items-center justify-between rounded-md px-1.5 py-1 text-body transition-colors",
                  kind === name ? "bg-primary/12 text-primary" : "text-muted-foreground hover:bg-muted"
                )}
              >
                <span>{kindLabel(name)}</span>
                <span className="font-mono text-meta">{stats?.kinds?.[name]}</span>
              </button>
            ))}
          </div>
        </div>

        <div>
          <p className="mb-1 text-meta text-muted-foreground">扩展跳数</p>
          <div className="flex gap-1">
            {[1, 2].map((depth) => (
              <button
                key={depth}
                type="button"
                onClick={() => setHops(depth)}
                className={cn(
                  "flex-1 rounded-md px-1.5 py-1 font-mono text-meta transition-colors",
                  hops === depth ? "bg-primary/12 text-primary" : "text-muted-foreground hover:bg-muted"
                )}
              >
                ≤{depth}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-1 border-t border-border pt-2">
          <p className="mb-1 text-meta text-muted-foreground">实体（{entities.length}）</p>
          <div className="space-y-0.5">
            {entities.map((entity) => (
              <button
                key={entity.entity_id}
                type="button"
                onClick={() => {
                  setAnchorId(entity.entity_id)
                  setSelectedId(entity.entity_id)
                }}
                className={cn(
                  "block w-full truncate rounded-md px-1.5 py-1 text-left text-body transition-colors",
                  anchorId === entity.entity_id
                    ? "bg-primary/12 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
                title={entity.name}
              >
                {entity.name}
              </button>
            ))}
          </div>
        </div>
      </aside>

      <section className="relative flex min-h-0 min-w-0 flex-1 flex-col bg-background">
        <div className="flex h-9 shrink-0 items-center justify-between gap-2 border-b border-border px-3">
          <span className="font-mono text-meta text-muted-foreground">
            {subgraph ? `${subgraph.nodes.length} 节点 · ${subgraph.edges.length} 边` : "—"}
          </span>
          <div className="flex items-center gap-2">
            {stats ? (
              <span className="font-mono text-meta text-muted-foreground">
                {stats.entities} 实体 · {stats.relations} 关系 · {stats.links} 连线
              </span>
            ) : null}
            <Button
              variant="ghost"
              size="icon-xs"
              title="重新加载子图"
              onClick={() => anchorId && void loadSubgraph(anchorId, hops)}
              disabled={!anchorId || loadingGraph}
            >
              <RefreshCw className={cn(loadingGraph && "animate-spin")} />
            </Button>
          </div>
        </div>

        <div className="relative min-h-0 flex-1 p-2">
          {empty ? (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <p className="text-sm font-medium">图谱为空</p>
              <p className="mt-1.5 max-w-md text-body text-muted-foreground">
                图谱由 LLM 从切片中抽取实体与关系，需要离线构建一次：
              </p>
              <code className="mt-2 rounded-md bg-muted px-2.5 py-1 font-mono text-xs">
                python -m src.graph build
              </code>
              <p className="mt-2 max-w-md text-meta text-muted-foreground">
                构建耗时与文档量成正比（一次全量约数十分钟），完成后回到本页刷新即可。
              </p>
            </div>
          ) : loadingGraph && !subgraph ? (
            <div className="flex h-full items-center justify-center gap-2 text-body text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" />
              加载子图…
            </div>
          ) : subgraph && subgraph.nodes.length > 0 ? (
            <GraphCanvas
              nodes={subgraph.nodes}
              edges={subgraph.edges}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onExpand={(entityId) => {
                setAnchorId(entityId)
                setSelectedId(entityId)
              }}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-body text-muted-foreground">
              该实体暂无关联子图
            </div>
          )}

          {error ? (
            <p className="absolute inset-x-2 bottom-2 rounded-md border border-destructive/30 bg-background px-2.5 py-1.5 text-body text-destructive">
              {error}
            </p>
          ) : null}
        </div>
      </section>

      <EntityDetail
        detail={selectedId ? detail : null}
        loading={loadingDetail}
        onSelect={setSelectedId}
        onExpand={(entityId) => {
          setAnchorId(entityId)
          setSelectedId(entityId)
        }}
      />
    </div>
  )
}
