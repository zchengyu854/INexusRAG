# NexusRAG — 多文档智能问答系统

## 项目概述

NexusRAG 是一个基于 RAG（Retrieval-Augmented Generation）技术的多文档智能问答系统，支持上传 PDF / Markdown / TXT 文档，并通过自然语言进行智能问答。

项目覆盖当前 RAG 技术栈的核心概念与实践，适合作为学习 RAG 全链路的技术实践项目。

---

## 当前 RAG 技术全景

### 一、基础层

| 概念 | 说明 |
|------|------|
| **Chunking 策略** | 固定长度切片、语义切片（LLM-based splitting）、递归字符切片；是检索效果的第一决定因素 |
| **父子切片（Parent-Child / small-to-big）** | 小块用于精准检索，命中后回溯父块喂给 LLM；句子窗口检索（Sentence Window）同属此类 |
| **Embedding 模型** | OpenAI text-embedding-3、BAAI/bge-m3、jina-embeddings-v2；多语言场景推荐 BGE-m3 |
| **向量数据库** | Chroma（轻量本地，零部署）、Qdrant（生产级）、Milvus、Weaviate |
| **ANN 索引原理** | HNSW（分层可导航小世界图）、IVF、Flat 暴力检索；面试常考"向量检索底层如何实现" |
| **Retrieval 增强** | Hybrid Search（稠密向量 + 稀疏 BM25）→ RRF（Reciprocal Rank Fusion）融合 → Cross-encoder Rerank |

### 二、进阶层

| 概念 | 说明 |
|------|------|
| **LangGraph / LlamaIndex Teams** | 将 RAG 构建为有状态的多步骤 Pipeline，而非单次请求 |
| **Agentic RAG** | 检索 → 判断 → 补充检索 → 生成，支持工具调用与循环推理 |
| **HyDE（假设式检索）** | 先让 LLM 生成一个"假设答案"，再用它进行二次检索 |
| **Query 改写** | Multi-query 展开、步骤分解，提升召回率 |
| **Contextual Retrieval / Late Chunking** | Anthropic 提出的上下文增强切片：先为每个 Chunk 生成所属文档的上下文摘要再做 Embedding，显著降低检索失配 |
| **GraphRAG（知识图谱增强）** | 抽取实体与关系构建知识图谱 + 社区层级摘要，擅长全局性/多跳问题；面试常问"何时优于向量 RAG" |
| **CRAG / Self-RAG / Adaptive RAG** | 反思式 RAG 家族：检索质量自评与纠错（CRAG）、自我反思是否检索（Self-RAG）、按问题复杂度路由（Adaptive RAG） |
| **长上下文 vs RAG** | 百万级 Context 模型冲击下 RAG 的定位：成本、时延、可溯源性的权衡，面试高频开放题 |
| **多向量检索（ColBERT / Late Interaction）** | 词级向量延迟交互，精度高于单向量池化，代价是存储与索引复杂度 |
| **RAG 评估框架** | RAGAS / TruLens，用 faithfulness / answer_relevancy 等指标量化质量 |
| **RAG Fusion** | Multi-query 并行检索后统一融合重排，比单路查询显著提升召回覆盖 |
| **Raptor** | 递归摘要构建分层检索树（叶子=原文块，上层=聚类摘要），长文档全局与细节问题兼顾 |
| **DSPy** | 将 RAG Pipeline 视为可编译程序，自动优化提示词与检索参数，替代手工调 Prompt；面试新宠"如何系统化调优 RAG" |
| **Matryoshka Embedding（套娃向量）** | 一次编码得到可截断的多精度向量（1536→512→256），精度与成本/速度灵活权衡 |
| **向量量化** | PQ（乘积量化）/ SQ（标量量化）/ 二值量化，存储压缩 80%+；生产级大规模向量库必考 |
| **多模态 RAG** | CLIP / LLaVA 图文联合检索、PDF 图表理解（GPT-4V + OCR）；高频题"如何让 RAG 支持图表问答" |
| **RAG 安全** | 间接 Prompt Injection（文档投毒）防御、PII 过滤、检索级权限隔离（ACL）；企业落地必问 |
| **流式 RAG** | 边检索边生成（Streaming + SSE），降低首字延迟，优化长问答体验 |
| **RAG vs Fine-tuning** | 知识频繁变化→RAG，改变模型行为/格式→微调，二者常组合；面试必问决策框架 |

### 三、落地层（企业主流实践）

