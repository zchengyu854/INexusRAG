"use client"

import { useState, useRef, useEffect } from "react"
import { clearConversation, getConversationMessages, getConversations, queryDoc, type ConversationSummary, type Source } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { Send, Bot, User, FileText, Search, Loader2, AlertCircle, Trash2, Plus, MessageSquare } from "lucide-react"

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  sources?: Source[]
  features?: string[]
  timestamp: Date
}

const CONVERSATION_KEY = "nexus-rag-conversation-id"

const FEATURE_OPTIONS: { key: string; label: string; desc: string }[] = [
  { key: "routing", label: "路由", desc: "先选目标文档再检索，缩小搜索范围" },
  { key: "keywords", label: "关键词", desc: "精确词匹配（专有名词、代号、数字）" },
  { key: "decompose", label: "分解", desc: "复杂问题拆成子问题分别检索" },
  { key: "stepback", label: "退步", desc: "细节问题先退成概念问题再检索" },
  { key: "hyde", label: "假想文档", desc: "生成假想答案段落辅助语义检索" },
  { key: "rerank", label: "重排", desc: "检索末端对候选精细排序（稍慢）" },
]

const LAST_FEATURES_KEY = "nexus-rag-last-features"

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

export function ChatPage() {
  const conversationIdRef = useRef<string | null>(null)
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null)
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState(0)
  const [showFeatures, setShowFeatures] = useState(false)
  const [checked, setChecked] = useState<Record<string, boolean>>(
    Object.fromEntries([...DEFAULT_FEATURES, "rerank"].map((k) => [k, k !== "rerank"]))
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

    if (!conversationIdRef.current) return
    const conversationId = conversationIdRef.current

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
    setProgress(5)

    // Simulate progress
    const progressInterval = setInterval(() => {
      setProgress((p) => Math.min(p + 10, 90))
    }, 300)

    try {
      const featuresSent = computeFeatures()
      // ponytail: 历史记录无 per-message features，用最后一次发送的值近似展示
      window.localStorage.setItem(LAST_FEATURES_KEY, JSON.stringify(featuresSent))
      const result = await queryDoc(question, conversationId, 5, undefined, featuresSent)
      clearInterval(progressInterval)
      setProgress(100)

      const assistantMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: result.answer,
        sources: result.sources || [],
        features: featuresSent,
        timestamp: new Date(),
      }
      setMessages((prev) => [...prev, assistantMsg])
      await refreshConversations()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Query failed")
    } finally {
      clearInterval(progressInterval)
      setLoading(false)
      setProgress(0)
    }
  }

  async function handleClear() {
    if (!conversationIdRef.current || loading) return
    const conversationId = conversationIdRef.current
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
      <aside className="hidden w-64 shrink-0 border-r bg-muted/20 md:flex md:flex-col">
        <div className="flex items-center justify-between border-b p-3">
          <span className="text-sm font-medium">History</span>
          <Button variant="ghost" size="icon" onClick={newConversation} disabled={loading} title="New conversation">
            <Plus className="size-4" />
          </Button>
        </div>
        <div className="flex-1 space-y-1 overflow-y-auto p-2">
          {conversations.map((conversation) => (
            <button
              key={conversation.id}
              onClick={() => selectConversation(conversation.id)}
              className={`w-full rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-muted ${conversation.id === selectedConversationId ? "bg-muted font-medium" : ""}`}
            >
              <div className="flex items-start gap-2">
                <MessageSquare className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <span className="line-clamp-2 break-words">{conversation.title}</span>
              </div>
              <span className="ml-6 text-xs text-muted-foreground">{conversation.message_count} messages</span>
            </button>
          ))}
          {conversations.length === 0 && <p className="p-2 text-xs text-muted-foreground">No saved conversations</p>}
        </div>
      </aside>

      <section className="flex min-h-0 min-w-0 flex-1 flex-col">
        {/* Messages */}
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6">
          <div className="mx-auto max-w-3xl space-y-6">
        {messages.length === 0 && !loading && !error && (
          <div className="flex h-[calc(100vh-24rem)] flex-col items-center justify-center text-center">
            <div className="mb-4 flex size-16 items-center justify-center rounded-full bg-primary/10">
              <Bot className="size-8 text-primary" />
            </div>
            <h2 className="text-lg font-semibold">Ask anything about your documents</h2>
            <p className="mt-2 max-w-md text-muted-foreground">Upload documents first, then ask questions to get grounded answers from your knowledge base.</p>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {loading && (
          <div className="space-y-2">
            <div className="flex items-start gap-3">
              <Avatar className="size-8 mt-1">
                <AvatarFallback className="bg-primary/10">
                  <Bot className="size-4 text-primary" />
                </AvatarFallback>
              </Avatar>
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-4 w-1/2" />
                <Progress value={progress} className="h-1" />
              </div>
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
            <Card className="border-destructive/50">
              <CardContent className="p-3 text-sm text-destructive">
                {error}
              </CardContent>
            </Card>
          </div>
        )}

        <div ref={bottomRef} />
          </div>
        </div>

        {/* Input */}
      <div className="shrink-0 border-t bg-card p-4">
        <div className="mx-auto flex max-w-3xl items-center justify-between pb-2">
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setShowFeatures((v) => !v)} aria-expanded={showFeatures} title="检索特性">
              特性
            </Button>
            <span className="text-xs text-muted-foreground">Saved to database</span>
          </div>
          <Button variant="ghost" size="sm" onClick={handleClear} disabled={loading || messages.length === 0} title="Clear conversation">
            <Trash2 className="size-4 mr-1" />
            Clear
          </Button>
        </div>
        {showFeatures && (
          <div className="mx-auto mb-2 w-full max-w-3xl space-y-0.5 rounded-md border bg-muted/30 p-2">
            <div className="flex items-center gap-2 px-1 pb-1">
              <span className="text-xs font-medium">检索特性</span>
              <span className="text-[11px] text-muted-foreground">勾选后按当前组合检索，全部不选或默认组合则使用后端默认</span>
            </div>
            {FEATURE_OPTIONS.map((o) => (
              <label key={o.key} className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 hover:bg-muted" title={o.key}>
                <input
                  type="checkbox"
                  checked={checked[o.key]}
                  onChange={(e) => setChecked((prev) => ({ ...prev, [o.key]: e.target.checked }))}
                />
                <span className="text-xs font-medium">{o.label}</span>
                <span className="text-[11px] text-muted-foreground">{o.desc}</span>
              </label>
            ))}
          </div>
        )}
        <div className="mx-auto flex max-w-3xl gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question... (Enter to send, Shift+Enter for new line)"
            className="flex-1 resize-none rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 min-h-[44px] max-h-[200px]"
            rows={1}
            disabled={loading}
          />
          <Button onClick={handleSend} disabled={loading || !input.trim()} size="lg">
            {loading ? <Loader2 className="size-5 animate-spin" /> : <Send className="size-5" />}
          </Button>
        </div>
      </div>
      </section>
    </div>
  )
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

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user"
  const shownFeatures = message.features ?? getLastFeatures()

  return (
    <div className={`flex items-start gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
      <Avatar className="w-8 h-8">
        <AvatarFallback className={isUser ? "bg-primary text-primary-foreground" : "bg-primary/10"}>
          {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4 text-primary" />}
        </AvatarFallback>
      </Avatar>

      <div className={`max-w-[80%] space-y-2 ${isUser ? "items-end" : "items-start"} flex flex-col`}>
        <div className={`px-4 py-2 rounded-lg ${
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-foreground"
        }`}>
          <p className="text-sm whitespace-pre-wrap break-words">{message.content}</p>
        </div>

        {message.sources && message.sources.length > 0 && (
          <div className="w-full space-y-1">
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <Search className="w-3 h-3" />
              <span>{message.sources.length} sources</span>
            </div>
            {message.sources.map((source, i) => (
              <SourceChip key={i} source={source} />
            ))}
          </div>
        )}

        {!isUser && (
          <p className="text-[11px] text-muted-foreground">
            本次检索特性: {shownFeatures ? shownFeatures.join("·") : "默认"}
          </p>
        )}
      </div>
    </div>
  )
}

function SourceChip({ source }: { source: Source }) {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-muted/50 text-xs hover:bg-muted transition-colors cursor-pointer">
      <FileText className="w-3 h-3 text-muted-foreground shrink-0" />
      <span className="font-medium truncate">{source.doc_name}</span>
      {source.chunk_index != null && (
        <span className="text-muted-foreground shrink-0">#{source.chunk_index}</span>
      )}
      {source.page != null && (
        <span className="text-muted-foreground shrink-0">p.{source.page}</span>
      )}
      {source.score != null && (
        <span className="ml-auto text-muted-foreground shrink-0">
          {source.score.toFixed(2)}
        </span>
      )}
    </div>
  )
}
