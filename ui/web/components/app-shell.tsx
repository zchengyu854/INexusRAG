"use client"

import { useEffect, useState } from "react"
import { Cpu, Files, MessageCircle, Network } from "lucide-react"
import { DocumentList } from "@/components/document-list"
import { ChatPage } from "@/components/chat-page"
import { LLMSettings } from "@/components/llm-settings"
import { HeroSection } from "@/components/hero-section"
import { FeatureBento } from "@/components/feature-bento"
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

  function scrollToApp() {
    document.getElementById("app-section")?.scrollIntoView({ behavior: "smooth" })
  }

  return (
    <main className="relative min-h-dvh overflow-x-hidden">
      <div aria-hidden className="ambient pointer-events-none fixed inset-0 z-0" />
      <div aria-hidden className="grain pointer-events-none fixed inset-0 z-30 opacity-[0.04]" />

      <Tabs value={tab} onValueChange={setTab} className="relative z-10 flex flex-col gap-0">
        {/* Floating glass pill nav — inside Tabs for context */}
        <div className="pointer-events-none sticky top-5 z-40 flex justify-center px-4 pb-4">
          <div className="pointer-events-auto flex h-12 items-center gap-2 rounded-full border border-white/10 bg-foreground/[0.55] p-1.5 pl-4 shadow-[0_12px_40px_rgba(0,0,0,0.45),inset_0_1px_0_rgba(255,255,255,0.14)] backdrop-blur-2xl">
            <span className="flex items-center gap-2 pr-2">
              <Network className="size-4" />
              <span className="text-sm font-semibold tracking-tight">NexusRAG</span>
            </span>
            <span className="h-6 w-px bg-white/15" aria-hidden />
            <TabsList
              variant="line"
              className="h-8 gap-1 rounded-full bg-transparent px-1 text-foreground/60"
            >
              <TabsTrigger value="chat" className="rounded-full data-active:bg-foreground data-active:text-background">
                <MessageCircle /> Chat
              </TabsTrigger>
              <TabsTrigger value="documents" className="rounded-full data-active:bg-foreground data-active:text-background">
                <Files /> Documents
              </TabsTrigger>
              <TabsTrigger value="llm" className="rounded-full data-active:bg-foreground data-active:text-background">
                <Cpu /> LLM
              </TabsTrigger>
            </TabsList>
            <span className="h-6 w-px bg-white/15" aria-hidden />
            {provider ? (
              <span className="flex items-center gap-2 rounded-full px-3 py-1.5 font-mono text-xs text-foreground/80" title={`Active LLM: ${provider.name}`}>
                <span className="size-1.5 rounded-full bg-primary shadow-[0_0_8px] shadow-primary/60" aria-hidden />
                {provider.model}
              </span>
            ) : (
              <button onClick={() => { setTab("llm"); scrollToApp() }} className="rounded-full px-3 py-1.5 font-mono text-xs text-foreground/50 underline-offset-4 transition-colors hover:text-foreground hover:underline">
                no llm active
              </button>
            )}
          </div>
        </div>

        {/* AIDA: Attention (Hero) */}
        <HeroSection
          onGoToChat={() => { setTab("chat"); scrollToApp() }}
          onGoToDocuments={() => { setTab("documents"); scrollToApp() }}
        />

        {/* AIDA: Interest (Feature Bento) */}
        <div className="mx-auto w-full max-w-[1200px] px-4 py-32 sm:px-6 md:py-48">
          <FeatureBento />
        </div>

        {/* AIDA: Desire — stats strip */}
        {stats && (
          <div className="border-y border-white/[0.06] py-12">
            <div className="mx-auto flex max-w-[1000px] flex-wrap items-center justify-center gap-x-12 gap-y-4 font-mono text-[11px] uppercase tracking-[0.22em] text-foreground/30">
              <span><span className="mr-2 text-foreground/60">{stats.total_documents}</span>documents</span>
              <span><span className="mr-2 text-foreground/60">{stats.total_chunks}</span>chunks indexed</span>
              <span><span className="mr-2 text-foreground/60">{stats.embedding_dimension}D</span>embeddings</span>
              <span><span className="mr-2 text-foreground/60">{stats.total_size_kb}</span>KB stored</span>
            </div>
          </div>
        )}

        {/* AIDA: Action (App + Footer) */}
        <div id="app-section" className="mx-auto w-full max-w-[1200px] scroll-mt-24 px-4 py-20 sm:px-6 md:py-32">
          <TabsContent value="chat" className="mt-0 min-h-0">
            <ChatPage onGoToDocuments={() => setTab("documents")} />
          </TabsContent>
          <TabsContent value="documents" className="mt-0 min-h-0">
            <DocumentList />
          </TabsContent>
          <TabsContent value="llm" className="mt-0 min-h-0 pb-16">
            <LLMSettings onChanged={refreshStatus} />
          </TabsContent>
        </div>

        <footer className="border-t border-white/[0.06] py-16">
          <div className="mx-auto flex max-w-[1200px] flex-col items-center gap-6 px-4 text-center sm:px-6">
            <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-foreground/25">
              NexusRAG · Multi-document intelligent Q&A
            </p>
            <div className="flex gap-6 text-xs text-foreground/35">
              <button onClick={() => { setTab("chat"); scrollToApp() }} className="transition-colors hover:text-foreground/60">Chat</button>
              <button onClick={() => { setTab("documents"); scrollToApp() }} className="transition-colors hover:text-foreground/60">Documents</button>
              <button onClick={() => { setTab("llm"); scrollToApp() }} className="transition-colors hover:text-foreground/60">Settings</button>
            </div>
          </div>
        </footer>
      </Tabs>
    </main>
  )
}
