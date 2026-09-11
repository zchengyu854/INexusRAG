# NexusRAG Agentic RAG 设计方案

> 定位：在既有「传统 RAG（混合检索）」与「Graph RAG（P1 局部图谱）」两条范式之外，
> 增加第三条范式 **Agentic RAG**——由 Agent 自主决定检索次数、检索策略与工具。
> 目标不是替换现有管线，而是把它「降维」成 Agent 手里的工具，新增一层可控的编排与反馈循环。
>
> 状态：设计阶段（未实现）。本文档与主仓库 `docs/frontend-redesign.md` 同级，属方案文档。
>
> 注：本工作树（084d2bb）的 `.gitignore` 第 36 行仍有 `docs/*`，会忽略本文件——
> 它是被「Data (may contain sensitive test/sample data)」那一组误带进来的。
> **main 分支上该行已移除**（`docs/ROADMAP.md`、`docs/frontend-redesign.md` 均已跟踪），
> 因此合入 main 后本文件可正常入库，无需再改 `.gitignore`。

---

## 1. 背景：为什么要做第三条范式

### 1.1 三种范式核心差异

| 维度 | 传统 RAG | Graph RAG（§GraphRAG P1） | Agentic RAG（本节） |
| --- | --- | --- | --- |
| 检索次数 | 单次 | 单次/多次（预定） | 动态多次（自主决定） |
| 检索策略 | 固定（向量相似度） | 固定（图遍历+社区检测） | 动态（Agent 自主选择） |
| 反馈机制 | 无 | 有限 | 完整的反思-改写循环 |
| 工具选择 | 无 | 受限 | 自主多工具选择 |
| 适用问题 | 简单事实型 | 多跳关系推理 | 复杂多步、多源整合 |
| 延迟/成本 | 低 | 中 | 较高 |

### 1.2 现状盘点（基于当前代码）

NexusRAG **已经具备**前两条范式的全部构件，且检索是「多通道 + 可开关」的：

- `src/retrieval.py::multi_query_search` —— 检索总入口，按 `features` 组装通道：
  `routing / keywords / decompose / stepback / hyde / rerank / graph` 七开关；
  `_DEFAULT_FEATURES` 只开前五个（`rerank` / `graph` 默认关）。
- `src/retrieval.py::two_stage_search(query_embedding, top_k, terms, filters, use_routing, stats)`
  —— 路由命中目标文档 + 关键词通道 + 文档内向量，RRF 融合（**入参是 embedding + terms，不是 query 字符串**）。
- `src/retrieval.py::plan_question` —— **一次** LLM function-calling 规划（子问题 / 退步 / HyDE）。
- `src/graph.py::graph_channel(question_vector, top_k, filters)` —— 图谱通道：
  问题向量 → 实体锚点 → `graph_subgraph` ≤2 跳 → 回落到切片（**跳数写死，非入参**）。
- `src/rerank.py::rerank(query, candidates, top_k, strategy)` —— 四策略（rrf / cross / llm / colbert）。
- `src/llm/client.py::LLMClient` —— `generate(question, sources, history)` 接地回答 +
  `tool_call(prompt, tool, history)` 强制单工具 function calling（`tool_choice` 用对象形式，兼容部分网关）。
- `src/evaluation.py` —— `eval_cases` 评测集 + `retrieval_metrics`（Hit@K / MRR）+ `run_ablation`。
- 前端 `components/chat/retrieval-settings.tsx` + `retrieval-inspector.tsx` —— 特性开关与检索过程检视面板。

**缺口**：现有 `plan_question` 是「**一次**规划后固定执行」——规划完就按预定通道跑一遍，**没有观测结果、没有反思、没有基于中间结果的二次改写**。这本质上仍是「预定多次」而非「自主多次」。Graph RAG 的「有限反馈」也止步于图遍历本身。

Agentic RAG 要补的正是这一层：**执行 → 观测 → 反思 → 改写 → 再执行** 的闭环。

### 1.3 一个必须先说清楚的判断

> **不是所有问题都值得走 Agentic。** 简单事实题走传统 RAG 更快更稳；
> 多跳关系题 Graph RAG 已经够用。Agentic RAG 的价值只在「复杂多步、多源整合」——
> 需要跨文档、多轮收集、边查边判断的问题。因此它必须是**显式开启**的第三条路径，
> 默认关闭，绝不让所有请求都背上 3~5 倍的延迟与成本。

---

## 2. 设计目标与原则

| 目标 | 说明 |
| --- | --- |
| 新增范式而不破坏现有 | 传统 RAG / Graph RAG 的代码路径与行为**零改动**；Agentic 作为独立编排层叠加 |
| 复用而非重写 | 把 `two_stage_search` / `graph_channel` / `rerank` 直接包装成 Agent 工具，不复制检索逻辑 |
| 可控 | 有硬预算（步数 / LLM 调用数 / 时间），超限强制收敛，绝不无限循环 |
| 可观测 | 每一步的 thought / tool / args / observation 都进 trace，前端可视化 |
| 失败静默降级 | LLM 不可用、工具报错、预算耗尽 → 退回现有 `multi_query_search` 单轮管线，**绝不整体失败** |
| 可评估 | 纳入现有消融矩阵，与另两条范式同口径对比（Hit@K / MRR + 答案级指标） |