- 混合检索：Dense + BM25 + 元数据过滤，RRF 融合
- Cross-encoder Rerank：提升 Top-K 相关性
- 父子切片：小块检索、大块生成（small-to-big）
- 上下文压缩：仅将相关片段注入 LLM 上下文，避免信息过载
- 增量更新与语义缓存（GPTCache 思路）：减少重复 Embedding / LLM 开销
- 可观测性：LangSmith / OpenTelemetry 追踪检索命中率与回答质量
- 幻觉缓解：要求 LLM 引用原文出处、检索置信度阈值、低置信时明确拒答（"无相关信息"）
- 监控闭环：检索命中率、Rerank lift、P95 延迟、Token 成本、用户反馈回流数据集
- 权限与多租户：元数据级 ACL 过滤，在检索阶段完成数据隔离，而非生成后过滤

---

## 面试高频问题速查

### Q1: RAG vs Fine-tuning vs Long Context 如何选？

| 维度 | RAG | Fine-tuning | Long Context |
|------|-----|-------------|--------------|
| 知识频繁更新 | ✅ 文档实时换 | ❌ 需重训 | ✅ 直接换上下文 |
| 可溯源 | ✅ 引用原文 | ❌ 黑盒 | ✅ 可引用 |
| 改变行为/语气/格式 | ❌ | ✅ | ❌ |
| 成本 | 中（检索+Embedding） | 高（训练） | 高（Token 费用） |
| 时延 | 中 | 低 | 高（长 Prompt） |

实践：三者组合——RAG 预筛选 → 长上下文精读 → 微调固定输出风格。

### Q2: 如何缓解 RAG 幻觉？

- **检索端**：Rerank 提升 Top-K 质量、置信度阈值过滤低相关块
- **生成端**：Prompt 强制引用原文、要求"上下文中没有则明确说不知道"
- **评估端**：RAGAS faithfulness 量化、人工抽查、用户反馈回流

### Q3: 向量数据库选型标准？

| 场景 | 推荐 | 原因 |
|------|------|------|
| 原型/学习 | Chroma | 零配置、Python 原生 |
| 生产中小规模 | Qdrant | Rust 实现、高性能、丰富过滤 |
| 大规模分布式 | Milvus / Weaviate | 集群、多租户、量化索引 |
| Serverless | Pinecone | 托管、按量付费 |

关键维度：索引类型（HNSW/IVF/Flat）、元数据过滤能力、量化支持、多租户、成本。

### Q4: 如何评估 Chunking 质量？

- Chunk 独立性：单块脱离上下文是否可理解
- 边界完整性：关键信息是否被切断（跨块实体丢失）
- 检索召回率：不同切片策略下的 Recall@K 对比
- 经验起点：512-1024 token + 10-20% overlap，再按评估调优

### Q5: 多跳/全局性问题如何处理？

单次向量检索无法回答"全文档总结类"或"A 影响 B，B 又影响什么"的问题：
- **GraphRAG**：实体关系图 + 社区摘要，擅长全局性问题
- **子问题分解**：Query Rewrite 拆成多个单跳子问题，逐个检索
- **Raptor**：分层摘要树，上层节点回答宏观问题

### Q6: 生产环境 RAG 的性能瓶颈在哪？

延迟大头通常在 LLM 生成，优化优先级：
1. 语义缓存（相同/相近问题直接返回）
2. 流式输出降低感知延迟
3. Embedding 批处理与缓存
4. Rerank 用轻量模型或两阶段（粗排 Top100 → 精排 Top10）

---

## 项目架构

```
nexus-rag/
├── src/
│   ├── ingestion/          # 文档解析与入库
│   │   ├── loaders.py      # PDF/MD/TXT 加载器
│   │   ├── splitter.py     # 文本切片策略
│   │   └── embedder.py     # Embedding 封装
│   ├── retrieval/          # 检索层
│   │   ├── vector_store.py # ChromaDB 封装
│   │   ├── hybrid_search.py # Dense + BM25 混合检索
│   │   ├── reranker.py     # Cross-encoder 重排序
│   │   └── query_rewrite.py # 多查询改写 / HyDE
│   ├── generation/         # 生成层
│   │   └── llm.py          # LLM 调用封装
│   ├── pipeline/           # LangGraph 编排
│   │   ├── graph.py        # 状态机定义
│   │   └── nodes.py        # 各节点逻辑
│   ├── evaluation/         # RAG 评估
│   │   └── ragas_eval.py   # faithfulness / answer_relevancy
│   └── api/                # 服务层
│       ├── app.py          # FastAPI 入口
│       └── schemas.py      # Pydantic 模型
├── ui/
├── data/                   # 示例文档目录
├── config/
│   └── settings.py         # 配置中心（环境变量）
├── tests/
│   ├── test_ingestion.py
│   ├── test_retrieval.py
│   └── test_pipeline.py
├── pyproject.toml
├── .env.example
└── README.md
```

