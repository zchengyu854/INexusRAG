import { Cpu, Files, MessageCircle, Network } from "lucide-react"
import { DocumentList } from "@/components/document-list"
import { ChatPage } from "@/components/chat-page"
import { LLMSettings } from "@/components/llm-settings"
import { getStats, type Stats } from "@/lib/api"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

export default async function Home() {
  let stats: Stats | null = null
  try {
    stats = await getStats()
  } catch {
    // Backend might not be running yet
  }

  return (
    <main className="flex h-dvh flex-col overflow-hidden bg-muted/30">
      <header className="border-b bg-card">
        <div className="mx-auto flex w-full max-w-[1440px] items-center justify-between gap-6 px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground">
              <Network className="size-5" />
            </div>
            <div>
              <h1 className="text-xl font-semibold tracking-tight">NexusRAG</h1>
              <p className="text-sm text-muted-foreground">Multi-document intelligent Q&A system</p>
            </div>
          </div>
          {stats && (
            <div className="hidden items-center gap-5 text-sm text-muted-foreground sm:flex">
              <span><strong className="text-foreground">{stats.total_documents}</strong> documents</span>
              <span><strong className="text-foreground">{stats.total_chunks}</strong> chunks</span>
            </div>
          )}
        </div>
      </header>

      <div className="mx-auto flex min-h-0 w-full max-w-[1440px] flex-1 px-6 py-6">
        <Tabs defaultValue="chat" className="flex h-full min-h-0 w-full flex-col">
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
            <ChatPage />
          </TabsContent>

          <TabsContent value="documents" className="mt-0 min-h-0 overflow-y-auto">
            <DocumentList />
          </TabsContent>

          <TabsContent value="llm" className="mt-0 min-h-0 overflow-y-auto">
            <LLMSettings />
          </TabsContent>
        </Tabs>
      </div>
    </main>
  )
}