**工程约定对齐**（沿用仓库既有铁律）：

- 依赖严格单向：`agent` 只惰性（函数体内）import `retrieval / graph / rerank / llm`，不反向被引。
- 存储层之外不写 SQL；Agent trace 落库也走 `storage/database.py`。
- 特性/模式开关三处同步：`schemas` ↔ 后端常量 ↔ 前端选项，缺一不可。
- 新增 LLM 环节遵循「失败静默降级」。

---

## 3. 总体架构

Agentic RAG 不改变「检索→融合→生成」的底层，而是**在其上加一层 Agent 编排器**，把原有能力暴露为工具。

```
                        ┌─────────────────────────────────────────────┐
                        │              Agent Orchestrator              │
                        │   (src/agent.py::run_agent)                  │
                        └─────────────────────────────────────────────┘
                                          │
        ┌──────────────┬──────────────────┼──────────────────┬──────────────┐
        ▼              ▼                  ▼                  ▼              ▼
   ┌─────────┐   ┌──────────┐      ┌────────────┐     ┌──────────┐   ┌───────────┐
   │ Planner │→  │  Select  │  →   │  Execute   │  →  │ Observe  │→  │  Reflect  │
   │ 规划    │   │ 选工具   │      │ 调工具     │     │ 观测结果 │   │ 反思      │
   └─────────┘   └──────────┘      └────────────┘     └──────────┘   └───────────┘
                                          ▲                                  │
                                          │        不够/需改写：回到 Select ──┘
                                          │
                                          ▼
                                   ┌──────────────┐
                                   │  Synthesize  │  证据足够 → 生成接地回答（带引用）
                                   └──────────────┘

   工具层（复用现有实现）:
     search_knowledge ─→ two_stage_search()          # 向量 + 关键词 + 路由，RRF
     search_graph     ─→ graph_channel()             # 实体锚点 ≤2 跳
     route_documents  ─→ search_doc_index()          # 先定位文档
     read_chunk       ─→ database.get_chunk()        # 精读某个切片原文
     rerank           ─→ rerank()                    # 对候选精排
     answer           ─→ 终止：带证据生成回答
```

**循环的本质（ReAct 风格）**：`Thought → Action(tool, args) → Observation → ... → Answer`。
与传统 RAG 的区别在于 **`max_steps` 由 Agent 自己用**（在预算内），而不是预先写死跑几路。

---

## 4. 核心流程（伪代码）

```python
# src/agent.py
def run_agent(question, top_k=5, filters=None, max_steps=6, budget=None) -> dict:
    """Agentic 检索：自主多轮，最多 max_steps 步，返回 {results, answer, trace}。
    任一环节失败 → 返回 None，由调用方退回 multi_query_search（静默降级）。"""
    from src.llm.client import get_llm
    llm = get_llm()
    if not llm.enabled:
        return None                                   # 降级：无 LLM 不做 agent

    budget = budget or Budget(max_llm_calls=8, max_seconds=45)
    scratch = EvidenceStore()                         # 去重累积的证据（chunk_id → row）
    steps = []

    for step in range(1, max_steps + 1):
        if budget.exhausted():
            break                                     # 超预算 → 收敛
        action = llm.chat_with_tools(                 # Thought + ToolCall(s)
            messages=_agent_messages(question, steps, scratch.summary()),
            tools=TOOL_SCHEMAS,
        )
        steps.append(_trace_step(step, action))

        if action.tool == "answer":
            break                                     # Agent 主动终止

        try:
            rows = TOOL_IMPL[action.tool](**action.args)   # 执行工具
        except Exception as exc:                      # 工具失败不致命
            steps[-1]["error"] = str(exc)
            continue
        scratch.add(rows)                             # 观测：累积证据
        steps[-1]["observation"] = _summarize(rows)   # 供下一轮上下文 + 前端展示

    results = scratch.ranked(top_k)                   # 汇总证据 → 候选
    answer = llm.generate(question, results, history) # 复用现有接地 prompt（含 [Source N] 引用）
    return {"results": results, "answer": answer, "trace": {"steps": steps, ...}}
```

### 4.1 反思-改写循环（范式差异的核心）

反思不是额外的一次 LLM 调用，而是**下一轮 `chat_with_tools` 的输入**——把「已收集证据摘要」
喂回模型，由它决定：**继续换角度检索 / 精读某块 / 直接回答**。这样每个 ReAct 步天然携带反思。

为可控，另加一个**显式的收敛判据**（避免模型「贪心」）：