---

## 技术栈

| 组件 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.11+ | RAG 生态最完整 |
| 包管理 | uv | 极速安装，现代替代 pip |
| LLM 框架 | LangChain / LangGraph | 生态成熟，支持 Agent 编排 |
| 向量库 | ChromaDB | 本地持久化，零依赖，开箱即用 |
| Embedding | BAAI/bge-m3 | 多语言、开源、无需 API Key |
| Rerank | BAAI/bge-reranker-v2-m3 | 中文效果好，开源 |
| 文档解析 | pymupdf / unstructured | 支持 PDF/MD/TXT |
| 服务层 | FastAPI | 异步、自动文档 |
| UI | Next.js | React + TypeScript，生产级前端 |
| 评估 | RAGAS | faithfulness / answer_relevancy 指标 |

---

## 核心流程

```
用户上传文档
    │
    ▼
[Ingestion]  解析 → 切片 → Embedding → 写入 ChromaDB
    │
    ▼
用户提问
    │
    ▼
[Query Rewrite]  Multi-query 展开 / HyDE 假设生成
    │
    ▼
[Hybrid Search]  Dense 向量检索 + BM25 稀疏检索 → RRF 融合
    │
    ▼
[Rerank]  Cross-encoder 对 Top-K 重新排序
    │
    ▼
[Generate]  将相关片段作为上下文，调用 LLM 生成答案
    │
    ▼
[Evaluation]  RAGAS 评估 faithfulness / answer_relevancy
```

---

## 环境准备

```bash
# 使用 uv 创建虚拟环境
uv init nexus-rag
cd nexus-rag
uv add langchain langchain-community langgraph chromadb \
     sentence-transformers rank-bm25 fastapi uvicorn streamlit \
     pymupdf ragas openai aiofiles python-multipart requests
```

## 启动

```bash
./run.sh          # 一键启动后端(:8000) + UI(:8501)
./run.sh backend  # 只启后端
./run.sh ui       # 只启 UI
```

---

## 开发路线

| 阶段 | 内容 | 目标 |
|------|------|------|
| Phase 1 | 基础 RAG：Chroma + Embedding + 简单检索 | 能跑通端到端流程 |
| Phase 2 | 混合检索 + Rerank | 提升召回质量 |
| Phase 3 | LangGraph 编排 + Query Rewrite | 引入多步推理能力 |
| Phase 4 | FastAPI + Next.js UI | 提供可交互的服务 |
| Phase 5 | RAGAS 评估 | 量化回答质量 |

> 各阶段的具体做法与 AI 辅助学习方法，见 [docs/learning-path.md](docs/learning-path.md)。

---

## 关键设计决策

1. **本地优先**：Embedding 和向量库全部本地运行，无需外部 API Key，适合学习和隐私敏感场景
2. **可扩展 LLM**：默认使用 OpenAI，通过 config 可切换至本地模型（Ollama / vLLM）
3. **模块化设计**：每个组件独立可替换，便于后续实验不同策略
4. **增量更新**：新文档不重建整个向量库，仅追加新切片

---

## 后续可拓展方向

- Agent 循环：检索→判断→补充检索（Agentic RAG）
- 反思式 RAG：CRAG 检索质量自评与纠错，低置信时回退 Web Search
- GraphRAG：实体关系抽取 + 社区摘要，补足全局性/多跳问题
- Raptor 递归摘要树：长文档分层摘要 + 检索（Tree Summarization 升级版）
- 多模态：支持图片文档（PDF 中的图表）
- 分布式部署：Chroma → Qdrant，支持横向扩展
- RAG 监控：LangSmith Tracing，追踪检索命中率、回答质量趋势
- DSPy 自动调优：用评估指标反向优化提示词与检索参数
- 安全防护：文档投毒检测 + 检索级 ACL 权限隔离
- 流式输出：Server-Sent Events 逐字生成，降低首字延迟
