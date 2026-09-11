# NexusRAG 前端重设计方案

> 状态：待评审 · 范围：`ui/web/` 全部页面 + 少量后端新增接口
> 本文档基于两轮需求确认产出，所有决策点均可回退。

---

## 0. 决策摘要

| 维度 | 决定 |
| --- | --- |
| 信息架构 | 概览首页 + 6 个真实路由子页面 |
| 目标场景 | 给他人使用的产品界面 |
| 复杂度策略 | 分层：主流程默认简洁，内部过程按需展开 |
| 视觉风格 | 高密度工作台 |
| 新增能力 | 检索过程可视化 / 图谱可视化 / 评测消融面板 / 文档读取体验（四项全做） |
| 首页内容 | 知识库状态 + 系统健康 |
| 图谱方案 | 先补后端图谱 API，再做前端可视化 |

**唯一待定的假设：明暗主题。** 「高密度工作台」只界定了密度，未界定明暗，本方案默认**沿用现有深色底**（与工作台/IDE 观感一致，且能复用已有的 OKLCH token 与玻璃质感投资）。若要浅色，第 4 节 token 需要整体替换，工作量增加约 0.5 期。

---

## 1. 现状诊断

在动手前必须先解决四类既有问题，否则重构会把债务一起搬过去。

### 1.1 死代码

| 文件 | 情况 |
| --- | --- |
| `components/hero-section.tsx` | 定义了 `HeroSection`，全项目无引用 |
| `components/feature-bento.tsx` | 定义了 `FeatureBento`，全项目无引用 |
| `components/theme-toggle.tsx` | 定义了 `ThemeToggle`，全项目无引用 |

三者均为早期落地页残留，与当前"工具型工作台"定位不符，**直接删除**。

### 1.2 浅色主题是空壳

- `app/layout.tsx` 写死 `<html lang="en" className="dark">`，`themeColor: "#0d0f16"`。
- `app/globals.css` 中 `:root, .dark { ... }` 共用同一套 OKLCH 值 —— 即不存在浅色 token。
- `lang="en"` 与全中文界面不符。

处理：`lang` 改为 `zh-CN`；若确定只做深色，则移除 `.dark` 变体与 ThemeToggle 相关样式，避免留下第二套假主题。

### 1.3 假路由

`app/page.tsx` 仅挂载 `AppShell`，三个 Tab 由 `useState("chat")` 客户端切换：

- 无法深链（刷新回到 Chat）
- 无法前进/后退
- 状态与视图耦合，新页面无处安放

### 1.4 断掉的接口与缺失能力

- `chat-page.tsx` 声明 `onGoToDocuments` 参数，但 `AppShell` 渲染 `<ChatPage />` 时从未传入，回调永远为空。
- 助手回答用 `whitespace-pre-wrap` 纯文本渲染，**不解析 Markdown**，而 LLM 输出含 `[Source N]` 标记与列表结构，观感差。
- `/api/query` 为同步一次性返回，无流式输出、无阶段进度。
- 后端**没有图谱查询接口**（`graph.py` 仅 CLI：`build` / `stats` / `reset`）。
- 后端**没有评测接口**（`evaluation.py` 仅 CLI）。
- 后端**没有健康检查接口**（仅有 `/` 返回 `HealthResponse`，不反映 DB / LLM 真实状态）。

---

## 2. 设计目标与原则

**P1 — 复杂度分层。** 主界面只回答"问题与答案"；检索轨迹、图谱、评测收进可展开的检视层与独立页。默认视图不出现任何内部术语（RRF、锚点、跳数）。

**P2 — 默认即用，专家可达。** 新用户零配置即可提问；需要调优的人最多两次点击能触达 features 开关、top_k、filters、chunk 预览。

**P3 — 高密度但可呼吸。** 信息密度靠**排版层级与栅格**而非缩小字号（正文不低于 13px）；靠分栏而非滚动堆叠。

**P4 — 真实路由，可深链。** 每个页面有独立 URL，刷新/分享/回退均正确。

---

## 3. 信息架构与路由

### 3.1 路由表

| 路径 | 页面 | 说明 |
| --- | --- | --- |
| `/` | → 重定向 `/overview` | 默认落地 |
| `/overview` | 概览 | 知识库状态 + 系统健康 |
| `/chat` | 问答 | 对话 + 检索检视面板 |
| `/documents` | 文档 | 列表 / 详情 / 重切 / 原件预览 |
| `/graph` | 图谱 | 子图浏览 + 实体详情 |
| `/eval` | 评测 | 评测集 + 消融矩阵 |
| `/settings` | 设置 | LLM provider 管理 + 系统信息 |

