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
import { MessageThread, STAGE_LABELS, type ChatMessageView } from "@/components/chat/message-thread"
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
  queryDocStream,
  type AgentStep,
  type ConversationSummary,
  type QueryTrace,
} from "@/lib/api"
import { cn } from "@/lib/utils"

const CONVERSATION_KEY = "nexus-rag-conversation-id"
// v2：新增 rewrite 特性进默认集（基础装置）。旧 v1 存档的 features 数组里没有 rewrite，
// 直接沿用会让新默认失效，故升键让新默认生效一次。
const SETTINGS_KEY = "nexus-rag-retrieval-settings-v2"
const RERANK_CHOICES: RerankChoice[] = ["auto", "rrf", "cross", "llm", "colbert"]

function defaultSettings(): RetrievalConfig {
  return {
    mode: "pipeline",
    maxSteps: 6,
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
      mode: parsed.mode === "agent" ? "agent" : "pipeline",
      maxSteps:
        typeof parsed.maxSteps === "number" && parsed.maxSteps >= 1 && parsed.maxSteps <= 12
          ? parsed.maxSteps
          : base.maxSteps,
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
  const [stage, setStage] = useState(STAGE_LABELS.retrieve)
  const [settings, setSettings] = useState<RetrievalConfig>(() => defaultSettings())
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [inspectingId, setInspectingId] = useState<string | null>(null)

  // 已从服务端加载过的会话，避免"自己刚发消息"时被回源请求覆盖掉乐观消息
  const loadedRef = useRef<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

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
    const assistantId = `local-assistant-${Date.now()}`
    setMessages((previous) => [
      ...previous,
      { id: `local-user-${Date.now()}`, role: "user", content: question },
      {
        id: assistantId,
        role: "assistant",
        content: "",
        pending: true,
        features: activeFeatures,
        mode: settings.mode,
      },
    ])
    setInput("")
    setError(null)
    setStage(settings.mode === "agent" ? STAGE_LABELS.agent : STAGE_LABELS.retrieve)
    setLoading(true)
    setInspectingId(assistantId)

    const controller = new AbortController()
    abortRef.current = controller

    const patchAssistant = (patch: Partial<ChatMessageView>) => {
      setMessages((previous) =>
        previous.map((message) => (message.id === assistantId ? { ...message, ...patch } : message))
      )
    }

    try {
      const result = await queryDocStream(
        question,
        {
          conversationId: cid,
          topK: settings.topK,
          filters: filtersToRecord(settings.filters),
          features: activeFeatures,
          rerankStrategy: settings.rerankStrategy === "auto" ? null : settings.rerankStrategy,
          mode: settings.mode,
          maxSteps: settings.maxSteps,
          debug: inspectorOpen,
        },
        {
          onStage: (name, detail) => {
            setStage(STAGE_LABELS[name] ?? detail ?? STAGE_LABELS.retrieve)
          },
          onToken: (text) => {
            setMessages((previous) =>
              previous.map((message) =>
                message.id === assistantId
                  ? { ...message, content: message.content + text, pending: true }
                  : message
              )
            )
          },
          onSources: (sources, figures) => {
            patchAssistant({ sources, figures })
          },
          onAgentStep: (step: AgentStep) => {
            setMessages((previous) =>
              previous.map((message) => {
                if (message.id !== assistantId) return message
                const prev = message.trace
                const steps = [...(prev?.agent?.steps ?? []), step]
                const nextTrace: QueryTrace = {
                  features: prev?.features ?? [],
                  applied: prev?.applied ?? [],
                  skipped: prev?.skipped ?? [],
                  params: prev?.params ?? { top_k: settings.topK, filters: {}, rerank_strategy: null },
                  plan: prev?.plan ?? { subs: [], step_back: null, hyde: null, queries: [], rewritten: null },
                  routing: prev?.routing ?? { routed_docs: 0, top_score: 0, fallback: false, min_score: 0 },
                  channels: prev?.channels ?? [],
                  fusion: prev?.fusion ?? { channels: 0, pre_merge: 0, post_merge: 0, rerank: null, final: 0 },
                  timings: prev?.timings ?? { plan_ms: 0, retrieve_ms: 0, generate_ms: 0 },
                  agent: {
                    steps,
                    termination: prev?.agent?.termination ?? null,
                    budget: prev?.agent?.budget ?? {},
                    evidence_chunks: prev?.agent?.evidence_chunks ?? 0,
                    tools: prev?.agent?.tools ?? [],
                  },
                }
                return { ...message, trace: nextTrace }
              })
            )
          },
        },
        controller.signal
      )
      patchAssistant({
        content: result.answer,
        sources: result.sources,
        figures: result.figures,
        latency_ms: result.latency_ms,
        trace: result.trace ?? null,
        pending: false,
      })
      if (result.trace) setInspectingId(assistantId)
      void refreshConversations()
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") {
        setMessages((previous) =>
          previous.map((message) =>
            message.id === assistantId
              ? {
                  ...message,
                  pending: false,
                  content: message.content || "已停止生成。",
                }
              : message
          )
        )
      } else {
        setMessages((previous) => previous.filter((message) => message.id !== assistantId))
        setError(caught instanceof Error ? caught.message : "问答失败，请稍后重试")
      }
    } finally {
      abortRef.current = null
      setLoading(false)
    }
  }

  function handleCancel() {
    abortRef.current?.abort()
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
                stage={stage}
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
          onCancel={handleCancel}
          loading={loading}
          canClear={messages.length > 0}
          settings={settings}
          onSettingsChange={persistSettings}
        />
      </section>

      {inspectorOpen ? (
        <RetrievalInspector
          mode={inspectingMessage?.mode ?? null}
          trace={inspectingMessage?.trace ?? null}
          sources={inspectingMessage?.sources ?? []}
          loading={loading}
          onClose={() => setInspectorOpen(false)}
        />
      ) : null}
    </div>
  )
}
