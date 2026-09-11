"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Files, MessageCircle } from "lucide-react"

import { Composer } from "@/components/chat/composer"
import { ConversationList } from "@/components/chat/conversation-list"
import {
  DEFAULT_FEATURES,
  initialFeatureState,
  selectedFeatures,
} from "@/components/chat/feature-toggle"
import { MessageThread, STAGES, type ChatMessageView } from "@/components/chat/message-thread"
import { RetrievalInspector } from "@/components/chat/retrieval-inspector"
import {
  filtersToRecord,
  type FilterRow,
  type RerankChoice,
  type RetrievalConfig,
} from "@/components/chat/retrieval-settings"
import { buttonVariants } from "@/components/ui/button"
import {
  clearConversation,
  getConversationMessages,
  getConversations,
  queryDoc,
  type ConversationSummary,
} from "@/lib/api"
import { cn } from "@/lib/utils"

const CONVERSATION_KEY = "nexus-rag-conversation-id"
const SETTINGS_KEY = "nexus-rag-retrieval-settings"
const STAGE_INTERVAL_MS = 1400
const RERANK_CHOICES: RerankChoice[] = ["auto", "rrf", "cross", "llm", "colbert"]

function defaultSettings(): RetrievalConfig {
  return {
    features: initialFeatureState(DEFAULT_FEATURES),
    topK: 5,
    rerankStrategy: "auto",
    filters: [],
  }
}

function readStoredSettings(): RetrievalConfig {
  const base = defaultSettings()
  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY)
    if (!raw) return base
    const parsed = JSON.parse(raw) as Record<string, unknown>
    return {
      features: Array.isArray(parsed.features)
        ? initialFeatureState(parsed.features as string[])
        : base.features,
      topK:
        typeof parsed.topK === "number" && parsed.topK >= 1 && parsed.topK <= 50
          ? parsed.topK
          : base.topK,
      rerankStrategy: RERANK_CHOICES.includes(parsed.rerankStrategy as RerankChoice)
        ? (parsed.rerankStrategy as RerankChoice)
        : base.rerankStrategy,
      filters: Array.isArray(parsed.filters)
        ? (parsed.filters as FilterRow[]).filter(
            (row) => row && typeof row.key === "string" && typeof row.value === "string"
          )
        : base.filters,
    }
  } catch {
    return base
  }
}

