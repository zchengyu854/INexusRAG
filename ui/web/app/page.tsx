"use client"

import { useEffect, useState } from "react"
import { Cpu, Files, MessageCircle, Network } from "lucide-react"
import { DocumentList } from "@/components/document-list"
import { ChatPage } from "@/components/chat-page"
import { LLMSettings } from "@/components/llm-settings"
import { ThemeToggle } from "@/components/theme-toggle"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { getStats, getActiveProvider, type LLMProvider, type Stats } from "@/lib/api"

export default function Home() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [provider, setProvider] = useState<LLMProvider | null>(null)
  const [tab, setTab] = useState("chat")

  function refreshStatus() {
    getActiveProvider().then(setProvider).catch(() => setProvider(null))
  }

  useEffect(() => {
    getStats().then(setStats).catch(() => setStats(null))
    refreshStatus()
  }, [])

  return (
    <main className="flex h-dvh flex-col overflow-hidden bg-background">
      <header className="h-16 shrink-0 border-b bg-card/80 backdrop-blur-sm">
        <div className="mx-auto flex h-full w-full max-w-[1440px] items-center justify-between gap-6 px-6">
          <div className="flex items-center gap-3">
            <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Network className="size-4" />
            </div>
            <span className="text-lg font-semibold tracking-tight">NexusRAG</span>
          </div>

          <div className="flex items-center gap-5">
            {provider ? (
              <span
                className="hidden items-center gap-2 text-xs text-muted-foreground sm:flex"
                title={`Active LLM: ${provider.name}`}
              >
                <span className="size-2 rounded-full bg-primary" aria-hidden />
                <span className="font-mono">{provider.model}</span>
              </span>
            ) : (
              <button
                onClick={() => setTab("llm")}
                className="hidden text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline sm:block"
              >
                No LLM active. Configure one
              </button>
            )}
            {stats && (
              <span className="hidden font-mono text-xs text-muted-foreground sm:block">
                {stats.total_documents} docs / {stats.total_chunks} chunks
              </span>
            )}
            <ThemeToggle />
          </div>
        </div>
      </header>

      <div className="mx-auto flex min-h-0 w-full max-w-[1440px] flex-1 px-6 py-6">
        <Tabs value={tab} onValueChange={setTab} className="flex h-full min-h-0 w-full flex-col">
          <TabsList className="mb-5 self-start">
            <TabsTrigger value="chat">
              <MessageCircle /> Chat
            </TabsTrigger>
            <TabsTrigger value="documents">
              <Files /> Documents
            </TabsTrigger>
            <TabsTrigger value="llm">
              <Cpu /> LLM
            </TabsTrigger>
          </TabsList>

          <TabsContent value="chat" className="mt-0 min-h-0 overflow-hidden">
            <div className="h-full animate-fade-up">
              <ChatPage onGoToDocuments={() => setTab("documents")} />
            </div>
          </TabsContent>

          <TabsContent value="documents" className="mt-0 min-h-0 overflow-y-auto">
            <div className="animate-fade-up">
              <DocumentList />
            </div>
          </TabsContent>

          <TabsContent value="llm" className="mt-0 min-h-0 overflow-y-auto">
            <div className="animate-fade-up">
              <LLMSettings onChanged={refreshStatus} />
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </main>
  )
}
