"use client"

import { useEffect, useState } from "react"
import { Check, Eye, EyeOff, Plus, Trash2 } from "lucide-react"
import {
  activateProvider,
  deleteProvider,
  fetchProviders,
  testProvider,
  upsertProvider,
  type LLMProviderDraft,
} from "@/lib/api"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

interface Row extends LLMProviderDraft {
  id: string | null
  key: string
  msg: string
  msgOk: boolean
}

const BLANK: LLMProviderDraft = {
  name: "",
  model: "",
  base_url: "https://api.openai.com/v1",
  api_key: "",
  timeout: 60,
  active: false,
}

export function LLMSettings({ onChanged }: { onChanged?: () => void }) {
  const [rows, setRows] = useState<Row[]>([])
  const [error, setError] = useState<string | null>(null)
  const [showKeys, setShowKeys] = useState<Record<string, boolean>>({})

  useEffect(() => {
    let cancelled = false
    fetchProviders()
      .then((providers) => {
        if (cancelled) return
        setRows(
          providers.map((p) => ({
            name: p.name,
            model: p.model,
            base_url: p.base_url,
            api_key: p.api_key,
            timeout: p.timeout,
            active: p.active,
            id: p.id,
            key: p.id,
            msg: "",
            msgOk: true,
          }))
        )
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load providers")
      })
    return () => {
      cancelled = true
    }
  }, [])

  function update(key: string, patch: Partial<Row>) {
    setRows((prev) => prev.map((row) => (row.key === key ? { ...row, ...patch, msg: "" } : row)))
  }

  function setMsg(key: string, msg: string, ok: boolean) {
    setRows((prev) => prev.map((row) => (row.key === key ? { ...row, msg, msgOk: ok } : row)))
  }

  async function save(row: Row) {
    if (!row.name.trim() || !row.model.trim()) return
    try {
      const saved = await upsertProvider({
        name: row.name.trim(),
        model: row.model.trim(),
        base_url: row.base_url.trim() || "https://api.openai.com/v1",
        api_key: row.api_key.trim(),
        timeout: row.timeout,
        active: row.active,
      })
      update(row.key, { id: saved.id, name: saved.name, active: saved.active })
      setMsg(row.key, "Saved", true)
      onChanged?.()
    } catch (e) {
      setMsg(row.key, e instanceof Error ? e.message : "Save failed", false)
    }
  }

  async function activate(row: Row) {
    if (!row.id) {
      setMsg(row.key, "Save the row first", false)
      return
    }
    setMsg(row.key, "Activating…", true)
    try {
      await activateProvider(row.id)
      setRows((prev) =>
        prev.map((r) => ({
          ...r,
          active: r.id === row.id,
          msg: r.id === row.id ? "Activated" : r.msg && r.msgOk === false ? r.msg : "",
          msgOk: r.id === row.id ? true : r.msgOk,
        }))
      )
      onChanged?.()
    } catch (e) {
      setMsg(row.key, e instanceof Error ? e.message : "Activate failed", false)
    }
  }

  async function test(row: Row) {
    if (!row.id) {
      setMsg(row.key, "Save the row first", false)
      return
    }
    setMsg(row.key, "Testing…", true)
    try {
      const result = await testProvider(row.id)
      setMsg(row.key, result.detail, result.ok)
    } catch (e) {
      setMsg(row.key, e instanceof Error ? e.message : "Test failed", false)
    }
  }

  async function remove(row: Row) {
    if (row.id) {
      try {
        await deleteProvider(row.id)
      } catch (e) {
        setError(e instanceof Error ? e.message : "Delete failed")
        return
      }
    }
    setRows((prev) => prev.filter((r) => r.key !== row.key))
    onChanged?.()
  }

  return (
    <div className="mx-auto max-w-[1200px]">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">LLM Providers</h2>
          <p className="mt-1 max-w-xl text-sm text-muted-foreground">
            Add a provider and activate it. Chat answers use the active LLM; without one, the
            backend falls back to the .env configuration.
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() =>
            setRows((prev) => [
              ...prev,
              { ...BLANK, id: null, key: `draft-${Date.now()}`, msg: "", msgOk: true },
            ])
          }
        >
          <Plus /> Add provider
        </Button>
      </div>

      {error && (
        <Alert variant="destructive" className="mb-4">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {rows.length === 0 ? (
        <div className="py-20 text-center">
          <p className="text-lg font-medium">No LLM providers yet</p>
          <p className="mx-auto mt-1 max-w-sm text-sm text-muted-foreground">
            Add a provider with a name, model, base URL, and API key.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-card">
          <table className="w-full min-w-[980px] text-sm">
            <thead>
              <tr className="border-b bg-muted/30 text-left text-xs font-medium text-muted-foreground">
                <th className="px-3 py-2.5">Name</th>
                <th className="px-3 py-2.5">Model</th>
                <th className="px-3 py-2.5">Base URL</th>
                <th className="px-3 py-2.5">API key</th>
                <th className="px-3 py-2.5">Timeout</th>
                <th className="px-3 py-2.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key} className="border-b last:border-0">
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <Input
                        value={row.name}
                        placeholder="openai"
                        className="h-8 w-28"
                        onChange={(e) => update(row.key, { name: e.target.value })}
                      />
                      {row.active && (
                        <Badge variant="secondary" className="shrink-0 bg-primary/10 text-primary hover:bg-primary/10">
                          <Check className="size-3" /> Active
                        </Badge>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    <Input
                      value={row.model}
                      placeholder="gpt-4o-mini"
                      className="h-8 w-36"
                      onChange={(e) => update(row.key, { model: e.target.value })}
                    />
                  </td>
                  <td className="px-3 py-2.5">
                    <Input
                      value={row.base_url}
                      placeholder="https://api.openai.com/v1"
                      className="h-8 w-64"
                      onChange={(e) => update(row.key, { base_url: e.target.value })}
                    />
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-1.5">
                      <Input
                        type={showKeys[row.key] ? "text" : "password"}
                        value={row.api_key}
                        placeholder="sk-..."
                        className="h-8 w-36 font-mono"
                        onChange={(e) => update(row.key, { api_key: e.target.value })}
                      />
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-7"
                        title={showKeys[row.key] ? "Hide key" : "Show key"}
                        aria-label={showKeys[row.key] ? "Hide API key" : "Show API key"}
                        onClick={() =>
                          setShowKeys((prev) => ({ ...prev, [row.key]: !prev[row.key] }))
                        }
                      >
                        {showKeys[row.key] ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                      </Button>
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    <Input
                      type="number"
                      min={1}
                      max={600}
                      value={row.timeout}
                      className="h-8 w-16 font-mono"
                      onChange={(e) => update(row.key, { timeout: Number(e.target.value) || 60 })}
                    />
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center justify-end gap-1.5">
                      {row.msg && (
                        <span
                          className={`w-28 truncate text-right font-mono text-xs ${row.msgOk ? "text-muted-foreground" : "text-destructive"}`}
                          title={row.msg}
                        >
                          {row.msg}
                        </span>
                      )}
                      <Button size="xs" variant="outline" onClick={() => test(row)}>
                        Test
                      </Button>
                      <Button
                        size="xs"
                        variant={row.active ? "secondary" : "outline"}
                        onClick={() => activate(row)}
                        disabled={row.active}
                      >
                        {row.active ? "In use" : "Activate"}
                      </Button>
                      <Button
                        size="xs"
                        onClick={() => save(row)}
                        disabled={!row.name.trim() || !row.model.trim()}
                      >
                        Save
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-7 text-muted-foreground hover:text-destructive"
                        onClick={() => remove(row)}
                        title="Delete"
                        aria-label="Delete provider"
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