- 连续两步没有新增 chunk_id → 判为「边际收益为 0」，强制进入 `answer`。
- 已收集证据覆盖 ≥ `top_k` 个不同文档 + 关键实体 → 提示模型可以收敛。
- 步数达 `max_steps` 或预算耗尽 → 强制 `answer`。

### 4.2 与现有 `plan_question` 的关系

| | `plan_question`（现有） | Agent 循环（新增） |
| --- | --- | --- |
| 调用次数 | 固定 1 次 | 动态 1~max_steps 次 |
| 产出 | 一次性计划（subs/stepback/hyde） | 每步 Thought + ToolCall |
| 是否观测结果 | 否 | 是（observation 回灌） |
| 是否可改写 | 否 | 是（反思后换工具/换 query） |

两者**不冲突**：Agent 的第一轮可以直接把 `plan_question` 的多查询能力当作一次 `search_knowledge` 调用（内部已含 decompose/stepback/hyde）。即「传统多查询」是 Agent 的一个强大工具，而非平行替代。

---

## 5. 工具集设计（Tool Schema）

工具统一签名：`(query/args) → list[chunk_row]`，输出与现有检索结果同构（`chunk_id / doc_name / chunk_index / text / score / metadata`），使证据可以无缝合并进 RRF 与 `sources`。

| 工具 | 复用的现有函数 | 工具入参 | 适配层要做的事 | 典型用途 |
| --- | --- | --- | --- | --- |
| `search_knowledge` | `retrieval.two_stage_search` | `query, top_k, filters` | `embed(query)` + `extract_terms(query)` 后再调用 | 主力召回：向量+关键词+路由，RRF |
| `search_graph` | `graph.graph_channel` | `query, top_k, filters` | `embed(query)`；跳数写死 ≤2，不暴露给 Agent | 多跳关系：串起分散线索 |
| `route_documents` | `database.search_doc_index` | `query, top_k` | `embed(query)`；现有默认 `top_k=3` | 先定位「该查哪几篇」 |
| `read_chunk` | `database.get_chunk`（**需新增**） | `chunk_id` | 现有只有 `get_chunks(doc_id)`，需按 id 取单块 | 精读命中块原文，补充上下文 |
| `rerank` | `rerank.rerank` | `query, chunk_ids, strategy` | 候选从 `EvidenceStore` 取，非重新召回 | 对累积候选精排（可选） |
| `answer` | 终止信号 | — | — | 证据足够，进入生成 |

> **适配层（`src/agent.py` 内的 `TOOL_IMPL`）是必须的**：现有检索函数普遍接收
> `embedding` / `terms` 而非原始字符串，工具层负责「query → embedding + terms」的转换，
> 这样工具契约对模型友好（只给 query），底层复用又不打折。
>
> 新增 DB helper `get_chunk(chunk_id)`（存储层唯一出口，符合「存储层之外不写 SQL」约定）。
> `TOOL_SCHEMAS` 用 function-calling 的 JSON Schema 描述；注意现有 `tool_call` 是
> **强制单工具**（`tool_choice` 对象形式），Agent 需要的是**自由多工具选择**，
> 因此新增 `chat_with_tools(messages, tools)`，不复用 `tool_call`。

**工具选择的可控性**：工具集合有限且全部本地（无外部网络），风险主要是「选错工具」而非「越权」。
每个工具都有 `top_k` 上限与 `filters` 透传，防止单工具拉爆上下文。

---

## 6. 数据模型

### 6.1 新增表 `agent_traces`（可选用，用于评估复盘）

```sql
CREATE TABLE IF NOT EXISTS agent_traces (
    id             UUID PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    question       TEXT NOT NULL,
    steps          JSONB NOT NULL DEFAULT '[]'::jsonb,  -- 每步 thought/tool/args/observation
    termination    TEXT,                                -- answered | budget | max_steps | fallback
    step_count     INTEGER NOT NULL DEFAULT 0,
    llm_calls      INTEGER NOT NULL DEFAULT 0,
    latency_ms     DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_traces_conv_idx ON agent_traces(conversation_id, created_at);
```

现有 9 张表**不动**；`conversation_messages` 继续承载最终回答与 `sources`（引用来源不变）。

### 6.2 trace 结构扩展（`schemas.py`）

现有 `QueryTrace` **不破坏**，新增可选字段：

```python
class AgentStep(BaseModel):
    step: int
    thought: str | None = None        # 模型的推理文本（可空）
    tool: str                          # 工具名
    args: dict[str, Any] = {}
    observation: str | None = None     # 观测摘要（供前端展示）
    new_chunks: int = 0                # 本步新增证据数（判断边际收益）
    error: str | None = None
    latency_ms: float = 0.0

class AgentTrace(BaseModel):
    enabled: bool = False
    steps: list[AgentStep] = []
    termination: str | None = None     # answered | budget | max_steps | fallback
    budget: dict[str, Any] = {}        # {max_steps, max_llm_calls, max_seconds, used_*}
    evidence_docs: int = 0

# QueryTrace 追加：
#   agent: AgentTrace | None = None
```

