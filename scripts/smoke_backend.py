"""后端冒烟测试：不连数据库、不调外部服务，验证新增端点注册与 trace 装配逻辑。

通过替换 psycopg / dotenv 为桩件，再在两个模块上做 monkeypatch，
让 FastAPI 路由与 retrieval 的 debug 分支可以在无依赖环境下真实执行一次。
"""
from __future__ import annotations

import sys
import types

# ---- 依赖桩件（必须在导入 src.* 之前注入）----
psycopg = types.ModuleType("psycopg")


def _no_db(*args, **kwargs):
    raise RuntimeError("psycopg stub: no database in smoke test")


psycopg.connect = _no_db
psycopg.Connection = object
rows_mod = types.ModuleType("psycopg.rows")
rows_mod.dict_row = object()
sys.modules["psycopg"] = psycopg
sys.modules["psycopg.rows"] = rows_mod

dotenv = types.ModuleType("dotenv")
dotenv.load_dotenv = lambda *a, **k: None
sys.modules["dotenv"] = dotenv

# jieba 是纯 Python 源码包（需要构建），冒烟测试里只需 lcut 存在
jieba_stub = types.ModuleType("jieba")
jieba_stub.lcut = lambda text: list(text)
sys.modules["jieba"] = jieba_stub

sys.path.insert(0, ".")

failures: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    status = "✓" if condition else "✗"
    print(f"  {status} {label}{(' — ' + extra) if extra else ''}")
    if not condition:
        failures.append(label)


print("\n[1] 应用可导入，路由已注册")
from src.api.app import app  # noqa: E402

# 新版 FastAPI 把 include_router 的结果存为嵌套的 _IncludedRouter，不再摊平到 app.routes，
# 因此以 OpenAPI schema 为准来枚举真实对外的接口。
paths = sorted(app.openapi()["paths"].keys())
expected_new = [
    "/api/health",
    "/api/graph/stats",
    "/api/graph/search",
    "/api/graph/entities/{entity_id}",
    "/api/graph/subgraph",
    "/api/eval/cases",
    "/api/eval/run",
    "/api/eval/seed",
    "/api/documents/{doc_id}/file",
]
for path in expected_new:
    check(path, path in paths)
check("原有端点未丢失", "/api/query" in paths and "/api/upload" in paths and "/api/stats" in paths, f"共 {len(paths)} 条接口")

print("\n[2] /api/health 在无 LLM、仅环境变量下可正常返回")
import src.api.routes as routes  # noqa: E402

routes.database_stats = lambda: {
    "total_documents": 6,
    "total_chunks": 1284,
    "embedding_dimension": 1536,
    "text_bytes": 4_300_000,
}
routes.get_active_llm_provider_row = lambda: None
health = routes.health()
check("status=ok", health.status == "ok", health.status)
check("database.ok", health.database.ok is True)
check("统计透传", health.documents == 6 and health.chunks == 1284)
check("llm 回退 env", health.llm.source in {"env", "none"}, health.llm.source)
check("embedding 维度", health.embedding.dimension > 0, str(health.embedding.dimension))

print("\n[3] 数据库异常时 health 降级而不抛错")
routes.database_stats = _no_db
degraded = routes.health()
check("status=degraded", degraded.status == "degraded", degraded.status)
check("database.ok=False", degraded.database.ok is False)
check("带错误信息", bool(degraded.database.error))

print("\n[4] 图谱端点装配")
routes.graph_stats = lambda: {"relations": 976, "links": 1132, "orphan_entities": 12, "entities": 412}
routes.graph_kind_counts = lambda: {"concept": 148, "method": 96}
stats = routes.graph_stats_endpoint()
check("GraphStats 字段", stats.entities == 412 and stats.relations == 976 and stats.kinds["concept"] == 148)
routes.search_entities_by_text = lambda q, kind=None, limit=20: [
    {"entity_id": "e1", "name": "QueryPlanner", "norm": "queryplanner", "kind": "method", "description": "", "mentions": 14}
]
found = routes.graph_search(q="Query", kind=None, limit=20)
check("搜索返回 GraphEntity", len(found) == 1 and found[0].name == "QueryPlanner")
routes.get_entity = lambda eid: {
    "entity_id": "e1", "name": "QueryPlanner", "norm": "queryplanner",
    "kind": "method", "description": "拆解问题", "mentions": 14,
}
routes.entity_edges = lambda eid, limit=50: {
    "out": [{"rel": "基于", "norm_rel": "based-on", "weight": 3.0, "entity_id": "e2", "name": "ReCite", "kind": "concept", "evidence_chunk_id": None}],
    "in": [],
}
routes.entity_evidence_chunks = lambda eid, limit=10: [
    {"chunk_id": "c1", "document_id": "d1", "doc_name": "RAG.pdf", "chunk_index": 150, "text": "…", "metadata": {"page": 7}}
]
detail = routes.graph_entity_detail("e1")
check("实体详情含边", len(detail.out_edges) == 1 and detail.out_edges[0].norm_rel == "based-on")
check("证据切片带 page", detail.evidence[0].page == 7)
routes.graph_subgraph = lambda ids, hops=2, limit=150: {
    "nodes": [{"entity_id": "e1", "name": "QueryPlanner", "kind": "method", "mentions": 14, "hop": 0}],
    "edges": [],
}
sub = routes.graph_subgraph_view("e1", hops=2, limit=150)
check("子图返回节点", len(sub.nodes) == 1 and sub.nodes[0].hop == 0)