采用 App Router 分组布局：`app/(workspace)/layout.tsx` 承载左侧导航与顶部状态条，六个 `page.tsx` 各占一个子路由，共享骨架。

### 3.2 全局骨架

```
┌────────────┬──────────────────────────────────────────────┐
│ 左侧导航   │ 顶部状态条：页面标题 · 后端健康 · 活跃模型 · 主动作 │
│ 184px      ├──────────────────────────────────────────────┤
│            │                                              │
│ 概览       │              页面内容区                       │
│ 问答       │        （全宽 · 由页面自行分栏）               │
│ 文档       │                                              │
│ 图谱       │                                              │
│ 评测       │                                              │
│ 设置       │                                              │
│ ─────────  │                                              │
│ 最近会话   │                                              │
└────────────┴──────────────────────────────────────────────┘
```

导航栏底部保留「最近会话」快捷区（数据来自现有 `/api/conversations`），使跨页回到上次对话只需一次点击。

### 3.3 组件树（目标态）

```
app/
├── layout.tsx                     lang=zh-CN、字体、全局样式
├── (workspace)/
│   ├── layout.tsx                 侧边导航 + 顶部状态条（客户端壳）
│   ├── overview/page.tsx
│   ├── chat/page.tsx
│   ├── documents/page.tsx
│   ├── graph/page.tsx
│   ├── eval/page.tsx
│   └── settings/page.tsx
components/
├── shell/            side-nav.tsx · top-status-bar.tsx · recent-conversations.tsx
├── overview/         metric-row.tsx · system-health.tsx · quick-actions.tsx
├── chat/             conversation-list.tsx · message-thread.tsx · composer.tsx
│                     feature-toggle.tsx · retrieval-inspector.tsx · source-chip.tsx
├── documents/        document-table.tsx · document-detail.tsx · chunk-list.tsx
│                     rechunk-panel.tsx · source-preview.tsx · figure-gallery.tsx
├── graph/            graph-canvas.tsx · entity-search.tsx · entity-detail.tsx · kind-filter.tsx
├── eval/             case-list.tsx · ablation-table.tsx · run-controls.tsx
├── settings/         provider-list.tsx · provider-form.tsx · system-info.tsx
└── ui/               沿用现有 shadcn 原子组件，按需补充
lib/
├── api.ts            扩充新端点（保持现有函数签名兼容）
├── hooks/            use-stats.ts · use-documents.ts · use-inspector.ts 等
└── constants.ts      保持 API_BASE
```

**删除：** `hero-section.tsx`、`feature-bento.tsx`、`theme-toggle.tsx`、`app-shell.tsx`（被 `(workspace)/layout.tsx` 取代）。

---

## 4. 设计系统（高密度工作台基线）

### 4.1 间距与栅格

- 间距基数 **4px**；组件内间隙用 `8 / 12 / 16px`，区块间距用 `1rem / 1.5rem`。
- 内容区**取消居中最大宽度**（现为 `max-w-[1100px]`），改为全宽 + 按页分栏。
- 分栏规格（固定三档，不随意发明）：
  - 双栏：`224px + 1fr`（列表 + 内容）
  - 三栏：`190px + 1fr + 248px`（会话 + 对话 + 检视）
  - 图谱页：`152px + 1fr + 176px`

### 4.2 字号阶梯（收敛为 7 档）

| 用途 | 字号 | 字重 |
| --- | --- | --- |
| 页面标题 | 16px | 500 |
| 卡片/区块标题 | 14px | 500 |
| 正文、消息 | 13px | 400 |
| 次要文本 | 12px | 400 |
| 元数据（标签、时间、计数） | 11px | 400 / 等宽 |
| 大数字（指标卡） | 20px | 500 |
| 超大数字（详情页统计） | 28px | 500 |

现存的 `text-[15px]`、`text-2xl`、`text-3xl` 等散落写法统一替换。

### 4.3 颜色

沿用现有 OKLCH 深色 token，补齐语义色用途约束：

- `--primary` **仅用于可交互态**（选中项、主按钮、链接），不再用于装饰。
- 新增语义：`--success`（后端正常、指标提升）、`--warning`（indexing）、`--danger`（failed）。
- 图表/可视化只用**两个色系**（中性 + 强调），避免彩虹图。

### 4.4 形状与描边

- 圆角：控件 `6px`、卡片 `8px`、容器 `12px`。
- 描边统一 `0.5px`，颜色 `--border`；hover 用 `--border-secondary`。
- **移除所有 `shadow-[...]` 硬编码阴影**（`chat-page.tsx` 与 `app-shell.tsx` 中共 3 处），改用描边 + 背景层级表达层次，符合工作台观感。