---

## 7. API 设计

### 7.1 模式开关：顶层 `mode`，而非并入 `features`

**结论：用顶层参数 `mode: "pipeline" | "agent"`，默认 `pipeline`。**

理由（trade-off）：

- Agentic 是**编排层**，不是「通道」。塞进 `features` 会让 `multi_query_search` 既要管通道又要管循环，职责混乱。
- 但为了让现有「三处同步」约定仍然成立，前端把它做成**互斥的模式选择器**（管线 / Agent），而不是和第 7 个开关并列的布尔量。
- 这样 `features` 语义保持纯粹：**Agent 模式下，`features` 变成「允许 Agent 使用的工具子集」**（默认全开）。

```python
class QueryRequest(BaseModel):
    question: str
    top_k: int = 5
    conversation_id: str | None = None
    filters: dict[str, Any] | None = None
    features: list[FeatureName] | None = None       # pipeline 模式=通道；agent 模式=可用工具集
    rerank_strategy: RerankStrategy | None = None
    mode: Literal["pipeline", "agent"] = "pipeline"  # 新增
    max_steps: int = Field(6, ge=1, le=12)           # 新增，仅 agent 模式生效
    debug: bool = False
```

### 7.2 路由（已实现）

`/api/query` 签名不变，内部分流：

```python
# routes.py::query
results, agent_trace = [], None
if request.mode == "agent":
    outcome = _run_agent_or_none(request)     # 内部 try/except，任何异常都返回 None
    if outcome is not None:
        results, agent_trace = outcome["results"], outcome["trace"]

if not results:                               # pipeline，或 agent 未产出（静默降级）
    raw = multi_query_search(...)             # 现有路径，零改动
```

**与初稿的一处偏差**：`run_agent` **只返回检索结果与 trace，不生成回答**。
原设计让它一并 `generate`，但 routes 里已有 `[Source N]` 引用、figures 提取、`save_message`、
`history` 处理，再生成一次就会有两份逻辑。现在生成统一由 routes 负责，
Agent 的 `answer` 工具只是**终止信号**（意为「证据够了，别再搜了」）。

**硬约束**（已由 `tests/test_query_mode.py` 保证）：
`mode="pipeline"` 时 `run_agent` **完全不被调用**；`mode="agent"` 且 Agent 失败时
`multi_query_search` 必被调用一次，响应形态与 pipeline 完全一致。

### 7.3 新增只读端点（可选）

- `GET /api/agent/traces/{conversation_id}` —— 回放某会话的 Agent 轨迹（评估/调试用）。

### 7.4 自动路由（`mode="auto"`）：可行性与取舍

> 先澄清术语：现有 `features` 里的 `routing` 是**文档路由**（`search_doc_index` 先定位
> "该查哪几篇"），与本节的**范式路由**（该走传统 / Graph / Agentic）是两件事，不要混淆。

**结论：不建议做「预测式路由」（先看问题、再决定走哪条路）；建议做「自适应升级」（先跑便宜的，不够再升级）。而且两者都应排在 P2 之后。**

#### 为什么预测式路由效果不好

1. **分类器看的是问题文本，而真正决定要不要 Agentic 的是「证据够不够」。**
   一个看起来简单的问法可能横跨三篇文档；一个看起来复杂的问法可能一段话就答完。
   事前的文本信号与事后的证据质量相关性很弱。
2. **难度是连续的，不是离散可分的。** 三类问题的边界模糊，路由器的误差集中落在边界上——
   恰恰是收益最大的那批题。
3. **阈值能校准，但代价很高——而三路范式路由的标定成本只会更高。**

   > 更新（2026-09-11）：这条论据原本写的是「阈值没有 Ground Truth 可校准」，并举
   > `_MIN_ROUTE_SCORE` 注释里的「未校准（bge-m3）」为例。main 分支上这个阈值**已经被校准了**
   > （`scripts/calibrate_thresholds.py`）：0.30 → 0.70，依据 8 篇文档 / 7077 切片 /
   > bge-m3 1024 维，在三个评测集上 段落查询(n=120) Hit@5 57%→88%、首句查询(n=71) 44%→69%、
   > 手写查询(n=32) MRR 0.678→0.932。所以「不可校准」的说法是错的，应改为「**可校准但很贵**」。

   校准一个二值文档路由阈值的代价是：写一个专门的校准脚本 + **223 条带标注的查询**
   （120 + 71 + 32）。三路范式路由要标定，得再额外标注「这道题该走哪条路」——
   而范式选择的正确答案本身就是主观的、依赖系统当前能力的，标注一致性只会更差。
   **结论不变，但论据更硬**：不是不能做，是要先付 223 条标注这个量级的成本，
   而这笔预算花在 §13.5 说的评测集质量上回报更高。

   > 顺带一个对 Agentic 的利好：校准的实测结论是「路由一次取 3 篇、其中往往 2 篇是错的」，
   > 因此最优解是**全局兜底通道常开**。Agentic 的 `search_knowledge` 走 `two_stage_search`，
   > 兜底逻辑本就在里面，等于天然吃到了这个结论；而 Agent 还能通过「换角度再搜一次」
   > 进一步弥补单轮路由的漏检——这正是 Agentic 相对单轮的增量价值所在。
