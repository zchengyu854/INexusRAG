"use client"

import { useRef, type KeyboardEvent } from "react"
import { Send, Square, Trash2 } from "lucide-react"

import { applyMode, ModeToggle } from "@/components/chat/mode-toggle"
import { RetrievalSettings, type RetrievalConfig } from "@/components/chat/retrieval-settings"
import { Button } from "@/components/ui/button"

export function Composer({
  value,
  onChange,
  onSend,
  onClear,
  onCancel,
  loading,
  canClear,
  settings,
  onSettingsChange,
}: {
  value: string
  onChange: (next: string) => void
  onSend: () => void
  onClear: () => void
  onCancel?: () => void
  loading: boolean
  canClear: boolean
  settings: RetrievalConfig
  onSettingsChange: (next: RetrievalConfig) => void
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    if (!loading && value.trim()) onSend()
  }

  return (
    <div className="shrink-0 border-t border-border bg-card px-3 py-2.5">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <ModeToggle
            value={settings.mode}
            disabled={loading}
            onChange={(next) => onSettingsChange(applyMode(settings, next))}
          />
          <RetrievalSettings value={settings} onChange={onSettingsChange} disabled={loading} />
        </div>
        <Button
          variant="ghost"
          size="xs"
          onClick={onClear}
          disabled={loading || !canClear}
          title="清空当前会话"
          className="text-muted-foreground"
        >
          <Trash2 />
          清空
        </Button>
      </div>

      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入问题，Enter 发送，Shift+Enter 换行"
          rows={1}
          disabled={loading}
          className="scroll-thin max-h-[168px] min-h-[36px] flex-1 resize-none rounded-md border border-border bg-background px-2.5 py-2 text-body outline-none focus-visible:ring-2 focus-visible:ring-ring/40 disabled:opacity-50"
        />
        <Button
          size="icon"
          onClick={loading ? onCancel : onSend}
          disabled={loading ? !onCancel : !value.trim()}
          title={loading ? "停止生成" : "发送"}
        >
          {loading ? <Square className="size-3.5 fill-current" /> : <Send />}
        </Button>
      </div>
    </div>
  )
}