### 4.5 需要补充或改造的原子组件

| 组件 | 变更 |
| --- | --- |
| `button` | 增加 `size="xs"`（28px 高），供工具栏使用 |
| `badge` | 增加语义变体（success / warning / danger），替换文档页手写样式 |
| 新增 `panel` | 统一的可折叠侧面板容器（用于检视面板） |
| 新增 `data-table` | 固定列宽、可排序的紧凑表格，供文档/评测复用 |
| 新增 `metric` | 指标卡（11px 标签 + 20px 数值） |
| 新增 `code-block` / `markdown` | 渲染助手回答的 Markdown 与 `[Source N]` 标记 |
| `progress` | 已存在，用于 indexing 进度 |

---

## 5. 页面规格

### 5.1 概览 `/overview`

**目标**：一目了然知道"库里有什么、系统是否健康"，并快速进入下一步动作。

**布局**：单栏，自上而下三段。

1. **指标行** — 4 张指标卡：文档数 / 切片数 / 向量维度 / 存储占用（数据源 `GET /api/stats`，已有）。
2. **系统健康** — 键值行：后端响应耗时、活跃 LLM 模型、嵌入模型与维度、图谱规模、最近入库时间。
3. **快捷入口** — 继续最近会话 / 上传并入库 / 构建图谱 / 运行消融评测。

**状态**：后端不可达时顶部状态条转 danger，指标行降级为占位骨架；图谱未构建时健康区显示"未构建"并给出入口。

### 5.2 问答 `/chat`

**目标**：对外是干净的问答界面，对内可随时展开证据链。

**布局**：三栏 `190px + 1fr + 248px`。

- **左：会话列表** — 复用现有逻辑（搜索、选中态、消息数、相对时间）。新增"新建会话"显式入口（当前靠清空隐式创建）。
- **中：对话主区**
  - 用户消息右对齐气泡；助手消息为卡片，含正文 + 证据 chips + 元数据行。
  - 助手正文**改为 Markdown 渲染**，`[Source N]` 渲染为可点击的上标引用，点击滚动到对应证据 chip。
  - 底部工具行：左为「检索特性」开关（浮层收入到检视面板内，主区只留一个入口），右为清空。
  - 输入区：多行自适应，`Enter` 发送、`Shift+Enter` 换行，发送中禁用并显示阶段文案（"规划检索… / 检索中… / 生成中…"）。
- **右：检索检视面板**（可折叠，默认收起）
  - 规划输出：子问题 / 退步问题 / HyDE 段的条数与原文
  - 通道命中：路由 / 关键词 / 向量 / HyDE / 图谱 各自的候选数与命中块数（横向条形）
  - 融合与重排：RRF 去重前后数量、rerank 策略与 top-k 变化
  - 耗时分解：规划 / 检索 / 生成三段
  - 证据列表：每条来源可展开原文，支持按分数排序

**状态**：空库时给出引导（当前已有）；检索无结果、LLM 未配置、provider 测试失败均需明确的空/错状态。

**依赖**：需要后端 `/api/query` 支持 `debug` 模式返回 trace（见 6.3）。

### 5.3 文档 `/documents`

**目标**：管理语料，并能亲眼验证切片质量。

**布局**：列表态为单栏表格；进入详情后为双栏 `1fr + 384px`。

- **列表**：紧凑表格，列为 文件名 / 切片数 / 状态 / 大小 / 入库时间 / 操作。支持按状态与类型筛选、按时间排序。上传支持拖拽到页面任意位置。
- **详情（左）**：统计行（切片数 / chunk_size / overlap）、切片列表、重切配置与预览对比。切片列表支持关键词高亮与"查看原文对应位置"。
- **详情（右，新增）**：原件预览面板
  - PDF：按页渲染，命中切片高亮其页码位置
  - Markdown / TXT：原文按段落渲染，切片边界用底色标出
  - 内嵌图片：以缩略图墙呈现（数据源 `GET /api/query` 返回的 figures 同源逻辑，或新增按页取图接口）

**状态**：indexing 时进度与自动轮询（沿用现有 1.5s 轮询）；failed 时展示 `error` 字段并提供重试。

### 5.4 图谱 `/graph`

**目标**：让 GraphRAG 的黑盒可被检视 —— 实体是谁、关系有多强、证据在哪。

**布局**：三栏 `152px + 1fr + 176px`。

