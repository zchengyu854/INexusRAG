"use client"

import { useState } from "react"
import { MessageSquare, Plus } from "lucide-react"

import { Button } from "@/components/ui/button"
import type { ConversationSummary } from "@/lib/api"
import { cn } from "@/lib/utils"

function relativeTime(iso: string): string {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000
  if (seconds < 60) return "刚刚"
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`
  return `${Math.floor(seconds / 86400)} 天前`
}

export function ConversationList({
  conversations,
  activeId,
  onSelect,
  onNew,
  className,
}: {
  conversations: ConversationSummary[]
  activeId: string | null
  onSelect: (id: string) => void
  onNew: () => void
  className?: string
}) {
  const [filter, setFilter] = useState("")
  const keyword = filter.trim().toLowerCase()
  const visible = keyword
    ? conversations.filter((conversation) => conversation.title.toLowerCase().includes(keyword))
    : conversations

  return (
    <aside className={cn("flex min-h-0 w-[190px] shrink-0 flex-col border-r border-border", className)}>
      <div className="flex items-center gap-1.5 p-2">
        <input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="搜索会话"
          className="h-7 min-w-0 flex-1 rounded-md border border-border bg-background px-2 text-body outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
        />
        <Button variant="ghost" size="icon-sm" onClick={onNew} title="新建会话">
          <Plus />
        </Button>
      </div>

      <div className="scroll-thin min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 pb-2">
        {visible.length === 0 ? (
          <p className="px-2 py-2 text-meta text-muted-foreground">
            {conversations.length === 0 ? "还没有会话" : "没有匹配的会话"}
          </p>
        ) : (
          visible.map((conversation) => {
            const active = conversation.id === activeId
            return (
              <button
                key={conversation.id}
                type="button"
                onClick={() => onSelect(conversation.id)}
                className={cn(
                  "w-full rounded-md px-2 py-1.5 text-left transition-colors",
                  active ? "bg-primary/12 text-primary" : "hover:bg-muted"
                )}
              >
                <span className="flex items-start gap-1.5">
                  <MessageSquare className="mt-0.5 size-3.5 shrink-0 opacity-60" />
                  <span className="min-w-0 flex-1">
                    <span className="line-clamp-2 break-words text-body">{conversation.title}</span>
                    <span className="mt-0.5 block font-mono text-meta text-muted-foreground">
                      {conversation.message_count} 条 · {relativeTime(conversation.updated_at)}
                    </span>
                  </span>
                </span>
              </button>
            )
          })
        )}
      </div>
    </aside>
  )
}
