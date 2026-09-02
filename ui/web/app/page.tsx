import { DocumentList } from "@/components/document-list"
import { ChatPage } from "@/components/chat-page"
import { getStats } from "@/lib/api"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

export default async function Home() {
  let stats: any = null
  try {
    stats = await getStats()
  } catch {
    // Backend might not be running yet
  }

  return (
    <main className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b bg-card">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">NexusRAG</h1>
            <p className="text-sm text-muted-foreground">Multi-document intelligent Q&A system</p>
          </div>
          {stats && (
            <div className="flex gap-4 text-sm text-muted-foreground">
              <span><strong className="text-foreground">{stats.total_documents}</strong> docs</span>
              <span><strong className="text-foreground">{stats.total_chunks}</strong> chunks</span>
            </div>
          )}
        </div>
      </header>

      {/* Content */}
      <div className="max-w-6xl mx-auto px-4 py-6 w-full">
        <Tabs defaultValue="chat" className="w-full">
          <TabsList className="mb-6">
            <TabsTrigger value="chat">
              <ChatIcon /> Chat
            </TabsTrigger>
            <TabsTrigger value="documents">
              <DocsIcon /> Documents
            </TabsTrigger>
          </TabsList>

          <TabsContent value="chat" className="mt-0">
            <ChatPage />
          </TabsContent>

          <TabsContent value="documents" className="mt-0">
            <DocumentList />
          </TabsContent>
        </Tabs>
      </div>
    </main>
  )
}

function ChatIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mr-2">
      <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>
    </svg>
  )
}

function DocsIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mr-2">
      <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/>
      <polyline points="14 2 14 8 20 8"/>
    </svg>
  )
}