print("\n[5] 评测端点装配与空集保护")
routes.load_eval_cases = lambda: [
    {"id": 1, "question": "q", "expected_refs": "RAG.pdf:155", "reference_answer": None, "expected": {"RAG.pdf:155"}}
]
cases = routes.eval_cases()
check("评测例序列化", len(cases) == 1 and cases[0].expected_refs == "RAG.pdf:155")
routes.run_ablation = lambda configs, top_k=5: [{"label": "纯向量", "hit@k": 0.5, "mrr": 0.31}]
result = routes.eval_run(routes.EvalRunRequest(k=5))
check("消融结果字段映射", result.rows[0].hit_at_k == 0.5 and result.rows[0].mrr == 0.31)
routes.load_eval_cases = lambda: []
try:
    routes.eval_run(routes.EvalRunRequest(k=5))
    check("空评测集应报 400", False, "未抛异常")
except Exception as exc:  # noqa: BLE001
    check("空评测集报 400", getattr(exc, "status_code", None) == 400, str(getattr(exc, "detail", exc)))
check("默认配置矩阵非空", len(routes._default_eval_configs()) >= 4)

print("\n[6] retrieval.debug 分支：trace 装配 + 默认路径不受影响")
import src.retrieval as retrieval  # noqa: E402
import src.ingestion.embedder as embedder  # noqa: E402
import src.graph as graph_mod  # noqa: E402


class _StubEmbedder:
    def encode(self, texts):
        return [[float(index + 1)] for index, _ in enumerate(texts)]


embedder.get_embedder = lambda *a, **k: _StubEmbedder()
retrieval.extract_terms = lambda question: ["关键词"]

PLAN_WITH_OUTPUT = {
    "subs": ["子问题一", "子问题二"],
    "step_back": "更宽泛的概念问题",
    "hyde": "假设的文档段落" * 8,
}
PLAN_EMPTY = {"subs": [], "step_back": None, "hyde": None}
retrieval.plan_question = lambda question: dict(PLAN_WITH_OUTPUT)


def _fake_two_stage_search(vector, top_k, terms, filters=None, use_routing=True, stats=None):
    base = int(vector[0]) * 10
    rows = [
        {"chunk_id": f"c{base + i}", "doc_name": "RAG.pdf", "chunk_index": i, "text": "片段", "metadata": {}}
        for i in range(3)
    ]
    if stats is not None:
        # 每次调用都路由到同样的两篇文档，用于验证「按文档去重」而不是按查询累加
        stats.setdefault("route_top_score", 0.61)
        stats.setdefault("route_fallback", False)
        stats.setdefault("routed_doc_ids", set()).update({"doc-a", "doc-b"})
        stats["keywords"] = stats.get("keywords", 0) + (1 if terms else 0)
        stats["vector"] = stats.get("vector", 0) + len(rows)
    return rows


retrieval.two_stage_search = _fake_two_stage_search
graph_mod.graph_channel = lambda vector, top_k, filters=None: [
    {"chunk_id": "g1", "doc_name": "RAG.pdf", "chunk_index": 99, "text": "图谱", "metadata": {}}
]

full = ["routing", "keywords", "decompose", "stepback", "hyde", "graph"]
out = retrieval.multi_query_search("问题", 5, features=full, debug=True)
trace = out["trace"]
check("返回 dict 且含 results/trace", isinstance(out, dict) and "results" in out and "trace" in out)
check("查询集合 = 原问题+2子问题+退步", len(trace["plan"]["queries"]) == 4, str(trace["plan"]["queries"]))

