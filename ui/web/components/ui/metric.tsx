import { type ReactNode } from "react"

import { cn } from "@/lib/utils"

/** 指标卡：11px 标签 + 20px 数值，用于概览页与详情页统计行。 */
export function Metric({
  label,
  value,
  hint,
  className,
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  className?: string
}) {
  return (
    <div className={cn("rounded-md bg-secondary px-3 py-2.5", className)}>
      <div className="text-meta text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-xl font-medium tabular-nums">{value}</div>
      {hint ? <div className="mt-0.5 text-meta text-muted-foreground">{hint}</div> : null}
    </div>
  )
}

/** 键值行：系统健康、实体属性等紧凑信息。 */
export function KeyValueRow({
  label,
  children,
  mono = true,
  className,
}: {
  label: ReactNode
  children: ReactNode
  mono?: boolean
  className?: string
}) {
  return (
    <div className={cn("flex items-baseline justify-between gap-3 py-1 text-body", className)}>
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className={cn("min-w-0 truncate text-right", mono && "font-mono text-xs")}>{children}</span>
    </div>
  )
}

/** 横向条形：通道命中量等比例展示。 */
export function BarRow({
  label,
  value,
  max,
  display,
}: {
  label: string
  value: number
  max: number
  display?: string
}) {
  const width = max > 0 ? Math.max(2, Math.round((value / max) * 96)) : 0
  return (
    <div className="flex items-center gap-2 text-meta">
      <span className="w-14 shrink-0 text-muted-foreground">{label}</span>
      <span className="h-[5px] shrink-0 rounded-sm bg-primary" style={{ width }} />
      <span className="font-mono text-muted-foreground">{display ?? value}</span>
    </div>
  )
}
