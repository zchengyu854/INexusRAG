/**
 * 检索特性开关的元数据与状态工具。
 *
 * 开关名必须与后端 schemas.FeatureName、retrieval.ALL_FEATURES 三处同步。
 * 面板界面见同目录的 retrieval-settings.tsx。
 */

export interface FeatureOption {
  key: string
  label: string
  desc: string
}

export const FEATURE_OPTIONS: FeatureOption[] = [
  { key: "routing", label: "路由", desc: "先定位相关文档，缩小检索范围" },
  { key: "keywords", label: "关键词", desc: "精确匹配专有名词、代号、数字" },
  { key: "rewrite", label: "改写", desc: "归一化查询：去疑问词、规范法条编号（确定性，无需大模型）" },
  { key: "decompose", label: "分解", desc: "将复杂问题拆成子问题分别检索" },
  { key: "stepback", label: "退步", desc: "先把细节问题抽象为概念问题" },
  { key: "hyde", label: "假想文档", desc: "生成假想答案段落辅助语义检索" },
  { key: "rerank", label: "重排", desc: "对候选结果精细排序（较慢）" },
  { key: "graph", label: "图谱", desc: "图谱多跳检索，串联分散线索" },
]

/**
 * 基础检索装置：默认开启——开销小、无额外依赖，属于「每次检索都该有」的兜底能力
 * （与后端 retrieval._DEFAULT_FEATURES 一致）。
 */
export const CORE_FEATURE_KEYS = ["routing", "keywords", "rewrite", "decompose", "stepback", "hyde"]

/** 进阶检索装置：默认关闭——较慢或需额外资源（重排模型下载 / 图谱构建），按需单独开启。 */
export const ADVANCED_FEATURE_KEYS = ["rerank", "graph"]

/** 默认集与后端 retrieval._DEFAULT_FEATURES 一致：进阶装置默认关闭。 */
export const DEFAULT_FEATURES = CORE_FEATURE_KEYS

/** 按分组键取选项元数据（保持传入顺序）。 */
export function featureOptionsOf(keys: string[]): FeatureOption[] {
  const byKey = new Map(FEATURE_OPTIONS.map((option) => [option.key, option]))
  return keys.map((key) => byKey.get(key)).filter((option): option is FeatureOption => Boolean(option))
}

export function initialFeatureState(features?: string[] | null): Record<string, boolean> {
  const active = features ?? DEFAULT_FEATURES
  return Object.fromEntries(FEATURE_OPTIONS.map((option) => [option.key, active.includes(option.key)]))
}

export function selectedFeatures(checked: Record<string, boolean>): string[] {
  return FEATURE_OPTIONS.filter((option) => checked[option.key]).map((option) => option.key)
}

export function featureLabels(keys: string[] | null | undefined): string | null {
  if (!keys || keys.length === 0) return null
  return keys.map((key) => FEATURE_OPTIONS.find((option) => option.key === key)?.label ?? key).join(" · ")
}

export function featureLabel(key: string): string {
  return FEATURE_OPTIONS.find((option) => option.key === key)?.label ?? key
}