- **左：筛选** — 实体搜索框、按 kind 过滤（concept / product / metric / method / person / org / other，与 `graph.py` 的 `ENTITY_KINDS` 对齐）、扩展跳数（1 / 2，与 `HOPS=2` 对齐）、图谱统计。
- **中：画布** — 力导向子图。节点大小映射 `mentions`，边粗细映射 `weight`，颜色区分 kind。支持拖拽、缩放、点击选节点、双击展开下一跳。
- **右：实体详情** — 名称、kind、`description`、被提及次数、出/入边列表（标注 weight）、证据切片（`relations.evidence` → chunk，可跳转到文档页对应位置）。

**技术选型**：默认**不引入重型图库**，用 `d3-force` 做布局计算 + 自绘 SVG 渲染（约 30KB，可控、可定制）。若后续需要框选、小地图等复杂交互，再评估 cytoscape。

**依赖**：需要后端图谱查询 API（见 6.1）。

### 5.5 评测 `/eval`

**目标**：把 `evaluation.py` 的消融矩阵搬到界面上，让"哪个特性有用"可量化、可复现。

**布局**：双栏 `288px + 1fr`。

- **左：评测集** — 评测例列表（问题 + 期望引用），支持新增（对应现有 `add` 命令）与 `seed-multihop` 一键播种。
- **右：结果** — 运行控制（K 值、配置矩阵勾选、运行按钮）+ 结果表（配置 / Hit@K / MRR / Δ） + 对比条形图（仅两色系）。
- 运行中显示逐配置进度，避免长时间无反馈。

**依赖**：需要后端评测 API（见 6.2）。

### 5.6 设置 `/settings`

**目标**：把现有 `llm-settings.tsx` 归位，并补齐系统信息。

- **LLM Providers**：沿用现有增删改查、激活、连通性测试（`POST /api/llm/providers/{id}/test`）。改为紧凑表格 + 行内编辑，替换现有的大表单卡片。
- **嵌入配置**：只读展示 `EMBEDDING_PROVIDER` / `MODEL` / `DIMENSION`（来源 `/api/stats` 与新增 health）。
- **系统信息**：版本、数据库连接状态、向量维度一致性校验结果。

---

## 6. 后端需新增的接口

以下均为**新增**，不改动现有契约。

### 6.1 图谱查询（必需）

```
GET  /api/graph/stats
     → { entities, relations, links, orphan_entities, kinds: {concept: 148, ...} }
     （复用现有 graph_stats()，补 kinds 分布）

GET  /api/graph/search?q=&kind=&limit=20
     → [{ entity_id, name, kind, description, mentions }]

GET  /api/graph/entities/{entity_id}
     → { entity: {...}, out_edges: [{rel, norm_rel, weight, target}],
         in_edges: [...], evidence_chunks: [{chunk_id, doc_name, chunk_index, page, text}] }

GET  /api/graph/subgraph?entity_id=&hops=2&limit=100
     → { nodes: [{entity_id, name, kind, mentions, hop}],
         edges: [{src, dst, norm_rel, rel, weight}] }
     （复用 graph_chunks 的递归 CTE 思路，但返回图结构而非切片）
```

实现落点：`src/storage/database.py` 新增查询函数，`src/api/routes.py` 新增路由，`src/api/schemas.py` 新增模型。`graph.py` 保持 CLI 不变。

### 6.2 评测（必需）

```
GET  /api/eval/cases                → 评测例列表
POST /api/eval/cases                → 新增评测例
GET  /api/eval/run?k=5&configs=...  → 同步返回消融结果矩阵
```

注意：`run_ablation` 会逐组跑全量评测例，耗时可达分钟级。建议 **POST + 轮询任务状态**，或先限制配置数与评测例数并加超时。

### 6.3 问答 trace（检视面板依赖）

`POST /api/query` 新增可选字段 `debug: bool`（默认 false）。

- `debug=false`：行为与现在完全一致，**零额外开销**。
- `debug=true`：额外返回 `trace` 字段：

```
trace: {
  plan:   { subs: [...], step_back: "...", hyde: "..." },
  channels: [ { name: "routing", candidates: 50, docs: [...] },
              { name: "keywords", candidates: 18 },
              { name: "vector", candidates: 50 },
              { name: "hyde", candidates: 50 },
              { name: "graph", candidates: 25 } ],
  fusion: { merged_before: 128, merged_after: 25, rerank: "rrf", top_k: 5 },
  timings: { plan_ms: 1200, retrieve_ms: 400, generate_ms: 2100 }
}
```

实现要点：`multi_query_search` 需支持返回 trace。**不要改变其现有返回类型**，新增 `multi_query_search_with_trace()` 或在末尾追加可选 `debug` 出参，保持 `evaluation.py` 与现有调用方不受影响。