4. **误差代价严重不对称**（这是最关键的一点）：

   | 路由结果 | 后果 | 严重性 |
   | --- | --- | --- |
   | 简单题 → 误判走 Agentic | 多花 3~5 倍延迟/成本，**答案通常不差** | 轻（只费钱） |
   | 复杂题 → 漏判走单轮 | **直接答错/答不全，且用户无法感知** | 重（答案坏了） |
   | 中间题 → 判错任一边 | 同上，视方向而定 | 中 |

   不对称意味着：如果一定要有误差，应该**偏向过度使用 Agentic**。这与「省成本」的初衷相悖——
   自动路由省下的钱，可能正是用答案质量换的。

#### 三种做法对比

| 方案 | 额外成本 | 判断依据 | 判断时机 | 评价 |
| --- | --- | --- | --- | --- |
| **A. LLM 分类器** | +1 次 LLM 调用（+300~800ms，**所有请求**） | 问题文本 | 检索前 | 最贵且最不准；给简单题也加上固定开销，不划算 |
| **B. 规则/启发式** | ≈0 | 问题长度、信号词、实体数 | 检索前 | 便宜但很脆，同 A 一样是「猜」 |
| **C. 自适应升级（Cascade）** | 仅对升级的题付费 | **实际观测到的证据质量** | 检索后 | **推荐**：用事实而非猜测做决策 |
| **D. 让 Agent 自己当路由器** | 与现有 `plan_question` **打平**（见 §13） | Agent 首步决定检索或直答 | 循环内 | **架构最优**，见 §13。前提是 Agent 首步**取代**而非叠加 `plan_question` |

#### 推荐做法：C + 零成本复用 `plan_question`

现有 `multi_query_search` **已经在跑** `plan_question`（一次 LLM 调用），它的输出天然是复杂度信号，
复用它**不增加任何 LLM 开销**：

| 信号 | 来源 | 含义 |
| --- | --- | --- |
| `plan["subs"]` 非空 | `plan_question`（已有） | 模型判断需要拆分子问题 → 多跳 |
| `plan["step_back"]` 非空 | 同上 | 需要退一步抽象 |
| `plan["hyde"]` 非空 | 同上 | 非事实型问题 |
| `stats["route_fallback"]` 为真 | `two_stage_search`（已有） | 文档路由没把握，已兜底 |
| `stats["keywords"] == 0` | 同上 | 关键词通道零命中 |
| 融合后 top1 的 RRF `score` 偏低 | `rrf_merge`（已有） | 没有强相关证据 |
| 结果只覆盖 1 个 `doc_name` | 检索结果 | 线索可能没串起来 |

分两级判定：

- **L0（检索前，零成本）**：`plan_question` 输出 + 问题特征 → 只用于**提前升级**那些信号很强的复杂题（避免白跑单轮）。
- **L1（检索后，基于证据）**：单轮跑完，用证据质量信号判定 → 不足才升级到 Agentic，并**带上已收集的证据**作为 Agent 的初始 `EvidenceStore`（不浪费第一轮）。

```python
# 伪代码：自适应升级
results = multi_query_search(q, top_k, debug=True)          # 单轮，但要 trace 信号
if l0_signals_strong(q, plan) or l1_evidence_weak(results, trace):
    outcome = run_agent(q, seed_evidence=results)           # 升级，复用已有证据
    if outcome: return outcome
return pipeline_answer(q, results)                          # 够了，直接答
```

#### 仍然必须保留显式 `mode`

`mode="auto"` 只能是**可选项，默认仍为 `pipeline`**，原因：

1. **可评估性**——消融评测必须能强制走某条路，否则无法归因。
2. **可控性**——用户/调用方需要能强制指定（成本高或延迟敏感的场景）。
3. **数据从哪来**——auto 的阈值要靠消融数据标定，而拿数据必须先能强制分流。
   顺序是：`显式 mode` → 跑消融 → 拿到「复杂题占比 / 各路收益」→ 才谈得上校准 auto。

#### 效果预期（诚实估计）

- **准确率**：相比「全走 Agentic」不会更好，大概率略差（路由误差引入的损失）。
- **收益**：只在成本/延迟——避免对简单题付 Agentic 的钱。收益大小**完全取决于语料里复杂题的占比**：
  占比 < 10% 时收益有限，> 30% 时才值得做。
- **代价**：复杂题的延迟变成「单轮 + Agent」叠加，比直接走 Agentic 更慢。

**建议排期：P2 之后。** 先把显式开关做出来、跑完消融、拿到「复杂题占比」和各路的收益数据，
再决定 auto 值不值得做、阈值定在哪。没有数据支撑的阈值就是拍脑袋——`_MIN_ROUTE_SCORE` 那条
「未校准」的注释已经说明过一次了。

