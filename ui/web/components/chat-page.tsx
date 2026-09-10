"use client"

import { useState, useRef, useEffect } from "react"
import { clearConversation, getConversationMessages, getConversations, queryDoc, type ConversationSummary, type Figure, type Source } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Bot, MessageCircle, Search, Send, SlidersHorizontal, FileText, Loader2, AlertCircle, Trash2, Plus, MessageSquare, Files } from "lucide-react"
import { Input } from "@/components/ui/input"

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  sources?: Source[]
  figures?: Figure[]
  features?: string[]
  latency_ms?: number
  timestamp: Date
}

const CONVERSATION_KEY = "nexus-rag-conversation-id"
const LAST_FEATURES_KEY = "nexus-rag-last-features"

const FEATURE_OPTIONS: { key: string; label: string; desc: string }[] = [
  { key: "routing", label: "路由", desc: "先定位到相关文档，缩小检索范围" },
  { key: "keywords", label: "关键词", desc: "精确匹配专有名词、代号、数字" },
  { key: "decompose", label: "分解", desc: "将复杂问题拆分为子问题分别检索" },
  { key: "stepback", label: "退步", desc: "先将细节问题转化为概念问题再检索" },
  { key: "hyde", label: "假想文档", desc: "生成假想答案段落辅助语义检索" },
  { key: "rerank", label: "重排", desc: "检索末端对候选结果精细排序（稍慢）" },
  { key: "graph", label: "图谱", desc: "图谱多跳检索，串联分散在文档各处的关系线索" },
]

const DEFAULT_FEATURES = ["routing", "keywords", "decompose", "stepback", "hyde"]

function getConversationId() {
  const existing = window.localStorage.getItem(CONVERSATION_KEY)
  if (existing) return existing
  const id = crypto.randomUUID()
  window.localStorage.setItem(CONVERSATION_KEY, id)
  return id
}

function toMessage(message: { id: string; role: "user" | "assistant"; content: string; sources: Source[]; created_at: string }): Message {
  return { ...message, timestamp: new Date(message.created_at) }
}

function relTime(iso: string) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return "just now"
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

function featureLabels(keys: string[] | undefined) {
  if (!keys || keys.length === 0) return null
  return keys.map((k) => FEATURE_OPTIONS.find((o) => o.key === k)?.label ?? k).join(", ")
}

function getLastFeatures(): string[] | null {
  try {
    const raw = window.localStorage.getItem(LAST_FEATURES_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as string[]) : null
  } catch {
    return null
  }
}

function messageMeta(message: Message) {
  const features = message.features ?? getLastFeatures() ?? undefined
  return [
    featureLabels(features) ? `features: ${featureLabels(features)}` : null,
    message.latency_ms != null ? `${(message.latency_ms / 1000).toFixed(1)}s` : null,
  ].filter(Boolean) as string[]
}

