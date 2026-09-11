"use client"

import { type ReactNode } from "react"

import { cn } from "@/lib/utils"

/**
 * 轻量 Markdown 渲染器。
 *
 * 为什么不用 react-markdown：本项目的回答文本结构很有限（标题/列表/代码/粗体/行内代码 +
 * [Source N] 引用标记），为它引入一条依赖链不划算。这里只覆盖实际会出现的语法。
 */

const INLINE_PATTERN = /\[Source\s+(\d+)\]|\*\*([^*]+)\*\*|`([^`]+)`|\*([^*\n]+)\*/g

function renderInline(text: string, onCite?: (n: number) => void, keyPrefix = ""): ReactNode[] {
  const nodes: ReactNode[] = []
  let lastIndex = 0
  let index = 0
  let match: RegExpExecArray | null
  INLINE_PATTERN.lastIndex = 0

  while ((match = INLINE_PATTERN.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index))
    }
    const key = `${keyPrefix}-${index++}`
    if (match[1] !== undefined) {
      const n = Number(match[1])
      nodes.push(
        onCite ? (
          <button
            key={key}
            type="button"
            onClick={() => onCite(n)}
            title={`跳转到证据 ${n}`}
            className="mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-[4px] bg-primary/15 px-1 align-super font-mono text-meta leading-none text-primary transition-colors hover:bg-primary/25"
          >
            {n}
          </button>
        ) : (
          <sup key={key} className="mx-0.5 font-mono text-meta text-primary">
            [{n}]
          </sup>
        )
      )
    } else if (match[2] !== undefined) {
      nodes.push(
        <strong key={key} className="font-medium text-foreground">
          {match[2]}
        </strong>
      )
    } else if (match[3] !== undefined) {
      nodes.push(
        <code key={key} className="rounded-[4px] bg-muted px-1 py-0.5 font-mono text-xs">
          {match[3]}
        </code>
      )
    } else if (match[4] !== undefined) {
      nodes.push(
        <em key={key} className="italic">
          {match[4]}
        </em>
      )
    }
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex))
  }
  return nodes
}

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "code"; text: string }
  | { kind: "quote"; text: string }
  | { kind: "rule" }

function parseBlocks(content: string): Block[] {
  const lines = content.replace(/\r\n/g, "\n").split("\n")
  const blocks: Block[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    if (/^\s*```/.test(line)) {
      const body: string[] = []
      i += 1
      while (i < lines.length && !/^\s*```/.test(lines[i])) {
        body.push(lines[i])
        i += 1
      }
      i += 1
      blocks.push({ kind: "code", text: body.join("\n") })
      continue
    }

    const heading = /^\s{0,3}(#{1,6})\s+(.*)$/.exec(line)
    if (heading) {
      blocks.push({ kind: "heading", level: heading[1].length, text: heading[2].trim() })
      i += 1
      continue
    }

    if (/^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      blocks.push({ kind: "rule" })
      i += 1
      continue
    }

    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line)
    if (bullet) {
      const items: string[] = []
      while (i < lines.length) {
        const item = /^\s*[-*+]\s+(.*)$/.exec(lines[i])
        if (!item) break
        items.push(item[1])
        i += 1
      }
      blocks.push({ kind: "list", ordered: false, items })
      continue
    }

    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    if (numbered) {
      const items: string[] = []
      while (i < lines.length) {
        const item = /^\s*\d+[.)]\s+(.*)$/.exec(lines[i])
        if (!item) break
        items.push(item[1])
        i += 1
      }
      blocks.push({ kind: "list", ordered: true, items })
      continue
    }

    if (/^\s*>\s?/.test(line)) {
      const body: string[] = []
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        body.push(lines[i].replace(/^\s*>\s?/, ""))
        i += 1
      }
      blocks.push({ kind: "quote", text: body.join("\n") })
      continue
    }

    if (!line.trim()) {
      i += 1
      continue
    }

    const paragraph: string[] = []
    while (i < lines.length && lines[i].trim() && !/^\s*(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|>|```)/.test(lines[i])) {
      paragraph.push(lines[i])
      i += 1
    }
    blocks.push({ kind: "paragraph", text: paragraph.join("\n") })
  }

  return blocks
}

export function Markdown({
  content,
  onCite,
  className,
}: {
  content: string
  onCite?: (index: number) => void
  className?: string
}) {
  const blocks = parseBlocks(content)

  return (
    <div className={cn("space-y-2 text-body leading-relaxed", className)}>
      {blocks.map((block, blockIndex) => {
        const key = `b${blockIndex}`
        switch (block.kind) {
          case "heading": {
            const level = Math.min(block.level, 4)
            const size =
              level <= 2 ? "text-base font-medium" : level === 3 ? "text-sm font-medium" : "text-body font-medium"
            return (
              <p key={key} className={cn(size, "text-foreground")}>
                {renderInline(block.text, onCite, key)}
              </p>
            )
          }
          case "list":
            return block.ordered ? (
              <ol key={key} className="ml-4 list-decimal space-y-1">
                {block.items.map((item, itemIndex) => (
                  <li key={`${key}-${itemIndex}`}>{renderInline(item, onCite, `${key}-${itemIndex}`)}</li>
                ))}
              </ol>
            ) : (
              <ul key={key} className="ml-4 list-disc space-y-1">
                {block.items.map((item, itemIndex) => (
                  <li key={`${key}-${itemIndex}`}>{renderInline(item, onCite, `${key}-${itemIndex}`)}</li>
                ))}
              </ul>
            )
          case "code":
            return (
              <pre
                key={key}
                className="scroll-thin overflow-x-auto rounded-md border border-border bg-muted/60 p-2.5 font-mono text-xs"
              >
                <code>{block.text}</code>
              </pre>
            )
          case "quote":
            return (
              <blockquote key={key} className="border-l-2 border-border pl-3 text-muted-foreground">
                {renderInline(block.text, onCite, key)}
              </blockquote>
            )
          case "rule":
            return <hr key={key} className="border-border" />
          default:
            return (
              <p key={key} className="whitespace-pre-wrap break-words">
                {renderInline(block.text, onCite, key)}
              </p>
            )
        }
      })}
    </div>
  )
}
