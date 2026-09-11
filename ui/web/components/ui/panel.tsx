import { type ReactNode } from "react"

import { cn } from "@/lib/utils"

/** 侧栏面板容器：固定宽度、独立滚动、顶部标题栏。用于检索检视 / 实体详情等。 */
export function Panel({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <aside className={cn("flex min-h-0 flex-col border-l border-border bg-card", className)}>{children}</aside>
  )
}

export function PanelHeader({
  title,
  actions,
  className,
}: {
  title: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex h-9 shrink-0 items-center justify-between gap-2 border-b border-border px-3",
        className
      )}
    >
      <span className="text-body font-medium">{title}</span>
      {actions ? <div className="flex items-center gap-1">{actions}</div> : null}
    </div>
  )
}

export function PanelSection({
  label,
  action,
  children,
  className,
}: {
  label: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={cn("space-y-1.5", className)}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-meta text-muted-foreground">{label}</span>
        {action}
      </div>
      {children}
    </section>
  )
}

/** 面板滚动区。 */
export function PanelBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("scroll-thin min-h-0 flex-1 overflow-y-auto p-3", className)}>{children}</div>
}
