"use client"

import { useState, useRef, useEffect } from "react"
import { queryDoc } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { Send, Bot, User, FileText, Search, Loader2, AlertCircle } from "lucide-react"

interface Source {
  doc_name: string
  text: string
  score: number
}

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  sources?: Source[]
  timestamp: Date
}

export function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState(0)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  // Auto-resize textarea
  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = Math.min(el.scrollHeight, 200) + "px"
  }, [input])

  async function handleSend() {
    const question = input.trim()
    if (!question || loading) return

    const userMsg: Message = {
      id: Date.now().toString(),
      role: "user",
      content: question,
      timestamp: new Date(),
    }
    setMessages((prev) => [...prev, userMsg])
    setInput("")
    setLoading(true)
    setError(null)
    setProgress(5)

    // Simulate progress
    const progressInterval = setInterval(() => {
      setProgress((p) => Math.min(p + 10, 90))
    }, 300)

    try {
      const result = await queryDoc(question)
      clearInterval(progressInterval)
      setProgress(100)

      const assistantMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: result.answer,
        sources: result.sources || [],
        timestamp: new Date(),
      }
      setMessages((prev) => [...prev, assistantMsg])
    } catch (e) {
      setError(e instanceof Error ? e.message : "Query failed")
    } finally {
      clearInterval(progressInterval)
      setLoading(false)
      setProgress(0)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-13rem)]">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-6">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center space-y-4">
            <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center">
              <Bot className="w-8 h-8 text-primary" />
            </div>
            <div>
              <h2 className="text-xl font-semibold">Ask anything about your documents</h2>
              <p className="text-muted-foreground mt-1">Upload documents first, then ask questions to get answers from your knowledge base.</p>
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {loading && (
          <div className="space-y-2">
            <div className="flex items-start gap-3">
              <Avatar className="w-8 h-8 mt-1">
                <AvatarFallback className="bg-primary/10">
                  <Bot className="w-4 h-4 text-primary" />
                </AvatarFallback>
              </Avatar>
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-4 w-1/2" />
                <Progress value={progress} className="h-1" />
              </div>
            </div>
          </div>
        )}

        {error && (
          <div className="flex items-start gap-3">
            <Avatar className="w-8 h-8 mt-1">
              <AvatarFallback className="bg-destructive/10">
                <AlertCircle className="w-4 h-4 text-destructive" />
              </AvatarFallback>
            </Avatar>
            <Card className="border-destructive/50">
              <CardContent className="p-3 text-sm text-destructive">
                {error}
              </CardContent>
            </Card>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t bg-card p-4">
        <div className="max-w-3xl mx-auto flex gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question... (Enter to send, Shift+Enter for new line)"
            className="flex-1 resize-none rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 min-h-[44px] max-h-[200px]"
            rows={1}
            disabled={loading}
          />
          <Button onClick={handleSend} disabled={loading || !input.trim()} size="lg">
            {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
          </Button>
        </div>
      </div>
    </div>
  )
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user"

  return (
    <div className={`flex items-start gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
      <Avatar className="w-8 h-8">
        <AvatarFallback className={isUser ? "bg-primary text-primary-foreground" : "bg-primary/10"}>
          {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4 text-primary" />}
        </AvatarFallback>
      </Avatar>

      <div className={`max-w-[80%] space-y-2 ${isUser ? "items-end" : "items-start"} flex flex-col`}>
        <div className={`px-4 py-2 rounded-lg ${
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-foreground"
        }`}>
          <p className="text-sm whitespace-pre-wrap break-words">{message.content}</p>
        </div>

        {message.sources && message.sources.length > 0 && (
          <div className="w-full space-y-1">
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <Search className="w-3 h-3" />
              <span>{message.sources.length} sources</span>
            </div>
            {message.sources.map((source, i) => (
              <SourceChip key={i} source={source} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function SourceChip({ source }: { source: Source }) {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-muted/50 text-xs hover:bg-muted transition-colors cursor-pointer">
      <FileText className="w-3 h-3 text-muted-foreground shrink-0" />
      <span className="font-medium truncate">{source.doc_name}</span>
      {source.score != null && (
        <span className="ml-auto text-muted-foreground shrink-0">
          {source.score.toFixed(2)}
        </span>
      )}
    </div>
  )
}
