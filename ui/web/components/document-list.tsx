"use client"

import React from "react"
import { useState, useEffect, useCallback } from "react"
import { fetchDocs, uploadFile, ingestDocument, deleteDocument } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Upload, FileText, ArrowUpRight, Trash2, Loader2 } from "lucide-react"
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
      setDocs(await fetchDocs())
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
    <div className="mx-auto max-w-[1100px]">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Documents</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            PDF, Markdown, and TXT files are split into chunks and indexed locally.
          </p>
        </div>
        <UploadButton onUpload={handleUpload} loading={uploading} />
      </div>

      {error && (
        <Alert variant="destructive" className="mb-4">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {docs.length === 0 ? (
        <div className="py-20 text-center">
          <p className="text-lg font-medium">No documents yet</p>
          <p className="mx-auto mt-1 max-w-sm text-sm text-muted-foreground">
            Upload a file to build your knowledge base. Indexing takes a few seconds.
          </p>
          <Button className="mt-5" onClick={() => document.getElementById("doc-upload")?.click()}>
            <Upload /> Upload your first file
          </Button>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border bg-card">
          <div className="grid grid-cols-[1fr_auto_auto_120px] items-center gap-4 border-b bg-muted/30 px-4 py-2.5 text-xs font-medium text-muted-foreground">
            <span>File</span>
            <span className="w-20 text-right">Chunks</span>
            <span className="w-24">Status</span>
            <span />
          </div>
          <ul className="divide-y">
            {docs.map((doc) => (
              <li
                key={doc.id}
                className="grid cursor-pointer grid-cols-[1fr_auto_auto_120px] items-center gap-4 px-4 py-3 transition-colors hover:bg-muted/50"
                onClick={() => setSelectedDoc(doc)}
              >
                <div className="flex min-w-0 items-center gap-2.5">
                  <FileText className="size-4 shrink-0 text-muted-foreground" />
                  <span className="truncate font-medium">{doc.filename}</span>
                </div>
                <span className="w-20 text-right font-mono text-sm text-muted-foreground">
                  {doc.chunks || "-"}
                </span>
                <span className="w-24"><StatusBadge status={doc.status} /></span>
                <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                  {doc.status === "indexing" && (
                    <Loader2 className="size-3.5 animate-spin text-muted-foreground" aria-label="Indexing" />
                  )}
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7 text-muted-foreground"
                    onClick={() => setSelectedDoc(doc)}
                    title="Open"
                  >
                    <ArrowUpRight className="size-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7 text-muted-foreground hover:text-destructive"
                    onClick={() => handleDelete(doc.id)}
                    title="Delete"
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  if (status === "ready")
    return (
      <Badge variant="secondary" className="bg-primary/10 font-normal text-primary hover:bg-primary/10">
        Ready
      </Badge>
    )
  if (status === "indexing")
    return (
      <Badge variant="secondary" className="font-normal text-amber-600 dark:text-amber-400">
        Indexing
      </Badge>
    )
  if (status === "failed")
    return (
      <Badge variant="destructive" className="font-normal">
        Failed
      </Badge>
    )
  return <Badge variant="outline">{status}</Badge>
}

function UploadButton({ onUpload, loading }: { onUpload: (file: File) => void; loading: boolean }) {
  const inputRef = React.useRef<HTMLInputElement>(null)

  return (
    <>
      <Input
        id="doc-upload"
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
        {loading ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
        {loading ? "Uploading…" : "Upload document"}
      </Button>
    </>
  )
}
