"use client"

import React from "react"
import { useState, useEffect, useCallback } from "react"
import { fetchDocs, uploadFile, ingestDocument, deleteDocument } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { DocumentViewer } from "./document-viewer"

interface Doc {
  id: string
  filename: string
  chunks: number
  status: string
}

export function DocumentList() {
  const [docs, setDocs] = useState<Doc[]>([])
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedDoc, setSelectedDoc] = useState<Doc | null>(null)

  const loadDocs = useCallback(async () => {
    try {
      const data = await fetchDocs()
      setDocs(data)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load documents")
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadDocs() }, 0)
    return () => window.clearTimeout(timer)
  }, [loadDocs])

  useEffect(() => {
    if (!docs.some((doc) => doc.status === "indexing")) return
    const timer = window.setInterval(loadDocs, 1500)
    return () => window.clearInterval(timer)
  }, [docs, loadDocs])

  async function handleUpload(file: File) {
    setUploading(true)
    setError(null)
    try {
      const result = await uploadFile(file)
      await ingestDocument(result.id)
      await loadDocs()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed")
    } finally {
      setUploading(false)
    }
  }

  async function handleDelete(docId: string) {
    try {
      await deleteDocument(docId)
      await loadDocs()
      if (selectedDoc?.id === docId) setSelectedDoc(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed")
    }
  }

  if (selectedDoc) {
    return (
      <DocumentViewer
        doc={selectedDoc}
        onBack={() => setSelectedDoc(null)}
        onDeleted={() => handleDelete(selectedDoc.id).then(() => setSelectedDoc(null))}
        onRefresh={loadDocs}
      />
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Documents</h2>
        <UploadButton onUpload={handleUpload} loading={uploading} />
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {docs.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          <p className="text-lg">No documents yet</p>
          <p className="text-sm mt-1">Upload a PDF, Markdown, or TXT file to get started</p>
        </div>
      ) : (
        <div className="grid gap-4">
          {docs.map((doc) => (
            <Card
              key={doc.id}
              className="cursor-pointer hover:border-primary/50 transition-colors"
              onClick={() => setSelectedDoc(doc)}
            >
              <CardContent className="p-4 flex items-center justify-between">
                <div className="flex-1 min-w-0">
                  <p className="font-medium truncate">{doc.filename}</p>
                  <p className="text-sm text-muted-foreground">
                    {doc.chunks} chunks
                  </p>
                </div>
                <StatusBadge status={doc.status} />
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const config = {
    ready: { label: "Ready", variant: "default" as const },
    indexing: { label: "Indexing", variant: "secondary" as const },
    failed: { label: "Failed", variant: "destructive" as const },
    pending: { label: "Pending", variant: "outline" as const },
  }[status] || { label: status, variant: "outline" as const }

  return <Badge variant={config.variant}>{config.label}</Badge>
}

function UploadButton({ onUpload, loading }: { onUpload: (file: File) => void; loading: boolean }) {
  const inputRef = React.useRef<HTMLInputElement>(null)

  return (
    <>
      <Input
        ref={inputRef}
        type="file"
        accept=".pdf,.md,.markdown,.txt"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) onUpload(file)
          e.target.value = ""
        }}
      />
      <Button onClick={() => inputRef.current?.click()} disabled={loading}>
        {loading ? "Uploading file..." : "+ Upload Document"}
      </Button>
    </>
  )
}