---

## 8. 前端设计

复用现有「检索检视面板」的交互范式，新增 Agent 专属视图：

| 位置 | 改动 |
| --- | --- |
| 问答页顶部 | 模式选择器：`管线` / `Agent`（互斥）。Agent 模式下露出 `最大步数` 滑杆 |
| 右侧检视面板 | 新增 **Agent 轨迹时间线**：按步展示 `Thought → 工具(参数) → 观测(新增 N 块)`，可折叠 |
| 消息卡片 | 回答、`[Source N]` 引用、figures 展示**不变**（证据来源仍走 `sources`） |
| 顶部状态条 | Agent 模式下显示当前步数 / 已用 LLM 调用数，超预算给黄标 |

- 组件：`components/chat/agent-timeline.tsx`（新建），数据来自 `trace.agent.steps`。
- `lib/api.ts` 增补 `AgentStep` / `AgentTrace` 类型；`mode` / `max_steps` 进入 `QueryRequest`。
- 模式持久化沿用 `localStorage`（现有 `nexus-rag-retrieval-settings` 同套机制）。

---

## 9. 评估方案

Agentic RAG 的价值必须**用数据证明**，而不是「看起来很高级」。纳入现有消融矩阵：

### 9.1 检索级（需改造 `run_ablation`，不能只加一行）

现状：`run_ablation(configs, top_k)` 内部**硬编码**调用 `multi_query_search`：

```python
m = retrieval_metrics(multi_query_search(case["question"], top_k, features=features), ...)
```

配置是 `(label, features: list[str] | None)` 二元组，**没有承载「走 agent」的位置**。
所以加 agent 行不能只往 `main()` 的 `configs` 里塞字符串，需要先做小改造：

```python
def run_ablation(configs, top_k=5) -> list[dict]:
    for label, features, runner in configs:          # 三元组：加 runner
        results = runner(case["question"], top_k, features)   # 默认 multi_query_search
```

- `runner` 默认 `multi_query_search`（现有 5 行配置**行为不变**）；
- agent 行传 `lambda q, k, f: run_agent(q, top_k=k, features=f)["results"]`；
- 这样 `none / default / +graph / +graph+rerank / all / agent(默认) / agent(step=8)` 同口径对比。

> 顺带修正：现有配置列表**不是**独立函数，而是内联在 `main()` 里，
> 改造时可顺势抽成 `_default_eval_configs()` 便于复用。

### 9.2 答案级（新增，Agentic 的真正考场）

Agentic 面向复杂多步问题，**只测 Hit@K/MRR 会低估其价值**。需补答案级指标：

- 数据：`eval_cases.reference_answer`（字段已存在，目前留白）。
- 指标：LLM 判官打分——**Faithfulness（接地性）/ Answer Relevance（相关性）/ Completeness（完整性）**。
- 现有 `evaluation.py` 的 CLI/接口可直接扩展 `run_ablation` 增加答案级列。

### 9.3 成本剖面（必须一并报告）

单列一张表，回答「贵了多少」：平均步数、平均 LLM 调用数、P50/P95 延迟、token 估算。
**没有成本数据的 Agentic 对比是不完整的**——这正是 §1.3 判断的量化依据。

---

## 10. 失败模式与降级

| 失败场景 | 处理 |
| --- | --- |
| LLM 未配置 / 不可用 | `run_agent` 返回 `None` → 退回 `multi_query_search` |
| 中途 LLM 调用抛错 | 捕获 → 用当前已收集证据直接 `generate`（termination=error） |
| 工具执行报错 | 该步记 `error`，不中断循环，继续下一步 |
| 无限循环倾向 | `max_steps` + 边际收益为 0 判据 + 预算，三重兜底 |
| 预算耗尽 | 强制 `answer`，用现有证据生成，termination=budget |
| 证据为空 | 走现有「未检索到相关内容」分支（与 pipeline 一致） |

**原则**：Agentic 是「锦上添花」路径，任何时候失败都必须能安静地退回那条已经验证过的单轮管线。

---

## 11. 分期实施

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| **P0 骨架** | `src/agent.py` + 3 个核心工具（search_knowledge / search_graph / answer）+ ReAct 循环 + trace + `mode` 开关 + 降级 | ✅ **已完成** |
| **P1 闭环** | 反思-改写（observation 回灌）+ 预算守卫 + `agent_traces` 落库 + 前端轨迹时间线 | 待做 |
| **P2 扩展** | 补 `read_chunk` / `rerank` 工具 + 工具并行 + 答案级评测（LLM 判官）+ 成本剖面 | 待做 |
| **P3 进阶（观察触发）** | 子 Agent / 多 Agent 协作、跨会话记忆、流式步骤推送 | 仅在 P2 证明收益后启动 |
| **P4 统一收敛** | 见 §13.4：把 pipeline 实现为 `run_agent(max_steps=1)`，两条路径合并 | 需 P2 数据支撑 |

