"use client"

import { useMemo } from "react"

import type { GraphLink, GraphNode } from "@/lib/api"

const WIDTH = 820
const HEIGHT = 620

/** 类型 → 颜色只取设计系统里已有的语义色，不引入额外色板。 */
const KIND_COLOR: Record<string, string> = {
  concept: "var(--info)",
  method: "var(--primary)",
  metric: "var(--success)",
  product: "var(--warning)",
  org: "var(--warning)",
  person: "var(--warning)",
  other: "var(--muted-foreground)",
}

const KIND_LABEL: Record<string, string> = {
  concept: "概念",
  product: "产品",
  metric: "指标",
  method: "方法",
  person: "人物",
  org: "组织",
  other: "其他",
}

export function kindColor(kind: string): string {
  return KIND_COLOR[kind] ?? KIND_COLOR.other
}

export function kindLabel(kind: string): string {
  return KIND_LABEL[kind] ?? kind
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max)}…` : text
}

/**
 * 确定性径向布局：锚点居中，hop=1/2 的实体按跳数分环均布。
 *
 * 说明：原方案建议用 d3-force，但项目未引入该依赖；力导向的节点位置每次渲染都会漂移，
 * 对"点开一个实体看它的两跳邻居"这种场景反而不如固定布局稳定，故改为无依赖的环状布局。
 */
function useLayout(nodes: GraphNode[]) {
  return useMemo(() => {
    const cx = WIDTH / 2
    const cy = HEIGHT / 2
    const ringRadius = [0, Math.min(WIDTH, HEIGHT) * 0.29, Math.min(WIDTH, HEIGHT) * 0.45]
    const positions = new Map<string, { x: number; y: number }>()

    const anchors = nodes.filter((node) => node.hop === 0)
    anchors.forEach((node, index) => {
      if (anchors.length === 1) {
        positions.set(node.entity_id, { x: cx, y: cy })
        return
      }
      const angle = (2 * Math.PI * index) / anchors.length
      positions.set(node.entity_id, { x: cx + 46 * Math.cos(angle), y: cy + 46 * Math.sin(angle) })
    })

    for (const hop of [1, 2]) {
      const ring = nodes.filter((node) => node.hop === hop)
      const radius = ringRadius[Math.min(hop, ringRadius.length - 1)]
      ring.forEach((node, index) => {
        const angle = (2 * Math.PI * index) / Math.max(ring.length, 1) - Math.PI / 2
        positions.set(node.entity_id, {
          x: cx + radius * Math.cos(angle),
          y: cy + radius * Math.sin(angle),
        })
      })
    }

    const rest = nodes.filter((node) => !positions.has(node.entity_id))
    rest.forEach((node, index) => {
      const angle = (2 * Math.PI * index) / Math.max(rest.length, 1)
      positions.set(node.entity_id, {
        x: cx + ringRadius[2] * Math.cos(angle),
        y: cy + ringRadius[2] * Math.sin(angle),
      })
    })

    return positions
  }, [nodes])
}

export function GraphCanvas({
  nodes,
  edges,
  selectedId,
  onSelect,
  onExpand,
}: {
  nodes: GraphNode[]
  edges: GraphLink[]
  selectedId: string | null
  onSelect: (entityId: string) => void
  onExpand: (entityId: string) => void
}) {
  const positions = useLayout(nodes)

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      width="100%"
      height="100%"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      className="select-none"
    >
      <g>
        {edges.map((edge, index) => {
          const from = positions.get(edge.src)
          const to = positions.get(edge.dst)
          if (!from || !to) return null
          const touchesSelection = selectedId === edge.src || selectedId === edge.dst
          return (
            <line
              key={`${edge.src}-${edge.dst}-${index}`}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              stroke={touchesSelection ? "var(--primary)" : "var(--border-strong)"}
              strokeWidth={Math.min(1 + edge.weight * 0.5, 3)}
              opacity={touchesSelection ? 0.9 : 0.5}
            />
          )
        })}
      </g>

      <g>
        {nodes.map((node) => {
          const point = positions.get(node.entity_id)
          if (!point) return null
          const radius = Math.min(7 + node.mentions * 0.6, 22)
          const selected = node.entity_id === selectedId
          const anchor = node.hop === 0
          return (
            <g
              key={node.entity_id}
              className="cursor-pointer"
              onClick={() => onSelect(node.entity_id)}
              onDoubleClick={() => onExpand(node.entity_id)}
            >
              <title>{`${node.name}（${kindLabel(node.kind)}）· 被提及 ${node.mentions} 次\n单击查看详情，双击以此为中心`}</title>
              {anchor && !selected ? (
                <circle cx={point.x} cy={point.y} r={radius + 5} fill="none" stroke={kindColor(node.kind)} strokeWidth={1} opacity={0.5} />
              ) : null}
              <circle
                cx={point.x}
                cy={point.y}
                r={radius}
                fill={selected ? "var(--primary)" : kindColor(node.kind)}
                stroke={selected ? "var(--background)" : "var(--background)"}
                strokeWidth={1.5}
                opacity={selected || anchor ? 1 : 0.85}
              />
              <text
                x={point.x}
                y={point.y + radius + 11}
                textAnchor="middle"
                fontSize={11}
                fill={selected ? "var(--primary)" : "var(--muted-foreground)"}
                className="pointer-events-none"
              >
                {truncate(node.name, 14)}
              </text>
            </g>
          )
        })}
      </g>
    </svg>
  )
}