### 6.4 健康检查（建议）

```
GET /api/health
     → { status, db: { ok, latency_ms }, llm: { configured, model }, embedding: { provider, model, dimension } }
```

### 6.5 流式输出（可选，建议后置）

`POST /api/query` 的 SSE 版本，推送阶段事件与增量 token。收益明显（长回答等待感下降），但会牵动 `routes.py` 与前端消息渲染，建议放在 P5 之后单独评估。

---

## 7. 数据获取与状态策略

- **不引入 SWR / React Query / Redux**，继续 `lib/api.ts` 手写 fetch，按页封装轻量 hooks（`lib/hooks/`），避免为一个中型前端引入抽象层。
- **状态就近**：页面级数据（文档列表、图谱子图、评测结果）由页面自己持有。
- **跨页共享**：仅"活跃 LLM provider"与"库统计"两项提升到 `(workspace)/layout.tsx`，由顶部状态条每 8s 轮询一次；不做全局 store。
- **轮询约定**：只在"有进行中任务"时轮询（沿用现有 `status === "indexing"` 触发思路），空闲时停表。
- **URL 即状态**：筛选条件、选中实体、选中会话尽量写入 query string，保证可分享与可回退。

---

## 8. 实施顺序与验收标准

| 期 | 内容 | 验收标准 |
| --- | --- | --- |
| **P0** 基座 | 路由拆分、`(workspace)` 布局、删除死组件、`lang=zh-CN`、设计 token 收敛、补齐原子组件 | 六个路由可直达与刷新；导航态正确；无遗留 `max-w-[1100px]` 与硬编码阴影 |
| **P1** 概览 | 指标行、系统健康、快捷入口；`GET /api/health` | 后端断开时降级不白屏；数据与 `/api/stats` 一致 |
| **P2** 问答 | 三栏布局、Markdown 渲染、`[Source N]` 引用跳转、检视面板；`/api/query` 支持 debug | 默认视图无内部术语；展开后可见规划/通道/融合/耗时四段；`debug=false` 时响应体与现在逐字节一致 |
| **P3** 文档 | 紧凑表格、详情双栏、原件预览、chunk 与原文对照高亮、图片墙 | PDF 与 MD 均能定位到切片对应位置；rechunk 预览对比正确 |
| **P4** 图谱 | 后端四个图谱端点、画布、实体详情、导航跳转 | 能从一个实体两跳展开；节点/边可追溯到证据切片 |
| **P5** 评测 | 后端评测端点、评测集管理、消融结果表与对比图 | 结果与 `python -m src.evaluation` 输出一致；运行有进度反馈 |

P0 是硬前置；P1–P5 之间无强依赖，可按价值调整顺序。若只想先看效果，建议 **P0 → P2 → P1**（问答是主路径，收益最直观）。

---

## 9. 待确认事项（含实施后的状态）

| # | 事项 | 状态 |
| --- | --- | --- |
| 1 | **明暗主题** | 仍待确认。当前按深色实现；改浅色需整体替换第 4 节 token |
| 2 | **前端新依赖**（图谱可视化） | 已决定「不引入」，改用无依赖径向布局，见附录 A.1 |
| 3 | **图谱规模上限** | 已定为单次 150 节点、最多 3 跳，服务端截断（前端暂未对截断做提示） |
| 4 | **评测运行时长** | 暂按同步实现；评测集变大后需改后台任务 + 轮询 |
| 5 | **流式输出** | 未纳入本轮，建议后续单独评估 |
| 6 | **`docs/*` 被 gitignore** | 新增待办：本文档当前不会进版本库，需决定是否调整规则 |

---

## 附：主要文件改动清单

**删除**
- `ui/web/components/hero-section.tsx`
- `ui/web/components/feature-bento.tsx`
- `ui/web/components/theme-toggle.tsx`
- `ui/web/components/app-shell.tsx`（由 `(workspace)/layout.tsx` 取代）
- `ui/web/app/page.tsx`（改为重定向）

**重写**
- `ui/web/components/chat-page.tsx` → 拆为 `components/chat/*` 六个组件
- `ui/web/components/document-list.tsx` → 拆为 `components/documents/*`
- `ui/web/components/document-viewer.tsx` → 拆为 `components/documents/*`
- `ui/web/components/llm-settings.tsx` → 拆为 `components/settings/*`
- `ui/web/app/globals.css` → 收敛 token 与字号阶梯
- `ui/web/app/layout.tsx` → `lang=zh-CN`