### 11.1 P0 交付与验收结果

| 交付物 | 说明 |
| --- | --- |
| `src/agent.py` | `run_agent` / `TOOL_SCHEMAS` / `TOOL_IMPL` / `Budget` / `EvidenceStore` / `_active_tools` |
| `src/llm/client.py` | 新增 `chat_with_tools(messages, tools)`（多工具 ReAct，区别于强制单工具的 `tool_call`） |
| `src/api/schemas.py` | `QueryRequest.mode` / `max_steps`；新增 `AgentStep` / `AgentTrace`；`QueryTrace.agent` |
| `src/api/routes.py` | `_run_agent_or_none` + 按 `mode` 分流，失败静默退回 `multi_query_search` |
| `tests/test_agent.py` | 16 例：降级 / 收敛判据 / 预算 / 工具报错 / 证据去重 / 观测回灌 / 工具子集 |
| `tests/test_query_mode.py` | 4 例：pipeline 零回归、agent 成功不重跑、agent 失败静默降级 |

验收结果：**全量 84 个测试，20 个新增全绿**；失败数 2 个，与改动前基线一致
（均为 `test_retrieval.py` 中已存在的陈旧断言，与本次改动无关——
另一工作树的 `894c196 chore: fix stale tests` 已修复）。
**pipeline 零回归成立**：`mode` 默认 `pipeline`，此时 `run_agent` 完全不被调用。

> P0 实现中发现并修复的一个真 bug：工具子集限制最初按全局 `TOOL_IMPL` 校验，
> 导致 `features` 未挂载的工具仍会被执行。现改为按本次允许的 `impl` 子集校验，
> 模型选了未挂载的工具则按终止处理。

**合入 main 前需复核的一项**：P0 代码基于 `084d2bb`（阈值校准前）编写，
而 main 上 `_MIN_ROUTE_SCORE` 已从 0.30 改为 0.70（兜底常开，见 §7.4 论据 3）。
单测全部 mock 了检索层，因此不受影响；但合入后应在真实语料上复核
`search_knowledge` / `search_graph` 两个工具的实际召回表现，
并按 `scripts/calibrate_thresholds.py` 的说明重跑评测页消融。

---

## 12. 风险与权衡（必须正视）

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| **延迟/成本高** | 多次 LLM + 多轮检索，可能 3~5 倍于单轮 | 默认关闭；硬预算；边际收益判据提前收敛 |
| **不确定性** | 同一问题两次轨迹可能不同，评测方差大 | 固定评测集 + 多次取均值；trace 留档复盘 |
| **过度工程** | 简单问题走 Agent 是负收益 | 前端注明适用场景；默认管线；评测驱动决策 |
| **上下文膨胀** | 每步 observation 累积会撑大 prompt | observation 存摘要而非原文；证据去重 |
| **评测难度** | 无标准答案、需 LLM 判官 | 复用 `reference_answer` 字段；判官 prompt 与生成 prompt 分离 |
| **调试复杂** | 多轮黑盒难定位 | 每步完整落 trace；`agent_traces` 可回放 |

**一句话**：Agentic RAG 的价值上限高、下限低。设计上所有「贵」的开关都必须显式打开，
所有失败都必须能退回已验证的单轮管线——这样它才是资产，而不是负债。

---

## 13. 最终推荐：统一自适应循环（分阶段收敛）

### 13.1 核心洞察：三范式不是三个东西

把「该走哪条路」当作分类问题，是因为先入为主地把三种范式看成了三条平行管线。
换一个视角——**它们是同一个循环的三个特例**：

| 范式 | 在这个统一视角下 |
| --- | --- |
| 传统 RAG | 循环跑 **1 步**就收敛（只调 `search_knowledge`） |
| Graph RAG | 循环跑 **1 步**就收敛，但**选了 `search_graph` 工具** |
| Agentic RAG | 循环跑 **N 步**，工具按需切换 |

区别只有两件事：**步数**和**工具选择**。所以根本不需要路由器——
Agent 每一步的 tool 选择本身就是路由决策，而且是**基于已观测证据**做出的。

这同时解决了 §7.4 的两个难题：不需要预测（无路由误差），不需要校准阈值（无阈值）。

### 13.2 一个反直觉的事实：简单题并不亏

上一节说「Agent 首步会多一次 LLM 往返」，**这个说法需要修正**。

关键在于「**够不够**」的判断**不是额外的一次 LLM 调用**——它就是 ReAct 步本身。
`chat_with_tools` 的返回已经在同时回答两件事：返回 `answer` = 够了，返回 `search_xxx` = 不够。

于是（前提是 Agent 首步**取代** `plan_question`，而不是叠加在它上面）：

| | LLM 调用次数 |
| --- | --- |
| 现有 pipeline（默认 features） | 1（`plan_question` 做 decompose/stepback/hyde） |
| 统一循环，简单题 | 1（Agent 首步决策，直接 `answer`） |
| 统一循环，复杂题 | N（每步 1 次，按需增加） |

