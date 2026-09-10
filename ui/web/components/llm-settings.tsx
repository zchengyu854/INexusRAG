"use client"

import { useEffect, useState } from "react"
import { Check, Plus, Trash2 } from "lucide-react"
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

export function LLMSettings() {
  const [rows, setRows] = useState<Row[]>([])
  const [error, setError] = useState<string | null>(null)

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
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : "Failed to load"))
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
    if (!row.name.trim() || !row.model.trim()) {
      setMsg(row.key, "名称与模型不能为空", false)
      return
    }
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
      setMsg(row.key, "已保存", true)
    } catch (e) {
      setMsg(row.key, e instanceof Error ? e.message : "保存失败", false)
    }
  }

  async function activate(row: Row) {
    if (!row.id) {
      setMsg(row.key, "请先保存", false)
      return
    }
    try {
      await activateProvider(row.id)
      // 激活是互斥的，重载整个列表
      const providers = await fetchProviders()
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
    } catch (e) {
      setMsg(row.key, e instanceof Error ? e.message : "激活失败", false)
    }
  }

  async function test(row: Row) {
    if (!row.id) {
      setMsg(row.key, "请先保存", false)
      return
    }
    setMsg(row.key, "测试中…", true)
    try {
      const result = await testProvider(row.id)
      setMsg(row.key, result.detail, result.ok)
    } catch (e) {
      setMsg(row.key, e instanceof Error ? e.message : "测试失败", false)
    }
  }

  async function remove(row: Row) {
    if (!row.id) {
      setRows((prev) => prev.filter((r) => r.key !== row.key))
      return
    }
    try {
      await deleteProvider(row.id)
      setRows((prev) => prev.filter((r) => r.key !== row.key))
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败")
    }
  }

  return (
    <div className="mx-auto max-w-[1200px] space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">LLM Providers</h2>
          <p className="text-sm text-muted-foreground">
            填入 Provider 配置并激活，Chat 将使用激活的 LLM；未激活时回退 .env 配置
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() =>
            setRows((prev) => [
              ...prev,
              { ...BLANK, id: null, key: `draft-${prev.length}-${Date.now()}`, msg: "", msgOk: true },
            ])
          }
        >
          <Plus /> Add provider
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {rows.length === 0 ? (
        <div className="py-12 text-center text-muted-foreground">
          <p className="text-lg">No LLM providers yet</p>
          <p className="mt-1 text-sm">点击右上角 “Add provider” 添加第一个 Provider</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-card">
          <table className="w-full min-w-[960px] text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Model</th>
                <th className="px-3 py-2 font-medium">Base URL</th>
                <th className="px-3 py-2 font-medium">API Key</th>
                <th className="px-3 py-2 font-medium">Timeout</th>
                <th className="px-3 py-2 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key} className="border-b last:border-0">
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <Input
                        value={row.name}
                        placeholder="openai"
                        className="h-8 w-28"
                        onChange={(e) => update(row.key, { name: e.target.value })}
                      />
                      {row.active && (
                        <Badge>
                          <Check className="size-3" /> Active
                        </Badge>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <Input
                      value={row.model}
                      placeholder="gpt-4o-mini"
                      className="h-8 w-36"
                      onChange={(e) => update(row.key, { model: e.target.value })}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <Input
                      value={row.base_url}
                      placeholder="https://api.openai.com/v1"
                      className="h-8 w-64"
                      onChange={(e) => update(row.key, { base_url: e.target.value })}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <Input
                      type="password"
                      value={row.api_key}
                      placeholder="sk-..."
                      className="h-8 w-44"
                      onChange={(e) => update(row.key, { api_key: e.target.value })}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <Input
                      type="number"
                      min={1}
                      max={600}
                      value={row.timeout}
                      className="h-8 w-20"
                      onChange={(e) => update(row.key, { timeout: Number(e.target.value) || 60 })}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center justify-end gap-1.5">
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
                      <Button size="xs" variant="ghost" onClick={() => remove(row)}>
                        <Trash2 />
                      </Button>
                      {row.msg && (
                        <span
                          className={`w-36 truncate text-xs ${row.msgOk ? "text-muted-foreground" : "text-destructive"}`}
                          title={row.msg}
                        >
                          {row.msg}
                        </span>
                      )}
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
