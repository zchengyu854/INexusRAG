/** 实体类型 → 颜色与中文标签。颜色取设计系统里已有的 CSS 变量，运行时通过 getComputedStyle 解析，避免打包时硬编码具体色值。 */

import type { GraphNode } from "@/lib/api"

export const KIND_LABEL: Record<string, string> = {
  concept: "概念",
  product: "产品",
  metric: "指标",
  method: "方法",
  person: "人物",
  org: "组织",
  other: "其他",
}

export const KIND_HEX: Record<string, string> = {
  concept: "#3b82f6",
  product: "#f59e0b",
  metric: "#10b981",
  method: "#ef4444",
  person: "#a855f7",
  org: "#06b6d4",
  other: "#6b7280",
}

/** 语义色变量形式，供 SVG / DOM 样式使用。 */
export const KIND_COLOR: Record<string, string> = {
  concept: "var(--info)",
  product: "var(--warning)",
  metric: "var(--success)",
  method: "var(--destructive)",
  person: "var(--primary)",
  org: "var(--accent-foreground)",
  other: "var(--muted-foreground)",
}

export function kindColor(kind: string): string {
  return KIND_COLOR[kind] ?? KIND_COLOR.other
}

export function kindLabel(kind: string): string {
  return KIND_LABEL[kind] ?? kind
}

export function kindHex(kind: string): string {
  return KIND_HEX[kind] ?? KIND_HEX.other
}

/** 与 SVG 画布保留同样半径规则：mentions 越多球越大，上限 1.4。 */
export function nodeRadius(node: Pick<GraphNode, "mentions" | "hop">, maxRadius = 0.45): number {
  const base = 0.18 + Math.min(node.mentions, 80) / 200
  const anchorBoost = node.hop === 0 ? 0.2 : 0
  return Math.min(base + anchorBoost, maxRadius)
}