channel_names = [c["name"] for c in trace["channels"]]
check(
    "通道是真实通道（不再是 primary/expanded）",
    channel_names == ["routing", "keywords", "vector", "hyde", "graph"],
    str(channel_names),
)
check("路由命中按文档去重而非按查询累加", trace["channels"][0]["hits"] == 2, f"hits={trace['channels'][0]['hits']}")
# 检索调用共 5 次：主查询 + 3 条扩展（2 子问题 + 1 退步）+ HyDE；HyDE 那次不传关键词
check("关键词只统计真正带关键词的调用", trace["channels"][1]["hits"] == 4, f"hits={trace['channels'][1]['hits']}")
check("向量块数跨调用累加（5 次 × 3 行）", trace["channels"][2]["hits"] == 15, f"hits={trace['channels'][2]['hits']}")

check("applied = 请求的全部 6 项", sorted(trace["applied"]) == sorted(full), str(trace["applied"]))
check("无空转项时 skipped 为空", trace["skipped"] == [], str(trace["skipped"]))
check("params 透出 top_k", trace["params"]["top_k"] == 5)
check("params 透出 filters", trace["params"]["filters"] == {})
check(
    "routing 判定块完整",
    trace["routing"]["routed_docs"] == 2 and trace["routing"]["fallback"] is False and trace["routing"]["min_score"] > 0,
    str(trace["routing"]),
)
check("pre_merge 去重生效", trace["fusion"]["pre_merge"] < 12 + 3 + 1, f"pre_merge={trace['fusion']['pre_merge']}")
check("final = top_k", trace["fusion"]["final"] == 5, str(trace["fusion"]["final"]))
check("rerank 未启用时为 None", trace["fusion"]["rerank"] is None)
check("timings 含三段", {"plan_ms", "retrieve_ms", "generate_ms"} <= set(trace["timings"]))

# routes.py 里是 QueryTrace(**trace_data)，这里等价校验一次，避免字段漂移
from src.api.schemas import QueryTrace  # noqa: E402

try:
    model = QueryTrace(**trace)
    check("trace 能通过 QueryTrace 校验", model.params.top_k == 5 and len(model.channels) == 5, f"channels={len(model.channels)}")
    check("skipped 序列化为 TraceSkip", isinstance(model.skipped, list))
except Exception as exc:  # noqa: BLE001
    check("trace 能通过 QueryTrace 校验", False, f"{type(exc).__name__}: {str(exc)[:140]}")

# 关键回归：规划无输出时，规划类特性必须落到 skipped 并给出原因，而不是伪装成「生效」
retrieval.plan_question = lambda question: dict(PLAN_EMPTY)
empty_trace = retrieval.multi_query_search("问题", 5, features=full, debug=True)["trace"]
skipped_names = {item["name"] for item in empty_trace["skipped"]}
check("规划空转时三项进 skipped", {"decompose", "stepback", "hyde"} <= skipped_names, str(sorted(skipped_names)))
check("skipped 每项都带原因", all(item["reason"] for item in empty_trace["skipped"]))
check("空转特性不出现在 applied", "decompose" not in empty_trace["applied"], str(empty_trace["applied"]))
retrieval.plan_question = lambda question: dict(PLAN_WITH_OUTPUT)

# 请求级重排策略覆盖
rerank_trace = retrieval.multi_query_search("问题", 3, features=["routing", "rerank"], debug=True, rerank_strategy="rrf")["trace"]
check("请求级 rerank 策略被采纳", rerank_trace["params"]["rerank_strategy"] == "rrf", str(rerank_trace["params"]))
check("rerank 生效时 applied 含 rerank", "rerank" in rerank_trace["applied"], str(rerank_trace["applied"]))

plain = retrieval.multi_query_search("问题", 5, features=["routing"])
check("debug=False 返回 list（契约不变）", isinstance(plain, list), type(plain).__name__)
check(
    "debug=False 返回带 score 的融合结果",
    0 < len(plain) <= 5 and all("score" in row for row in plain),
    f"{len(plain)} 条",
)

print("\n[7] 图谱构建入口仍在（CLI 未被破坏）")
check("graph.build 可调用", callable(getattr(graph_mod, "build", None)))
check("graph.graph_channel 存在", callable(getattr(graph_mod, "graph_channel", None)))

print("\n" + "=" * 56)
if failures:
    print(f"失败 {len(failures)} 项：")
    for item in failures:
        print("  -", item)
    sys.exit(1)
print("全部通过 ✓")
