import { DocumentList } from "@/components/document-list"
import { getStats } from "@/lib/api"

export default async function Home() {
  let stats: any = null
  try {
    stats = await getStats()
  } catch {
    // Backend might not be running yet
  }

  return (
    <main className="min-h-screen bg-background">
      <div className="max-w-4xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold">NexusRAG</h1>
          <p className="text-muted-foreground mt-1">Multi-document intelligent Q&A system</p>
        </div>

        {/* Stats */}
        {stats && (
          <div className="grid grid-cols-4 gap-4 mb-8">
            <StatCard label="Documents" value={stats.total_documents} />
            <StatCard label="Chunks" value={stats.total_chunks} />
            <StatCard label="Dimension" value={stats.embedding_dimension} />
            <StatCard label="Storage" value={`${stats.total_size_kb.toFixed(0)} KB`} />
          </div>
        )}

        {/* Document List */}
        <DocumentList />
      </div>
    </main>
  )
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="p-4 bg-card rounded-lg border">
      <p className="text-2xl font-bold">{value}</p>
      <p className="text-sm text-muted-foreground">{label}</p>
    </div>
  )
}