**新增**
- `ui/web/app/(workspace)/{layout.tsx,overview,chat,documents,graph,eval,settings}`
- `ui/web/components/{shell,overview,graph,eval}/**`
- `ui/web/lib/hooks/**`
- `src/api/routes.py` 图谱 / 评测 / health 端点
- `src/api/schemas.py` 对应模型
- `src/storage/database.py` 图谱子图查询函数

---

## 附录 A：实施记录（P0–P5 已落地）

本节记录实际实现与上文规划的差异，以及验证结果。**规划文档保留原文，差异在此说明。**

### A.1 与规划不一致的地方

| 项 | 规划 | 实际实现 | 原因 |
| --- | --- | --- | --- |
| 图谱布局 | `d3-force` 力导向 | 无依赖的**确定性径向布局**（锚点居中，hop=1/2 分环均布） | 项目未引入 `d3-force`，且力导向每次渲染位置漂移，对"查看某实体的两跳邻居"反而不如固定布局稳定 |
| 原件预览 | 未提及额外接口 | 新增 `GET /api/documents/{doc_id}/file` | 后端原本不回传源文件，PDF 无法预览。PDF 用 iframe 拼接 `#page=N` 定位；MD/TXT 拉取原文并对切片做前缀匹配高亮 |
| 文档列表字段 | 计划显示"大小/入库时间" | 仅显示切片数/状态/入库时间 | 后端无文件大小字段；为 `DocInfo` 增补了 `created_at` / `updated_at`（可选字段，向后兼容） |
| Markdown 渲染 | 未指定 | 自写轻量渲染器 `components/ui/markdown.tsx` | 避免为一个受限语法集引入 `react-markdown` 依赖链；顺带把 `[Source N]` 渲染成可跳转的引用标记 |
| 评测执行 | 待确认同步/异步 | **同步**执行（`POST /api/eval/run`） | 默认 6 例 × 4 组配置量级可控；评测集变大后需改后台任务 |
| 通道展示口径 | 规划的"候选数" | 展示**通道返回块数** | `two_stage_search` 内部已完成关键词/路由/向量的融合，拿不到分通道的原始候选数；把内部拆开会让检索路径变复杂，得不偿失 |
| 明暗主题 | 待确认，暂按深色 | 仍为深色 | 未获得明确结论前不引入第二套 token |
| 文档页输入框 | 未指定 | 手写 `<input>` 而非 `ui/input.tsx` | 工作台的密度基线是 13px/28px，`Input` 组件是 14px/32px，替换会破坏密度基线。`ui/input.tsx` 因此暂时无引用 |

### A.2 计划外的改动

- **`DocInfo` 增补时间字段**：`created_at` / `updated_at`（`str | None`，默认 None），供文档列表显示入库时间。既有调用方不受影响。
- **`evaluation.load_cases()` 增补字段**：新增 `expected_refs`（原始串）与 `reference_answer`，供评测接口回显。`run_ablation` 只读 `question` / `expected`，行为不变。
- **规避 `react-hooks/set-state-in-effect`**：该规则会把"在 effect 中调用异步加载器"误判为同步 setState。按仓库既有约定（原 `document-list.tsx` 即如此），首屏加载统一延后一拍执行；源头重置则改用组件 `key` 触发重挂载，而非在 effect 里同步重置。
- **保留但暂无引用**：`ui/{alert,avatar,card,progress,separator,skeleton,tabs}.tsx`。它们是组件库的常规储备，不视为死代码（与已删除的 `hero-section` / `feature-bento` / `theme-toggle` 性质不同）。

### A.3 验证结果

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 前端类型检查 | `tsc --noEmit` | 0 错误 |
| 前端 Lint | `eslint .` | 0 问题 |
| 前端生产构建 | `next build` | 成功，6 个页面路由 + `/` 重定向均已生成 |
| 后端冒烟 | `python .workbuddy/smoke_backend.py` | 33 项全通过 |
| 后端接口数 | OpenAPI schema | 16 → 25 条 |

后端冒烟脚本用桩件替换 `psycopg` / `dotenv` / `jieba`，因此**不需要数据库与外部服务**即可验证：接口注册、`/api/health` 正常与降级两条路径、图谱三类查询的响应装配、评测结果字段映射与空集保护、以及 `multi_query_search` 的 debug 分支（含"debug=false 时返回类型与融合结果不变"的契约回归）。运行方式：

```bash
/Users/Apple/.workbuddy/binaries/python/envs/default/bin/python .workbuddy/smoke_backend.py
```

### A.4 尚未验证的部分

以下需要真实数据库与 LLM 才能确认，本轮未覆盖：