export function ChatPage() {
  const router = useRouter()
  const searchParams = useSearchParams()

  const [conversationId, setConversationId] = useState<string | null>(null)
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [messages, setMessages] = useState<ChatMessageView[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [stageIndex, setStageIndex] = useState(0)
  const [settings, setSettings] = useState<RetrievalConfig>(() => defaultSettings())
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [inspectingId, setInspectingId] = useState<string | null>(null)

  // 已从服务端加载过的会话，避免"自己刚发消息"时被回源请求覆盖掉乐观消息
  const loadedRef = useRef<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await getConversations())
    } catch {
      setConversations([])
    }
  }, [])

  useEffect(() => {
    // 只在挂载时解析一次 URL / 本地存储，后续切换由交互驱动。
    // 延后一拍执行，避免在 effect 体内同步 setState（仓库既有约定）。
    const timer = window.setTimeout(() => {
      setSettings(readStoredSettings())
      const fromUrl = searchParams.get("conversation")
      const stored = window.localStorage.getItem(CONVERSATION_KEY)
      const initial = fromUrl || stored
      if (initial) setConversationId(initial)
      void refreshConversations()
    }, 0)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!conversationId || loadedRef.current === conversationId) return
    loadedRef.current = conversationId
    let cancelled = false
    getConversationMessages(conversationId)
      .then((rows) => {
        if (cancelled) return
        setMessages(
          rows.map((row) => ({
            id: row.id,
            role: row.role,
            content: row.content,
            sources: row.sources,
          }))
        )
      })
      .catch(() => {
        if (!cancelled) setMessages([])
      })
    return () => {
      cancelled = true
    }
  }, [conversationId])

  useEffect(() => {
    if (!loading) return
    const timer = window.setInterval(() => {
      setStageIndex((index) => (index + 1) % STAGES.length)
    }, STAGE_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [loading])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" })
  }, [messages, loading])

  function persistSettings(next: RetrievalConfig) {
    setSettings(next)
    window.localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({ ...next, features: selectedFeatures(next.features) })
    )
  }

  function selectConversation(id: string) {
    setConversationId(id)
    window.localStorage.setItem(CONVERSATION_KEY, id)
    setError(null)
    setInspectorOpen(false)
    setInspectingId(null)
    router.replace(`/chat?conversation=${encodeURIComponent(id)}`, { scroll: false })
  }

  function startNewConversation() {
    const id = crypto.randomUUID()
    loadedRef.current = id
    setConversationId(id)
    window.localStorage.setItem(CONVERSATION_KEY, id)
    setMessages([])
    setError(null)
    setInspectorOpen(false)
    setInspectingId(null)
    router.replace("/chat", { scroll: false })
  }

  async function handleSend() {
    const question = input.trim()
    if (!question || loading) return

    let cid = conversationId
    if (!cid) {
      cid = crypto.randomUUID()
      loadedRef.current = cid
      setConversationId(cid)
      window.localStorage.setItem(CONVERSATION_KEY, cid)
      router.replace(`/chat?conversation=${encodeURIComponent(cid)}`, { scroll: false })
    }

    const activeFeatures = selectedFeatures(settings.features)
    setMessages((previous) => [
      ...previous,
      { id: `local-user-${Date.now()}`, role: "user", content: question },
    ])
    setInput("")
    setError(null)
    setStageIndex(0)
    setLoading(true)

    try {
      const result = await queryDoc(question, {
        conversationId: cid,
        topK: settings.topK,
        filters: filtersToRecord(settings.filters),
        features: activeFeatures,
        rerankStrategy: settings.rerankStrategy === "auto" ? null : settings.rerankStrategy,
        debug: true,
      })
      const assistantId = `local-assistant-${Date.now()}`
      setMessages((previous) => [
        ...previous,
        {
          id: assistantId,
          role: "assistant",
          content: result.answer,
          sources: result.sources,
          figures: result.figures,
          features: activeFeatures,
          latency_ms: result.latency_ms,
          trace: result.trace ?? null,
        },
      ])
      if (result.trace) {
        setInspectingId(assistantId)
      }
      void refreshConversations()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "问答失败，请稍后重试")
    } finally {
      setLoading(false)
    }
  }

  async function handleClear() {
    if (!conversationId) return
    try {
      await clearConversation(conversationId)
    } catch {
      // 清空失败不阻塞界面，下一次发送仍会写入服务端
    }
    setMessages([])
    setInspectorOpen(false)
    setInspectingId(null)
    void refreshConversations()
  }

  const inspectingMessage = messages.find((message) => message.id === inspectingId) ?? null

  return (
    <div className="flex h-full min-h-0">
      <ConversationList
        conversations={conversations}
        activeId={conversationId}
        onSelect={selectConversation}
        onNew={startNewConversation}
      />

      <section className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-4 py-4">
          {messages.length === 0 && !loading && !error ? (
            <div className="mx-auto flex h-full max-w-3xl flex-col items-center justify-center py-16 text-center">
              <span className="mb-3 flex size-10 items-center justify-center rounded-lg bg-primary/12">
                <MessageCircle className="size-4 text-primary" />
              </span>
              <h2 className="text-sm font-medium">向你的文档提问</h2>
              <p className="mt-1.5 max-w-sm text-body text-muted-foreground">
                回答基于知识库内容，并标注引用来源与页码。
              </p>
              <a href="/documents" className={cn(buttonVariants({ variant: "outline", size: "sm" }), "mt-4")}>
                <Files />
                管理文档
              </a>
            </div>
          ) : (
            <div className="mx-auto max-w-3xl">
              <MessageThread
                messages={messages}
                loading={loading}
                stage={STAGES[stageIndex]}
                error={error}
                onInspect={(id) => {
                  setInspectingId(id)
                  setInspectorOpen(true)
                }}
                inspectingId={inspectorOpen ? inspectingId : null}
              />
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        <Composer
          value={input}
          onChange={setInput}
          onSend={handleSend}
          onClear={handleClear}
          loading={loading}
          canClear={messages.length > 0}
          settings={settings}
          onSettingsChange={persistSettings}
        />
      </section>

      {inspectorOpen ? (
        <RetrievalInspector
          trace={inspectingMessage?.trace ?? null}
          sources={inspectingMessage?.sources ?? []}
          loading={loading}
          onClose={() => setInspectorOpen(false)}
        />
      ) : null}
    </div>
  )
}
