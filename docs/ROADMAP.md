# NexusRAG 平台化路线图

> 定位：**RAG 技术实践平台**——市面上 RAG 相关技术统一进本项目，逐技术可开关，
> 配内置评估层做消融对比。不限定领域，pipeline 按用户配置。
> 定位决策（2026-09-09）：技术实践平台 · v1 全技术清单分期做 · 配置三层全做 · 评估自研先行/RAGAS 可选。

## 架构分层与技术清单

| 层 | 技术模块 | 状态 | 分期 |
|---|---|---|---|
| 数据 | loaders: PDF/MD（含图片 caption） | ✅ | — |
| 数据 | HTML/CSV/JSON/网页抓取，统一注册 | 🔲 | P2 |
| 切分 | 固定+重叠（默认） | ✅ | — |
| 切分 | 语义切分（embedding 边界） | 🔲 | P2 |
| 切分 | 父级-子级 chunking（子级检索→父级喂 LLM） | 🔲 | P2 |
| 索引 | 向量 HNSW + trigram GIN + jsonb GIN | ✅ | — |
| 索引 | tsvector + zhparser（>10k 文档升级路径） | 🔲 | P4 |
| 索引 | 实体/主题倒排表（轻量 GraphRAG） | 🔲 | P2 |
| 检索 | 两级路由（doc_index） | ✅ | — |
| 检索 | 混合检索 + RRF | ✅ | — |
| 检索 | 多查询规划（分解/退步/HyDE，单次 LLM 门控） | ✅ | — |
| 检索 | 元数据过滤 | ✅ | — |
| 检索 | Rerank 4 策略（rrf/cross BGE-reranker/llm 打分/colbert Late-Interaction，`RERANK_STRATEGY` 切换） | ✅ | P1 |
| 依赖 | colbert-ai + transformers<5 钉子；ColBERT 模型预下载 `models/colbert`（tct_colbert-v2-hn-msmarco，英文系，中文换多语模型） | ✅ | P1 |
| 检索 | 重 GraphRAG（社区摘要） | 🔲 | P4 |
| 数据 | Text-to-SQL（8 项 todo，先确认数据源） | 🔲 | P2 |
| 生成 | LLM 可换、引用标注、拒答 | ✅ | — |
| 评估 | 自研：评测集(DB) + MRR/Hit@K（检索级已做；LLM 判官答案级后置） | ✅ | **P1** |
| 评估 | RAGAS 可选插件 | 🔲 | P4 |

## 配置模型（三层）

```
① 入库 pipeline（YAML, 全局）
   pipeline:
     chunking: {strategy: fixed|semantic|parent_child, ...}
     indexes: [vector, trigram, tsvector, entity_inverted]
     caption:  {enabled: true, min_size: 40, model: $VISION_MODEL}
   → 建哪些索引、怎么切分，入库时读

② 查询特性开关（API 参数，逐请求）
   POST /query {question, features: [routing, keywords, hyde, stepback, rerank, entity], filters}
   features 缺省 = 全开（pipeline YAML 未禁用的）；调试单技术效果传显式列表

③ 运行时设置（DB settings 表 + 前端设置页）
   可视化开关 ② 的默认值 + ① 中可热切换项（如 rerank 开/关）
   改 ③ 即时生效，不动 YAML 文件
```

技术开关的统一契约：每个检索技术实现 `name + enabled(config) + run(...) -> channels`，
`multi_query_search` 变成按 features 组装通道列表，新技术 = 新文件 + 注册，不动主干。

## 分期里程碑

**P0（现在）** 已上线能力 + 本文档；Text-to-SQL todo 保留
**P1（1-2 周）** ✅ 已完成：特性开关契约（features 参数）+ 评估层（eval_cases 表 + MRR/Hit@K + 消融 CLI `python -m src.evaluation`）+ Rerank（本地 cross-encoder，默认关，消融/显式 features 开启）
- 待补：LLM 判官（答案级评估）；评测集扩充（当前 n=5 冒烟级）
**P2（随后）**
- 语义切分 + 父级 chunking；实体倒排表；更多 loaders；Text-to-SQL（先确认数据源）
- 前端设置页（③）
**P3** 性能与规模化：psycopg_pool、连接池化、异步切分后台任务（原"完整生产修复"层）
**P4（观察触发）** >10k 文档 → tsvector+zhparser + doc_index HNSW 恢复；
重 GraphRAG；RAGAS 插件

## 文档策略（每技术一页）

`docs/techniques/<name>.md`：原理 3-5 行 / 本项目接入点 / 开关方式 / 消融数据（来自 P1 评估层）。
没做消融的技术先写原理+接入点，效果栏留白。

## 验收标准

P1 完成后：同一评测集下"全开 vs 单技术 vs 关"三组消融表能回答
"哪个技术在我的语料上真的有用"——这是实践平台的立身之本。