- 图谱子图 SQL（递归 CTE 的 `min(hop)` 聚合与 `ANY(uuid[])` 边过滤）未在真实 pgvector 上跑过。
- `/api/eval/run` 与 `python -m src.evaluation` 的结果一致性未做交叉核对。
- 检视面板的 trace 数值在真实检索链路下的合理性（此处仅验证了装配逻辑与字段口径）。
- 前端各页面在浏览器中的实际渲染与交互（仅通过构建与类型检查，未做浏览器验证）。

### A.5 环境注意事项

- 本机的 `npm install` 会被运行环境策略拦截（`CODEBUDDY_BROKER_DENY`，`mkdir` 阶段失败）。本次通过「`npm install --package-lock-only` 生成锁文件 + 直接解包 tarball」的方式装配了 `node_modules`，该目录本身被 `.gitignore` 忽略，属一次性操作，不影响仓库。
- 根 `.gitignore` 含 `docs/*`，**本文档不会被提交**。若希望纳入版本管理，需调整该规则或改放到未被忽略的目录。

---

## 附录 B：后续修复（提交 `3b74d50`，已并入 main）

首次交付后对检索特性做了一次审计，发现并修复了三类问题。

### B.1 信息表达不准确（正确性问题，优先修）

- **`trace.active` 名不副实**：它被赋值为「请求的特性集」，而非「真正生效的」。后果具体——LLM 未配置时 `plan_question` 返回空计划，`decompose` / `stepback` / `hyde` 实际静默空转，面板却仍列为「生效」。
  现在拆为 `applied`（真正生效）与 `skipped`（空转 + 可读原因，如「LLM 未配置，检索规划未执行」「该问题无需拆分」）。
- **`routed_docs` 跨查询累加**：一条问题被拆成多个子查询时，每条各自路由，累加后会把同一批文档报成「命中 8 篇」。改为按 `doc_id` 去重。

### B.2 补齐后端已有、界面未暴露的能力

| 能力 | 修复方式 |
| --- | --- |
| `top_k` | 原本硬编码为 5；现可在「检索设置」浮层调（1–50） |
| `filters` 元数据过滤 | 原本永远传 `undefined`；现支持键值对编辑，值按 `true/false`→布尔、纯数字→数值推断类型 |
| `RERANK_STRATEGY` | 原本只能靠环境变量；`rerank()` 新增可选 `strategy` 参数，`QueryRequest` 增加 `rerank_strategy` 支持请求级覆盖 |

三者在问答页的「检索设置」浮层里，持久化于 localStorage；主输入区依然只保留一个入口，符合「复杂度按需展开」的定位。

### B.3 通道口径与语义澄清

- 新增通道级候选块数（`routing` / `keywords` / `vector` / `hyde` / `graph`）与路由判定块（命中文档数、最高分、是否兜底、阈值），**部分解决了原 A.1 中「三个通道被内部融合、无法分通道观测」的限制**——现在能看到各通道融合前的候选量。
- `fusion.channels` 是「参与融合的结果组数」，与「通道命中」不是同一概念，UI 已分别标注为「融合输入组数」与「通道命中（融合前候选）」。
- 设置面板明确写出：**7 个特性全关不等于不检索**，向量通道始终会跑，实为纯向量基线。

### B.4 本次验证

| 项 | 结果 |
| --- | --- |
| `tsc --noEmit` / `eslint .` | 0 错误 / 0 问题 |
| `next build` | 通过 |
| 后端冒烟 | 41/41（新增「空转必须进 skipped」「trace 能通过 QueryTrace 校验」「请求级 rerank 策略被采纳」） |
| 真实库 + 真模型端到端 | `/api/query?debug=true` → HTTP 200，`applied=[routing,keywords,hyde,graph,rerank]`，`skipped=[decompose, stepback]`（原因正确），`params` 透出 `top_k=3` / `rerank_strategy=rrf` |
| 主仓库前端 | 6 路由全 200，`/chat` 渲染出「检索设置」 |

**仍未验证**：`filters` 的端到端效果（需要构造带特定元数据的查询并确认结果确实被过滤）未做实测；浏览器内的实际交互（浮层展开、localStorage 持久化）仍需人工确认。

**观测到的性能事实**：一次完整问答约 33s，其中 `retrieve_ms` 占 28s——**主要来自本地 bge-m3 的冷启动加载**（进程首次 encode 时载入模型），不是检索逻辑本身的开销。进程预热后应显著下降，但尚未实测预热后的数值。


---

## 附录 C：浅色主题与图谱三维化（实施于 2026-09-11，提交 `260f5b1`）

### C.1 起因

用户反馈两点：

