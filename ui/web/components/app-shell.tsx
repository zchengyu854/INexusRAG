"use client"

import { useEffect, useState } from "react"
import { Cpu, Files, MessageCircle, Network } from "lucide-react"
import { DocumentList } from "@/components/document-list"
import { ChatPage } from "@/components/chat-page"
import { LLMSettings } from "@/components/llm-settings"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { getStats, getActiveProvider, type LLMProvider, type Stats } from "@/lib/api"

export function AppShell() {
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
    <main className="relative min-h-dvh overflow-x-hidden">
      <div aria-hidden className="ambient pointer-events-none fixed inset-0 z-0" />
      <div aria-hidden className="grain pointer-events-none fixed inset-0 z-30 opacity-[0.03]" />

      <Tabs value={tab} onValueChange={setTab} className="relative z-10 mx-auto flex min-h-dvh max-w-[1440px] flex-col">
        {/* Glass pill nav */}
        <div className="pointer-events-none sticky top-4 z-40 flex justify-center px-4 pb-3 pt-4">
          <div className="pointer-events-auto flex h-11 items-center gap-2 rounded-full border border-white/10 bg-foreground/[0.6] p-1.5 pl-4 shadow-[0_8px_32px_rgba(0,0,0,0.4),inset_0_1px_0_rgba(255,255,255,0.12)] backdrop-blur-xl">
            <span className="flex items-center gap-2 pr-2">
              <Network className="size-4 text-primary" />
              <span className="text-sm font-semibold tracking-tight">NexusRAG</span>
            </span>
            <span className="h-5 w-px bg-white/15" aria-hidden />
            <TabsList variant="line" className="h-7 gap-0.5 rounded-full bg-transparent px-1 text-foreground/50">
              <TabsTrigger value="chat" className="rounded-full px-3 text-xs data-active:bg-foreground data-active:text-background">
                <MessageCircle /> Chat
              </TabsTrigger>
              <TabsTrigger value="documents" className="rounded-full px-3 text-xs data-active:bg-foreground data-active:text-background">
                <Files /> Documents
              </TabsTrigger>
              <TabsTrigger value="llm" className="rounded-full px-3 text-xs data-active:bg-foreground data-active:text-background">
                <Cpu /> LLM
              </TabsTrigger>
            </TabsList>
            <span className="h-5 w-px bg-white/15" aria-hidden />
            {provider ? (
              <span className="flex items-center gap-1.5 rounded-full px-2.5 py-1 font-mono text-[11px] text-foreground/70" title={`Active LLM: ${provider.name} (${provider.model})`}>
                <span className="size-1.5 rounded-full bg-primary shadow-[0_0_6px] shadow-primary/50" />
                {provider.model}
              </span>
            ) : (
              <button onClick={() => setTab("llm")} className="rounded-full px-2.5 py-1 font-mono text-[11px] text-foreground/40 transition-colors hover:text-foreground/70">
                no llm
              </button>
            )}
            {stats && (
              <span className="hidden font-mono text-[10px] text-foreground/30 sm:block">
                {stats.total_documents}d {stats.total_chunks}c
              </span>
            )}
          </div>
        </div>

        {/* Content */}
        <div className="flex min-h-0 flex-1 flex-col px-4 pb-8 sm:px-6">
          <TabsContent value="chat" className="mt-0 min-h-0 flex-1">
            <ChatPage />
          </TabsContent>
          <TabsContent value="documents" className="mt-0 min-h-0 flex-1">
            <DocumentList />
          </TabsContent>
          <TabsContent value="llm" className="mt-0 min-h-0 flex-1">
            <LLMSettings onChanged={refreshStatus} />
          </TabsContent>
        </div>
      </Tabs>
    </main>
  )
}