**简单题打平，复杂题按需付费。** 这才是 Agentic 应该有的成本曲线——
贵的那部分只发生在真正需要的地方，而且没有路由误差。

> 代价：Agent 模式下 `search_knowledge` 工具内部不再跑 `plan_question`（否则变 2 次），
> 即把 decompose/stepback/hyde 的**决策权从固定规则交给 Agent**。
> 复杂题上 Agent 可以自己换 query 再搜一次来实现等价效果，但**这需要消融数据验证**——
> 有可能在某些题上不如现有的固定多查询。这是本方案唯一需要在 P2 用数据回答的问题。

### 13.3 但工程上不能一步到位

统一循环的**架构最优，风险也最高**：

1. 打破了「pipeline 模式零改动」的承诺——所有请求都走新代码路径，回归面最大。
2. 所有问题都带上不确定性：简单事实题从「确定路径」变成「模型这次选了什么」，
   同一问题两次结果可能不同，这对简单题是**退化**。
3. 对模型能力要求更高：工具选择必须准，选错就是负收益。

### 13.4 推荐路径：代码统一，行为分化，分阶段收敛

```
现在 ──────────────────────────────────────────────► 最终
P0/P1              P2                P3
两条路径并存        跑消融拿数据        pipeline 收敛成
pipeline 走老代码   验证 13.2 的假设     run_agent(max_steps=1)
（零回归）                             只剩一份代码
```

- **近期（P0/P1）**：保留现有 `multi_query_search` 不动，`run_agent` 独立叠加，
  显式 `mode` 切换。这是本文档前 12 章的方案，风险最低。
- **P2**：跑消融，重点验证 13.2 的两个假设——① 简单题 LLM 调用数确实打平；
  ② 复杂题上「Agent 自主多查询」不输「固定 decompose/stepback/hyde」。
- **P3（数据说话后）**：若 ② 成立，把 pipeline 模式实现为 `run_agent(max_steps=1)`，
  两条路径合并成一份代码，路由问题自动消失。

**不要跳过 P2 直接做 P3。** 统一循环的优雅是真实的，但它押注在「模型工具选择足够准」上，
而这个假设只能用你自己语料上的消融数据来验证。

### 13.5 最后一句提醒

「最好」取决于目标。如果目标是**系统真的好用**，那第三条范式的优先级可能低于：
评测集质量（`eval_cases` 目前只有 6 条多跳例）、答案级指标（`reference_answer` 字段还空着）、
以及 `build_routing_summary` 这种机械摘要的质量。**消融矩阵本身比多一条范式更有说服力。**
如果目标是**范式齐全度**，那就按 13.4 推进，但务必把成本剖面（§9.3）一起报告——
能说清「贵多少、换来了什么」的方案，才经得起追问。

---

## 附录 A：与现有代码的接入点清单

| 文件 | 改动 |
| --- | --- |
| `src/agent.py` | **新建**：`run_agent` / `TOOL_SCHEMAS` / `TOOL_IMPL`（含 query→embedding+terms 适配）/ `Budget` / `EvidenceStore` |
| `src/llm/client.py` | 新增 `chat_with_tools(messages, tools)`（多工具 ReAct，区别于现有强制单工具的 `tool_call`） |
| `src/ingestion/embedder.py` | **只读复用**：工具适配层用它把 `query` 转成 `embedding`（无改动） |
| `src/api/schemas.py` | `QueryRequest` 加 `mode` / `max_steps`；新增 `AgentStep` / `AgentTrace`；`QueryTrace` 加 `agent` |
| `src/api/routes.py` | `query` 内按 `mode` 分流；失败降级 |
| `src/storage/database.py` | 新增 `get_chunk(chunk_id)`；`agent_traces` 建表与读写 |
| `src/evaluation.py` | 消融配置加 agent 行；扩展答案级指标 |
| `ui/web/lib/api.ts` | 类型与请求字段 |
| `ui/web/components/chat/` | 新增 `agent-timeline.tsx`；模式选择器；`retrieval-inspector.tsx` 接入 |

## 附录 B：待用户确认的开放问题

1. **模式开关形态**：顶层 `mode`（本方案推荐）还是并入 `features`？
2. **首版工具范围**：只做 3 个核心工具，还是 P0 就补 `read_chunk`？
3. **是否持久化轨迹**：`agent_traces` 表是否 P0 就建（含数据保留策略）？
4. **答案级评测**：是否本轮纳入 LLM 判官，还是先只做检索级消融？
5. **`docs/*` 忽略规则**：方案文档是否要脱离 `.gitignore` 进版本库？
6. **自动路由（§7.4）**：是否接受「先显式开关 → 跑消融 → 拿数据后再谈 `mode="auto"`」的排期？
   若坚持本轮就上 auto，需要先确认语料里复杂题占比（< 10% 时收益有限）。