export function ChatPage({ onGoToDocuments }: { onGoToDocuments?: () => void }) {
  const conversationIdRef = useRef<string | null>(null)
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null)
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [filter, setFilter] = useState("")
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showFeatures, setShowFeatures] = useState(false)
  const [checked, setChecked] = useState<Record<string, boolean>>(
    Object.fromEntries(FEATURE_OPTIONS.map((o) => [o.key, DEFAULT_FEATURES.includes(o.key)]))
  )
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    let cancelled = false
    const conversationId = getConversationId()
    conversationIdRef.current = conversationId
    Promise.all([getConversations(), getConversationMessages(conversationId)]).then(([items, history]) => {
      if (cancelled) return
      setSelectedConversationId(conversationId)
      setConversations(items)
      setMessages(history.map(toMessage))
    }).catch((e) => {
      if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load conversation")
    })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  // Auto-resize textarea
  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = Math.min(el.scrollHeight, 200) + "px"
  }, [input])

  const visibleConversations = filter
    ? conversations.filter((c) => c.title.toLowerCase().includes(filter.toLowerCase()))
    : conversations

  async function selectConversation(id: string) {
    if (loading || id === conversationIdRef.current) return
    setError(null)
    try {
      const history = await getConversationMessages(id)
      conversationIdRef.current = id
      setSelectedConversationId(id)
      window.localStorage.setItem(CONVERSATION_KEY, id)
      setMessages(history.map(toMessage))
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load conversation")
    }
  }

  function newConversation() {
    if (loading) return
    const id = crypto.randomUUID()
    conversationIdRef.current = id
    setSelectedConversationId(id)
    window.localStorage.setItem(CONVERSATION_KEY, id)
    setMessages([])
    setError(null)
  }

  async function refreshConversations() {
    setConversations(await getConversations())
  }

  function computeFeatures() {
    const selected = FEATURE_OPTIONS.filter((o) => checked[o.key]).map((o) => o.key)
    const isDefault =
      selected.length === DEFAULT_FEATURES.length && DEFAULT_FEATURES.every((f) => selected.includes(f))
    // 默认组合或全部取消 = 不传（后端默认）
    if (isDefault || selected.length === 0) return undefined
    return selected
  }

  async function handleSend() {
    const question = input.trim()
    if (!question || loading) return

    const conversationId = conversationIdRef.current
    if (!conversationId) return

    const userMsg: Message = {
      id: Date.now().toString(),
      role: "user",
      content: question,
      timestamp: new Date(),
    }
    setMessages((prev) => [...prev, userMsg])
    setInput("")
    setLoading(true)
    setError(null)

    try {
      const featuresSent = computeFeatures()
      // ponytail: 历史记录无 per-message features，用最后一次发送的值近似展示
      window.localStorage.setItem(LAST_FEATURES_KEY, JSON.stringify(featuresSent))
      const result = await queryDoc(question, conversationId, 5, undefined, featuresSent)

      const assistantMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: result.answer,
        sources: result.sources || [],
        figures: result.figures || [],
        features: featuresSent,
        latency_ms: result.latency_ms,
        timestamp: new Date(),
      }
      setMessages((prev) => [...prev, assistantMsg])
      await refreshConversations()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Query failed")
    } finally {
      setLoading(false)
    }
  }

  async function handleClear() {
    const conversationId = conversationIdRef.current
    if (!conversationId || loading) return
    try {
      await clearConversation(conversationId)
      setMessages([])
      setConversations((items) => items.filter((item) => item.id !== conversationId))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to clear conversation")
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex h-full min-h-0 gap-0 overflow-hidden rounded-lg border bg-card">
      <aside className="hidden w-52 shrink-0 border-r bg-muted/30 md:flex md:flex-col">
        <div className="flex items-center justify-between border-b p-3">
          <span className="text-sm font-medium">History</span>
          <Button variant="ghost" size="icon" onClick={newConversation} disabled={loading} title="New conversation">
            <Plus className="size-4" />
          </Button>
        </div>
        <div className="p-2">
          <Input
            value={filter}
            placeholder="Search conversations"
            onChange={(e) => setFilter(e.target.value)}
            className="mb-2 h-8 bg-background"
          />
        </div>
        <div className="flex-1 space-y-1 overflow-y-auto p-2 pt-0">
          {visibleConversations.map((conversation) => (
            <button
              key={conversation.id}
              onClick={() => selectConversation(conversation.id)}
              className={`w-full rounded-md px-3 py-2 text-left text-sm transition-all hover:bg-muted ${conversation.id === selectedConversationId ? "bg-muted font-medium shadow-[inset_3px_0_0_var(--primary)]" : ""}`}
            >
              <div className="flex items-start gap-2">
                <MessageSquare className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <span className="line-clamp-2 break-words">{conversation.title}</span>
                  <span className="mt-0.5 block font-mono text-[11px] text-muted-foreground">
                    {conversation.message_count} messages · {relTime(conversation.updated_at)}
                  </span>
                </div>
              </div>
            </button>
          ))}
          {conversations.length === 0 && (
            <p className="px-2 py-3 text-xs text-muted-foreground">No saved conversations yet.</p>
          )}
        </div>
      </aside>

      <section className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6">
          <div className="mx-auto flex min-h-full max-w-4xl flex-col space-y-6">
            {messages.length === 0 && !loading && !error && (
              <div className="flex flex-1 flex-col items-center justify-center py-16 text-center">
                <div className="mb-4 flex size-12 items-center justify-center rounded-2xl bg-primary/10">
                  <MessageCircle className="size-5 text-primary" />
                </div>
                <h2 className="text-xl font-semibold tracking-tight">Ask anything about your documents</h2>
                <p className="mt-2 max-w-md text-sm text-muted-foreground">
                  Answers are grounded in your knowledge base and cite their sources.
                </p>
                <Button className="mt-6" onClick={() => onGoToDocuments?.()}>
                  <Files /> Open Documents
                </Button>
              </div>
            )}

            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}

            {loading && (
              <div className="animate-fade-up flex items-start gap-3">
                <Avatar className="size-8 mt-1 animate-pulse-soft">
                  <AvatarFallback className="bg-primary/10">
                    <Bot className="size-4 text-primary" />
                  </AvatarFallback>
                </Avatar>
                <div className="flex-1 space-y-2 pt-1">
                  <p className="text-xs text-muted-foreground">Searching your knowledge base…</p>
                  <Skeleton className="h-4 w-4/5" />
                  <Skeleton className="h-4 w-3/5" />
                </div>
              </div>
            )}

            {error && (
              <div className="flex items-start gap-3">
                <Avatar className="size-8 mt-1">
                  <AvatarFallback className="bg-destructive/10">
                    <AlertCircle className="size-4 text-destructive" />
                  </AvatarFallback>
                </Avatar>
                <p className="pt-1 text-sm text-destructive">{error}</p>
              </div>
            )}

            <div ref={bottomRef} />
          </div>
        </div>

        <div className="shrink-0 border-t bg-card p-4">
          <div className="mx-auto flex max-w-4xl items-center justify-between pb-2">
            <div className="relative">
              <Button variant="ghost" size="sm" onClick={() => setShowFeatures((v) => !v)} aria-expanded={showFeatures} title="检索特性" className="transition-colors hover:bg-muted/80">
                <SlidersHorizontal className="size-3.5" /> 检索特性
              </Button>
              {showFeatures && (
                <div className="absolute bottom-full left-0 z-50 mb-2 w-80 rounded-xl border bg-popover p-3 shadow-[0_12px_40px_rgba(0,0,0,0.5)]">
                  <p className="mb-2 text-xs font-medium text-muted-foreground">检索特性</p>
                  <div className="space-y-0.5">
                    {FEATURE_OPTIONS.map((o) => (
                      <label key={o.key} className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 transition-colors hover:bg-muted" title={o.key}>
                        <input
                          type="checkbox"
                          checked={checked[o.key]}
                          onChange={(e) => setChecked((prev) => ({ ...prev, [o.key]: e.target.checked }))}
                          className="size-3.5 rounded border-muted-foreground/40 accent-primary"
                        />
                        <span className="w-16 text-xs font-medium">{o.label}</span>
                        <span className="text-[11px] leading-tight text-muted-foreground">{o.desc}</span>
                      </label>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <Button variant="ghost" size="sm" onClick={handleClear} disabled={loading || messages.length === 0} title="Clear conversation">
              <Trash2 className="mr-1 size-4" />
              Clear
            </Button>
          </div>
          <div className="mx-auto flex max-w-4xl gap-2">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question… (Enter to send, Shift+Enter for a new line)"
              className="flex-1 resize-none rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 min-h-[44px] max-h-[200px]"
              rows={1}
              disabled={loading}
            />
            <Button onClick={handleSend} disabled={loading || !input.trim()} size="lg" className="transition-transform hover:scale-[1.03] active:scale-[0.97]">
              {loading ? <Loader2 className="size-5 animate-spin" /> : <Send className="size-5" />}
            </Button>
          </div>
        </div>
      </section>
    </div>
  )
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user"

  if (isUser) {
    return (
      <div className="flex animate-fade-up justify-end">
        <div className="max-w-[80%] rounded-xl bg-primary px-4 py-2.5 text-sm whitespace-pre-wrap break-words text-primary-foreground">
          {message.content}
        </div>
      </div>
    )
  }

  return (
    <div className="flex animate-fade-up items-start gap-3">
      <Avatar className="size-8 shrink-0">
        <AvatarFallback className="bg-primary/10">
          <Bot className="size-4 text-primary" />
        </AvatarFallback>
      </Avatar>
      <div className="min-w-0 flex-1 space-y-2 rounded-xl bg-muted/30 px-4 py-3">
        <p className="whitespace-pre-wrap break-words text-[15px] leading-relaxed">{message.content}</p>

        {message.figures && message.figures.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {message.figures.map((fig, i) => (
              <figure key={i} className="max-w-[240px] rounded-md border bg-background p-1">
                <img
                  src={fig.data_uri}
                  alt={`Image from page ${fig.page}`}
                  width={Math.min(fig.width, 240)}
                  height={Math.round((fig.height / fig.width) * Math.min(fig.width, 240))}
                  className="rounded-sm"
                />
                <figcaption className="mt-0.5 font-mono text-[11px] text-muted-foreground">page {fig.page}</figcaption>
              </figure>
            ))}
          </div>
        )}

        {message.sources && message.sources.length > 0 && (
          <div>
            <div className="mb-1.5 flex items-center gap-1 text-xs text-muted-foreground">
              <Search className="size-3" />
              <span>{message.sources.length} sources</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {message.sources.map((source, i) => (
                <SourceChip key={i} source={source} />
              ))}
            </div>
          </div>
        )}

        {messageMeta(message).length > 0 && (
          <p className="font-mono text-[11px] text-muted-foreground">{messageMeta(message).join(" · ")}</p>
        )}
      </div>
    </div>
  )
}

function SourceChip({ source }: { source: Source }) {
  return (
    <div className="group relative">
      <div className="flex cursor-default items-center gap-1.5 rounded-md bg-muted/60 px-2.5 py-1 text-xs transition-colors group-hover:bg-accent">
        <FileText className="size-3 shrink-0 text-muted-foreground" />
        <span className="max-w-40 truncate font-medium">{source.doc_name}</span>
        {source.page != null && <span className="font-mono text-[11px] text-muted-foreground">p.{source.page}</span>}
        {source.chunk_index != null && (
          <span className="font-mono text-[11px] text-muted-foreground">#{source.chunk_index}</span>
        )}
        {source.score != null && (
          <span className="font-mono text-[11px] text-muted-foreground">{source.score.toFixed(2)}</span>
        )}
      </div>
      <div className="pointer-events-none absolute bottom-full left-0 z-10 mb-1.5 hidden w-72 animate-fade-in rounded-lg border bg-popover p-3 text-xs shadow-md group-hover:block">
        <p className="mb-1 font-medium">{source.doc_name}</p>
        <p className="line-clamp-6 whitespace-pre-wrap text-muted-foreground">{source.text}</p>
      </div>
    </div>
  )
}
