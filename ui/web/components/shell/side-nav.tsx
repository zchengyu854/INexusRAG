"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useState } from "react"
import { Files, FlaskConical, Gauge, MessageCircle, Network, Settings } from "lucide-react"

import { getConversations, type ConversationSummary } from "@/lib/api"
import { cn } from "@/lib/utils"

const NAV_ITEMS = [
  { href: "/overview", label: "概览", icon: Gauge },
  { href: "/chat", label: "问答", icon: MessageCircle },
  { href: "/documents", label: "文档", icon: Files },
  { href: "/graph", label: "图谱", icon: Network },
  { href: "/eval", label: "评测", icon: FlaskConical },
  { href: "/settings", label: "设置", icon: Settings },
]

export function SideNav() {
  const pathname = usePathname()
  const [recent, setRecent] = useState<ConversationSummary[]>([])

  useEffect(() => {
    let cancelled = false
    getConversations()
      .then((rows) => {
        if (!cancelled) setRecent(rows.slice(0, 6))
      })
      .catch(() => {
        if (!cancelled) setRecent([])
      })
    return () => {
      cancelled = true
    }
  }, [pathname])

  return (
    <nav className="flex w-[184px] shrink-0 flex-col border-r border-border bg-card">
      <div className="flex items-center gap-2 px-3 py-3">
        <span className="size-4 rounded-[5px] bg-primary" />
        <span className="text-sm font-medium tracking-tight">NexusRAG</span>
      </div>

      <div className="px-3 pb-1.5 text-meta text-muted-foreground">工作区</div>
      <div className="flex flex-col gap-0.5 px-2">
        {NAV_ITEMS.map((item) => {
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`)
          const Icon = item.icon
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex h-7 items-center gap-2 rounded-md px-2 text-body transition-colors",
                active
                  ? "bg-primary/12 font-medium text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              <Icon className="size-3.5 shrink-0" />
              {item.label}
            </Link>
          )
        })}
      </div>

      <div className="mt-4 border-t border-border px-3 pb-1.5 pt-3 text-meta text-muted-foreground">
        最近会话
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {recent.length === 0 ? (
          <p className="px-2 py-1 text-meta text-muted-foreground">暂无会话</p>
        ) : (
          recent.map((conversation) => (
            <Link
              key={conversation.id}
              href={`/chat?conversation=${encodeURIComponent(conversation.id)}`}
              className={cn(
                "block rounded-md px-2 py-1.5 transition-colors hover:bg-muted",
                pathname === "/chat" ? "text-foreground" : "text-muted-foreground hover:text-foreground"
              )}
            >
              <span className="line-clamp-2 break-words text-body">{conversation.title}</span>
              <span className="mt-0.5 block font-mono text-meta text-muted-foreground">
                {conversation.message_count} 条
              </span>
            </Link>
          ))
        )}
      </div>
    </nav>
  )
}