1. **暗色界面不舒服** —— 这条把附录 A 里长期挂起的「明暗主题未确认」定了下来。
2. **图谱无法左右晃动，不真实** —— 确认属实：原实现是**静态 SVG 径向布局**，只有点击选中与双击换中心，**没有任何旋转、缩放、拖拽**。

经询问确认方向：浅色默认 + 跟随系统、冷白分层、真 3D（three.js）、四项交互全要（拖拽旋转含惯性 / 自动缓慢自转 / 滚轮缩放平移 / 点击高亮邻居与双击换中心）。

### C.2 主题：从硬编码深色改为浅色优先

- `globals.css`：浅色成为默认（页面底浅灰、卡片纯白，**层次靠明度而非描边**），深色整体收进 `@media (prefers-color-scheme: dark)`。
- `layout.tsx`：移除写死的 `className="dark"`；`themeColor` 改为声明明暗两个值。
- 移除了基于 `.dark` 类的 custom variant。这带来一个有利的副作用：`dark:` 工具类回落到 Tailwind v4 的默认行为（媒体查询），**正好就是"跟随系统"**，无需额外逻辑。
- 审计确认组件层没有硬编码深色假设（`text-white` / `bg-white/*` / 内联 hex 均已排查，仅剩 3D 场景内的材质色与 tooltip 阴影，两者明暗皆可用）。

### C.3 图谱：静态 SVG → WebGL

| 维度 | 原实现 | 现实现 |
| --- | --- | --- |
| 渲染 | 静态 SVG | three.js + @react-three/fiber + drei |
| 布局 | 二维径向分环 | 确定性球壳（锚点近原点，hop 1/2 按黄金角分壳） |
| 旋转 | 无 | OrbitControls 拖拽旋转，带阻尼惯性 |
| 缩放平移 | 无 | 滚轮缩放 + 平移 |
| 空闲动效 | 无 | 缓慢自转 |
| 选中反馈 | 变色 | 高亮邻居 + 淡化其余 + 选中球轻微脉动 |
| 节点 | 圆 + 文字 | 受光球体，半径由 mention 数决定，带 hover tooltip |

布局保持**确定性**：同一子图永远得到同一组坐标，只有相机在动——这样"点开实体看两跳邻居"时结构是可预期的，不会每次刷新都变。WebGL 无法服务端渲染，故用 `next/dynamic` + `ssr: false` 加载，加载期显示占位。

### C.4 关键坑：R3F v8 与 React 19 不兼容

第一版按常见写法装了 fiber v8，`tsc` 立刻报出 20 个错误：`Property 'mesh' does not exist on type 'JSX.IntrinsicElements'`、`'group'`、`'sphereGeometry'`、`'primitive'` …… 一度误判为依赖解包不全。

真实原因：R3F v8 通过 `declare global { namespace JSX { interface IntrinsicElements extends ThreeElements {} } }` 做类型增强，而 **React 19 已把 JSX 命名空间从全局挪到了 `React.JSX`**，于是这个全局增强完全不生效。

**解法：升到 fiber v9 + drei v10**（fiber 9.7.0 / drei 10.7.8，其 peer 要求 `react-dom >=19 <19.3`，项目 19.2.8 正好匹配）。

### C.5 另一个坑：解包脚本的路径写死

`.workbuddy/unpack_deps.py` 原本把 `ROOT` 写死成 WorkBuddy 工作区。给**主仓库**装配依赖时它一直在检查并装入另一个目录，表现为「统计: skip 510，全部跳过」，白跑一轮。已改为支持 `--root <目录>` 参数，给其他副本装依赖时必须显式传入。

### C.6 本次验证

| 项 | 结果 |
| --- | --- |
| `tsc --noEmit` | 0 错误 |
| `eslint .` | 0 问题 |
| `next build` | 通过，9 个路由 |
| 主仓库端到端 | 6 路由全 200 |
| `<html>` 标签 | `<html lang="zh-CN">`，已无 `dark` 类 |
| CSS 产物 | 浅色 `--background: #f5f6f8`、深色 `--background: #080b11`、`color-scheme: light dark` 三组均在 |
| three 打包 | 已进入客户端 bundle（904K chunk 含 `WebGLRenderer`） |
| 三副本同步 | main / ui / workbuddy 均到 `260f5b1` |

### C.7 仍未验证

- **WebGL 的实际渲染效果与交互手感**（拖拽旋转、滚轮缩放、自转速度、节点命中判定）需在浏览器中确认，本轮只做到构建与 HTTP 层面。
- 深色分支（系统设为深色时的表现）同样只验证了 CSS 变量存在，未做视觉确认。
- `main` 目前领先 `origin/main` 6 个提交，仍未推送。
