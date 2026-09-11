"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { AlertCircle, Loader2, Upload } from "lucide-react"

import { DocumentDetail } from "@/components/documents/document-detail"
import { DocumentTable } from "@/components/documents/document-table"
import { Button } from "@/components/ui/button"
import { deleteDocument, fetchDocs, ingestDocument, uploadFile, type Doc } from "@/lib/api"
import { cn } from "@/lib/utils"

const ACCEPT = ".pdf,.md,.markdown,.txt"
const POLL_MS = 1500

export function DocumentsPage() {
  const [docs, setDocs] = useState<Doc[]>([])
  const [selected, setSelected] = useState<Doc | null>(null)
  const [uploading, setUploading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const loadDocs = useCallback(async () => {
    try {
      const rows = await fetchDocs()
      setDocs(rows)
      setError(null)
      return rows
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载文档失败")
      return []
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadDocs()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadDocs])

  // 仅在有文档处于 indexing 时轮询，空闲即停表
  useEffect(() => {
    if (!docs.some((doc) => doc.status === "indexing")) return
    const timer = window.setInterval(async () => {
      const rows = await loadDocs()
      setSelected((current) => (current ? rows.find((doc) => doc.id === current.id) ?? current : current))
    }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [docs, loadDocs])

  async function handleFiles(files: FileList | File[]) {
    const list = Array.from(files)
    if (list.length === 0) return
    setUploading(true)
    setError(null)
    try {
      for (const file of list) {
        const created = await uploadFile(file)
        await ingestDocument(created.id)
      }
      await loadDocs()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "上传失败")
    } finally {
      setUploading(false)
    }
  }

  async function handleDelete(docId: string) {
    try {
      await deleteDocument(docId)
      if (selected?.id === docId) setSelected(null)
      await loadDocs()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "删除失败")
    }
  }

  const toolbar = (
    <div className="flex items-center gap-2">
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPT}
        className="hidden"
        onChange={(event) => {
          const files = event.target.files
          if (files) void handleFiles(files)
          event.target.value = ""
        }}
      />
      <Button size="sm" onClick={() => inputRef.current?.click()} disabled={uploading}>
        {uploading ? <Loader2 className="animate-spin" /> : <Upload />}
        {uploading ? "上传中…" : "上传文档"}
      </Button>
    </div>
  )

  if (selected) {
    return (
      <DocumentDetail
        doc={selected}
        onBack={() => setSelected(null)}
        onRefresh={loadDocs}
        onDelete={() => handleDelete(selected.id)}
      />
    )
  }

  return (
    <div
      className={cn("relative h-full", dragging && "ring-2 ring-primary ring-inset")}
      onDragOver={(event) => {
        event.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault()
        setDragging(false)
        if (event.dataTransfer.files) void handleFiles(event.dataTransfer.files)
      }}
    >
      <div className="scroll-thin h-full overflow-y-auto p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-medium">文档</h2>
            <p className="mt-0.5 text-meta text-muted-foreground">
              支持 PDF / Markdown / TXT，上传后自动切片并向量化入库。可直接把文件拖到页面任意位置。
            </p>
          </div>
          {toolbar}
        </div>

        {error ? (
          <p className="mb-3 flex items-center gap-1.5 rounded-md border border-destructive/30 px-2.5 py-1.5 text-body text-destructive">
            <AlertCircle className="size-3.5 shrink-0" />
            {error}
          </p>
        ) : null}

        {docs.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-md border border-dashed border-border py-20 text-center">
            <span className="mb-3 flex size-10 items-center justify-center rounded-lg bg-primary/12">
              <Upload className="size-4 text-primary" />
            </span>
            <p className="text-sm font-medium">还没有文档</p>
            <p className="mt-1 max-w-sm text-body text-muted-foreground">
              上传一个文件来构建知识库，入库通常需要几秒到几十秒。
            </p>
            <Button className="mt-4" size="sm" onClick={() => inputRef.current?.click()}>
              <Upload />
              上传第一个文件
            </Button>
          </div>
        ) : (
          <DocumentTable docs={docs} onOpen={setSelected} onDelete={handleDelete} />
        )}
      </div>

      {dragging ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-background/70 text-sm font-medium text-primary">
          松开即可上传
        </div>
      ) : null}
    </div>
  )
}
