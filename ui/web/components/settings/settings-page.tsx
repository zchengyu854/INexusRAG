"use client"

import { useCallback, useEffect, useState } from "react"
import { Check, Cpu, Eye, EyeOff, Loader2, Plus, Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { KeyValueRow } from "@/components/ui/metric"
import { Panel, PanelBody, PanelHeader, PanelSection } from "@/components/ui/panel"
import {
  activateProvider,
  deleteProvider,
  fetchProviders,
  getHealth,
  testProvider,
  upsertProvider,
  type HealthStatus,
  type LLMProvider,
  type LLMProviderDraft,
} from "@/lib/api"
import { cn } from "@/lib/utils"

const BLANK: LLMProviderDraft = {
  name: "",
  model: "",
  base_url: "https://api.openai.com/v1",
  api_key: "",
  timeout: 60,
  active: false,
}

const GRID = "grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_72px_68px_132px] items-center gap-3"

export function SettingsPage() {
  const [providers, setProviders] = useState<LLMProvider[]>([])
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [draft, setDraft] = useState<LLMProviderDraft>(BLANK)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [showKey, setShowKey] = useState(false)
  const [saving, setSaving] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [rows, current] = await Promise.all([fetchProviders(), getHealth()])
      setProviders(rows)
      setHealth(current)
      setError(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载失败")
    }
  }, [])

  // 延后一拍再拉取：避免在 effect 体内同步 setState 触发级联渲染（与仓库既有约定一致）
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [load])

  function startEdit(provider: LLMProvider) {
    setEditingId(provider.id)
    setDraft({
      name: provider.name,
      model: provider.model,
      base_url: provider.base_url,
      api_key: provider.api_key,
      timeout: provider.timeout,
      active: provider.active,
    })
    setMessage(null)
  }

  function resetForm() {
    setEditingId(null)
    setDraft(BLANK)
    setMessage(null)
  }

  async function handleSave() {
    if (!draft.name.trim() || !draft.model.trim()) {
      setMessage({ ok: false, text: "名称与模型为必填" })
      return
    }
    setSaving(true)
    setMessage(null)
    try {
      await upsertProvider({ ...draft, name: draft.name.trim(), model: draft.model.trim() })
      setMessage({ ok: true, text: editingId ? "已更新" : "已新增" })
      resetForm()
      await load()
    } catch (caught) {
      setMessage({ ok: false, text: caught instanceof Error ? caught.message : "保存失败" })
    } finally {
      setSaving(false)
    }
  }

  async function handleTest(provider: LLMProvider) {
    setBusyId(provider.id)
    setMessage(null)
    try {
      const result = await testProvider(provider.id)
      const lines = [`${provider.name}：${result.detail}`]
      // 失败时把「该改什么」和「实际打到了哪个端点」都摊开：
      // 只显示一句原始报错，用户无从判断是密钥、余额还是端点的问题
      if (result.hint) lines.push(`建议：${result.hint}`)
      if (result.provider) {
        lines.push(`端点：${result.provider.base_url}　模型：${result.provider.model}　密钥：${result.provider.key}`)
      }
      setMessage({ ok: result.ok, text: lines.join("\n") })
    } catch (caught) {
      setMessage({ ok: false, text: caught instanceof Error ? caught.message : "测试失败" })
    } finally {
      setBusyId(null)
      // 测试会写入运行时的 LLM 可用性，重取健康状态让右侧「系统信息」立刻反映结果
      void load()
    }
  }

  async function handleActivate(provider: LLMProvider) {
    setBusyId(provider.id)
    try {
      await activateProvider(provider.id)
      await load()
    } catch (caught) {
      setMessage({ ok: false, text: caught instanceof Error ? caught.message : "激活失败" })
    } finally {
      setBusyId(null)
    }
  }

  async function handleDelete(provider: LLMProvider) {
    if (!window.confirm(`删除 provider「${provider.name}」？`)) return
    setBusyId(provider.id)
    try {
      await deleteProvider(provider.id)
      if (editingId === provider.id) resetForm()
      await load()
    } catch (caught) {
      setMessage({ ok: false, text: caught instanceof Error ? caught.message : "删除失败" })
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="flex h-full min-h-0">
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto p-4">
        <div className="mb-3">
          <h2 className="text-base font-medium">LLM Providers</h2>
          <p className="mt-0.5 text-meta text-muted-foreground">
            被标记为「生效」的 provider 会驱动问答生成与图谱抽取；未配置时回退到 .env。
          </p>
        </div>

        {error ? (
          <p className="mb-3 rounded-md border border-destructive/30 px-2.5 py-1.5 text-body text-destructive">
            {error}
          </p>
        ) : null}

        {message ? (
          <p
            className={cn(
              "mb-3 whitespace-pre-line rounded-md px-2.5 py-1.5 text-body",
              message.ok ? "bg-success/12 text-success" : "bg-destructive/12 text-destructive"
            )}
          >
            {message.text}
          </p>
        ) : null}

        <div className="mb-4 overflow-hidden rounded-md border border-border">
          <div className={`${GRID} border-b border-border bg-muted/40 px-3 py-2 text-meta text-muted-foreground`}>
            <span>名称</span>
            <span>模型</span>
            <span className="text-right">超时</span>
            <span>状态</span>
            <span className="text-right">操作</span>
          </div>
          {providers.length === 0 ? (
            <p className="px-3 py-6 text-center text-body text-muted-foreground">
              还没有 provider。填写下方表单新增一个，或依赖 .env 中的配置。
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {providers.map((provider) => (
                <li key={provider.id} className={`${GRID} px-3 py-2`}>
                  <div className="min-w-0">
                    <p className="truncate text-body font-medium">{provider.name}</p>
                    <p className="truncate font-mono text-meta text-muted-foreground">{provider.base_url}</p>
                  </div>
                  <span className="truncate font-mono text-xs text-muted-foreground">{provider.model}</span>
                  <span className="text-right font-mono text-xs text-muted-foreground">{provider.timeout}s</span>
                  <span>
                    {provider.active ? (
                      <span className="inline-flex items-center gap-1 rounded-md bg-success/15 px-1.5 py-0.5 text-meta text-success">
                        <Check className="size-3" />
                        生效
                      </span>
                    ) : (
                      <span className="text-meta text-muted-foreground">未启用</span>
                    )}
                  </span>
                  <div className="flex justify-end gap-0.5">
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      title="连通性测试"
                      disabled={busyId === provider.id}
                      onClick={() => void handleTest(provider)}
                    >
                      {busyId === provider.id ? <Loader2 className="animate-spin" /> : <Cpu />}
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      title="设为生效"
                      disabled={provider.active || busyId === provider.id}
                      onClick={() => void handleActivate(provider)}
                    >
                      <Check />
                    </Button>
                    <Button variant="ghost" size="xs" onClick={() => startEdit(provider)}>
                      编辑
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      title="删除"
                      className="text-muted-foreground hover:text-destructive"
                      onClick={() => void handleDelete(provider)}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <section className="rounded-md border border-border p-3">
          <h3 className="mb-2 text-body font-medium">{editingId ? "编辑 provider" : "新增 provider"}</h3>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="space-y-1">
              <span className="text-meta text-muted-foreground">名称（唯一）</span>
              <input
                value={draft.name}
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                placeholder="openai-main"
                className="h-7 w-full rounded-md border border-border bg-background px-2 text-body outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
              />
            </label>
            <label className="space-y-1">
              <span className="text-meta text-muted-foreground">模型</span>
              <input
                value={draft.model}
                onChange={(event) => setDraft({ ...draft, model: event.target.value })}
                placeholder="gpt-4o-mini"
                className="h-7 w-full rounded-md border border-border bg-background px-2 font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
              />
            </label>
            <label className="space-y-1 sm:col-span-2">
              <span className="text-meta text-muted-foreground">Base URL</span>
              <input
                value={draft.base_url}
                onChange={(event) => setDraft({ ...draft, base_url: event.target.value })}
                className="h-7 w-full rounded-md border border-border bg-background px-2 font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
              />
            </label>
            <label className="space-y-1">
              <span className="text-meta text-muted-foreground">API Key</span>
              <span className="relative block">
                <input
                  type={showKey ? "text" : "password"}
                  value={draft.api_key}
                  onChange={(event) => setDraft({ ...draft, api_key: event.target.value })}
                  className="h-7 w-full rounded-md border border-border bg-background px-2 pr-7 font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                />
                <button
                  type="button"
                  onClick={() => setShowKey((value) => !value)}
                  title={showKey ? "隐藏" : "显示"}
                  className="absolute top-1/2 right-1.5 -translate-y-1/2 text-muted-foreground"
                >
                  {showKey ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                </button>
              </span>
            </label>
            <label className="space-y-1">
              <span className="text-meta text-muted-foreground">超时（秒）</span>
              <input
                type="number"
                min={1}
                max={600}
                value={draft.timeout}
                onChange={(event) => setDraft({ ...draft, timeout: Number(event.target.value) || 60 })}
                className="h-7 w-full rounded-md border border-border bg-background px-2 font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
              />
            </label>
          </div>

          <label className="mt-2 flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={draft.active}
              onChange={(event) => setDraft({ ...draft, active: event.target.checked })}
              className="size-3.5 rounded border-border accent-primary"
            />
            <span className="text-body">保存后立即设为生效</span>
          </label>

          <div className="mt-3 flex gap-2">
            <Button size="sm" onClick={() => void handleSave()} disabled={saving}>
              {saving ? <Loader2 className="animate-spin" /> : <Plus />}
              {editingId ? "保存修改" : "新增"}
            </Button>
            {editingId ? (
              <Button variant="outline" size="sm" onClick={resetForm}>
                取消编辑
              </Button>
            ) : null}
          </div>
        </section>
      </div>

      <Panel className="w-[268px] shrink-0">
        <PanelHeader title="系统信息" />
        <PanelBody className="space-y-3.5">
          <PanelSection label="运行状态">
            <div className="divide-y divide-border">
              <KeyValueRow label="服务状态">{health?.status === "ok" ? "正常" : "降级"}</KeyValueRow>
              <KeyValueRow label="版本">{health?.version ?? "—"}</KeyValueRow>
              <KeyValueRow label="后端响应">
                {health ? `${health.database.latency_ms ?? 0} ms` : "不可达"}
              </KeyValueRow>
            </div>
          </PanelSection>

          <PanelSection label="LLM">
            <div className="divide-y divide-border">
              <KeyValueRow label="配置来源">
                {health?.llm.source === "database" ? "数据库" : health?.llm.source === "env" ? "环境变量" : "未配置"}
              </KeyValueRow>
              <KeyValueRow label="当前模型">{health?.llm.model ?? "—"}</KeyValueRow>
              <KeyValueRow label="可用性">
                {!health?.llm.configured
                  ? "未配置"
                  : health.llm.ok === true
                    ? "已验证可用"
                    : health.llm.ok === false
                      ? "不可用"
                      : "未验证"}
              </KeyValueRow>
            </div>
            {health?.llm.ok === false ? (
              <p className="mt-1.5 rounded-md bg-destructive/12 px-2 py-1.5 text-meta leading-snug text-destructive">
                {health.llm.reason}
                {health.llm.hint ? <><br />建议：{health.llm.hint}</> : null}
              </p>
            ) : health?.llm.ok === null ? (
              <p className="mt-1.5 text-meta leading-snug text-muted-foreground">
                本次启动后还没有成功调用过模型；点上方 provider 的「测试」即可验证。
              </p>
            ) : null}
          </PanelSection>

          <PanelSection label="Embedding">
            <div className="divide-y divide-border">
              <KeyValueRow label="提供方">{health?.embedding.provider ?? "—"}</KeyValueRow>
              <KeyValueRow label="模型">{health?.embedding.model ?? "—"}</KeyValueRow>
              <KeyValueRow label="向量维度">{health?.embedding.dimension ?? "—"}</KeyValueRow>
            </div>
            <p className="mt-1.5 text-meta leading-snug text-muted-foreground">
              嵌入模型与维度来自环境变量，改动后需重建所有文档向量，且数据库向量维度必须一致。
            </p>
          </PanelSection>

          <PanelSection label="知识库">
            <div className="divide-y divide-border">
              <KeyValueRow label="文档数">{health?.documents ?? "—"}</KeyValueRow>
              <KeyValueRow label="切片数">{health?.chunks ?? "—"}</KeyValueRow>
            </div>
          </PanelSection>
        </PanelBody>
      </Panel>
    </div>
  )
}
