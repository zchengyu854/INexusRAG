"""GraphRAG P1：局部知识图谱检索（第 4 条检索通道）。

实体/关系从切片中经 LLM 抽取，落在 database.py 的 entities/relations/chunk_entities 表；
查询侧用问题向量定位实体锚点，≤2 跳扩展后落回切片（graph_chunks）。
"""
from __future__ import annotations

import argparse
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

from src.ingestion.embedder import get_embedder
from src.llm.client import get_llm
from src.storage.database import (
    add_relation,
    chunk_has_entities,
    get_entity_by_norm,
    get_chunks_for_graph,
    graph_chunks,
    graph_stats,
    link_chunk_entities,
    list_documents,
    reset_graph,
    search_entities,
    upsert_entity,
)

ANCHOR_TOP = 5            # 查询侧取几个实体锚点
MIN_ANCHOR_SCORE = 0.5   # 锚点余弦阈值  # ponytail: 未校准，观测到漏检后调
MERGE_SCORE = 0.92       # 实体 ANN 合并阈值  # ponytail: 未校准
HOPS = 2

ENTITY_KINDS = ("concept", "product", "metric", "method", "person", "org", "other")

# 谓词白名单（双语）：10 个规范词，中英同义词收敛到同一规范词；
# 不在白名单的关系（如 是/is/has/shows）归一为 "" 直接丢弃（抽取噪声）
_REL_ALIASES = {
    "使用": "uses", "采用": "uses", "用到": "uses", "利用": "uses",
    "uses": "uses", "use": "uses", "using": "uses", "used": "uses",
    "utilizes": "uses", "employs": "uses", "leverages": "uses",
    "包括": "includes", "包含": "includes", "涵盖": "includes", "含有": "includes",
    "includes": "includes", "include": "includes", "contains": "includes",
    "consists-of": "includes", "comprises": "includes",
    "属于": "is-a", "是一种": "is-a", "is-a": "is-a", "is-an": "is-a", "belongs-to": "is-a",
    "基于": "based-on", "建立在": "based-on", "based-on": "based-on", "builds-on": "based-on",
    "依赖": "depends-on", "取决于": "depends-on", "depends-on": "depends-on",
    "relies-on": "depends-on", "requires": "depends-on",
    "提升": "improves", "提高": "improves", "优于": "improves",
    "improves": "improves", "improve": "improves", "outperforms": "improves", "increases": "improves",
    "实现": "implements", "implements": "implements", "implements-via": "implements",
    "评估": "evaluates-with", "用…评测": "evaluates-with", "evaluates-with": "evaluates-with",
    "evaluated-on": "evaluates-with", "measured-by": "evaluates-with",
    "对比": "compares-with", "相比": "compares-with", "compares-with": "compares-with",
    "compared-to": "compares-with", "versus": "compares-with",
    "生成": "produces", "产出": "produces", "produces": "produces",
    "generates": "produces", "outputs": "produces",
}
# 规范词列表（供 schema 提示模型直接选用，而非自行发明谓词）
_CANONICAL_RELS = tuple(dict.fromkeys(_REL_ALIASES.values()))

_PUNCT = "，。、,.;:：；！？!?()（）[]【】\"'“”"
_CJK_WS = re.compile(r"(?<=[\u4e00-\u9fff])\s+|\s+(?=[\u4e00-\u9fff])")
_TEXT_CAP = 1200  # 抽取输入截断，控制 LLM 成本
_EXTRACT_WORKERS = 3  # 抽取并发度：上游限流偏紧，8 路会触发 429
_EXTRACT_BATCH = 32   # 每多少块落一次库（中断续跑的最小粒度）
_RETRY_BACKOFF = (2, 8)  # 秒：限流/瞬时故障的退避重试；不宜过长，否则限流持续时失败批要拖很久才报错


def normalize_name(name: str) -> str:
    """实体名归一：NFKC 全角→半角、casefold、CJK 两侧的空白删除、其余空白连串折成一个、去首尾标点。"""
    s = unicodedata.normalize("NFKC", str(name)).strip().casefold()
    s = _CJK_WS.sub("", s)
    s = " ".join(s.split())
    return s.strip(_PUNCT)


def norm_relation(rel: str) -> str:
    """谓词归一：别名收敛到白名单规范词，不在白名单返回 ""。"""
    key = unicodedata.normalize("NFKC", str(rel)).casefold().strip()
    return _REL_ALIASES.get(key, "")


# function-calling 抽取 schema：只留对检索有用的实体与短动词短语关系
_EXTRACT_TOOL: dict = {
    "name": "extract_graph",
    "description": "从一段文本中抽取有检索价值的实体与关系",
    "parameters": {
        "type": "object",
        "properties": {
            "entities": {
                "type": "array",
                "description": (
                    "文本可能是中文或英文。提取文中**所有**能作为检索锚点的技术实体：方法、模型、模块、数据集、"
                    "指标、系统/工具、组织、关键概念。通常一段 500~1200 字的学术文本有 5~15 个，"
                    "不要只挑一两个最重要的。保留专名原形（如 CiteLocator、CAP-8、S2ORC、Qwen3-4B、Strict F1）。"
                    "跳过：系统/方法/内容/信息/system/method/approach 等泛化词、纯数字、参考文献列表里的作者姓名。没有则 []"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "实体名（保持原文写法）"},
                        "kind": {"type": "string", "enum": list(ENTITY_KINDS), "description": "实体类型"},
                        "description": {"type": "string", "description": "不超过 20 字的中文短语，说明该实体在此文中指什么"},
                    },
                    "required": ["name", "kind", "description"],
                },
            },
            "relations": {
                "type": "array",
                "description": (
                    "实体间关系；src/dst 必须是 entities 中出现的实体名。"
                    "同一段落里实体间往往有多个可推断的关系（如 X 用 Y 评测、X 基于 Y、X 优于 Y），尽量抽全；没有则 []"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "src": {"type": "string", "description": "源实体名"},
                        "rel": {"type": "string", "description": (
                            "必须从这些规范词中选一个：" + "/".join(_CANONICAL_RELS)
                        )},
                        "dst": {"type": "string", "description": "目标实体名"},
                    },
                    "required": ["src", "rel", "dst"],
                },
            },
        },
        "required": ["entities", "relations"],
    },
}


def extract_graph(text: str) -> dict:
    """单切片抽取；LLM 不可用/调用失败/输出畸形时返回空结构（抽取失败绝不抛错）。

    限流很常见（长构建必遇），故退避重试；仍失败才返回空。
    """
    empty = {"entities": [], "relations": []}
    llm = get_llm()
    if not llm.enabled:
        return empty
    data = None
    for delay in (0, *_RETRY_BACKOFF):
        if delay:
            time.sleep(delay)
        try:
            data = llm.tool_call(f"请从以下文本中抽取实体与关系。\n{text[:_TEXT_CAP]}", _EXTRACT_TOOL)
            break
        except Exception:
            data = None
    if not isinstance(data, dict):
        return empty

    entities: list[dict] = []
    seen: set[str] = set()
    for item in data.get("entities") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        norm = normalize_name(name)
        if len(norm) < 2 or norm.isdigit():  # 过短/纯数字无检索价值
            continue
        kind = item.get("kind")
        entities.append({
            "name": name,
            "kind": kind if kind in ENTITY_KINDS else "other",
            "description": str(item.get("description", "")).strip()[:20],
        })
        seen.add(norm)

    relations: list[dict] = []
    for item in data.get("relations") or []:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("rel", "")).strip()
        if not norm_relation(rel):
            continue
        src = normalize_name(str(item.get("src", "")))
        dst = normalize_name(str(item.get("dst", "")))
        if not src or not dst or src not in seen or dst not in seen:
            continue
        relations.append({"src": src, "rel": rel, "dst": dst})
    return {"entities": entities, "relations": relations}


def resolve_entity(name: str, kind: str, description: str, embedding: list[float]) -> str:
    """实体消歧：norm 精确命中 → 语义近邻合并（阈值+kind 双校验）→ 新建。"""
    row = get_entity_by_norm(normalize_name(name))
    if row:
        return row["entity_id"]
    # embedding 为空说明该名已被建过（batch 编码只覆盖新实体），此路径不该走到；兜底防维度报错
    hits = search_entities(embedding, 1) if embedding else []
    if hits and hits[0]["score"] >= MERGE_SCORE and hits[0]["kind"] == kind:
        return hits[0]["entity_id"]
    return upsert_entity(name, normalize_name(name), kind, description, embedding)


def build_document(doc_id: str, resume: bool = True) -> int:
    """逐切片建图（抽取 → 消歧 → 加边 → 连线），返回本次处理的切片数。

    分批并发 + 每批落库：全篇抽完再统一落库的写法一旦中断会白烧全部 LLM 成本（490 块约半小时），
    所以每 _EXTRACT_BATCH 块就写一次，配合 resume 跳过已连线切片，中断后重跑即可续上。
    """
    chunks = [c for c in get_chunks_for_graph(doc_id) if c["text"].strip()]
    if resume:
        chunks = [c for c in chunks if not chunk_has_entities(c["chunk_id"])]
    if not chunks:
        return 0
    embedder = get_embedder()
    processed = 0
    for start in range(0, len(chunks), _EXTRACT_BATCH):
        batch = chunks[start:start + _EXTRACT_BATCH]
        with ThreadPoolExecutor(max_workers=_EXTRACT_WORKERS) as pool:
            extracted = list(pool.map(lambda c: (c, extract_graph(c["text"])), batch))
        for chunk, graph_data in extracted:
            _store_chunk(chunk, graph_data, embedder)
            processed += 1
        # 整批全空几乎只可能是限流/故障；不能静默写出一张空图（否则 12 分钟的构建
        # “成功”但产物无意义，且消融会得出“图检索没用”的假结论）
        if extracted and not any(g["entities"] for _, g in extracted):
            raise RuntimeError(
                f"连续 {len(extracted)} 块抽取均为空，判定为 LLM 限流/故障（非文本本身无实体）。"
                "已保留此前批次的进度，稍后用 --resume 续跑。"
            )
    return processed


def _store_chunk(chunk: dict, graph_data: dict, embedder) -> None:
    """单切片落库：本块新实体一次性编码，再逐个消歧、加边、连线。"""
    entities = graph_data["entities"]
    norms = [normalize_name(ent["name"]) for ent in entities]
    fresh = [norm for norm in dict.fromkeys(norms) if get_entity_by_norm(norm) is None]
    vectors = dict(zip(fresh, embedder.encode(fresh))) if fresh else {}

    idmap: dict[str, str] = {}
    for norm, ent in zip(norms, entities):
        idmap[norm] = resolve_entity(ent["name"], ent["kind"], ent["description"], vectors.get(norm, []))
    for rel in graph_data["relations"]:
        src_id, dst_id = idmap.get(rel["src"]), idmap.get(rel["dst"])
        if src_id and dst_id:
            add_relation(src_id, dst_id, rel["rel"], norm_relation(rel["rel"]), chunk["chunk_id"])
    link_chunk_entities(chunk["chunk_id"], list(idmap.values()))


def build(doc_names: list[str] | None = None, resume: bool = False) -> dict:
    """重建图谱；resume=True 时不重置、跳过已连线切片（用于分片续跑，见 build_document）。

    doc_names 接受 filename 或 doc id，None = 全部文档。
    """
    if not resume:
        reset_graph()
    wanted = set(doc_names) if doc_names is not None else None
    targets = [d for d in list_documents() if wanted is None or d["filename"] in wanted or d["id"] in wanted]
    chunks_total = 0
    for doc in targets:
        chunks_total += build_document(doc["id"], resume=resume)
    return {"documents": len(targets), "chunks": chunks_total, **graph_stats()}


def graph_channel(question_vector: list[float], top_k: int, filters: dict | None = None) -> list[dict]:
    """图通道：问题向量 → 实体锚点（余弦≥阈值）→ ≤HOPS 跳 → 切片；无锚点或出错返回 []。"""
    try:
        anchors = [
            e for e in search_entities(question_vector, ANCHOR_TOP)
            if e["score"] >= MIN_ANCHOR_SCORE
        ]
        if not anchors:
            return []
        return graph_chunks([a["entity_id"] for a in anchors], hops=HOPS, limit=top_k, filters=filters)
    except Exception:
        return []


def main() -> None:
    parser = argparse.ArgumentParser(description="知识图谱构建与统计")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_build = sub.add_parser("build", help="重建图谱")
    p_build.add_argument("--doc", action="append", help="只重建指定文档（filename 或 doc id），可多次")
    p_build.add_argument("--resume", action="store_true", help="不重置并跳过已连线的切片（断点续跑）")
    sub.add_parser("stats", help="图谱统计")
    sub.add_parser("reset", help="清空图谱")
    args = parser.parse_args()
    if args.cmd == "build":
        print(build(args.doc, resume=args.resume))
    elif args.cmd == "stats":
        print(graph_stats())
    else:
        reset_graph()
        print("已清空图谱")


if __name__ == "__main__":
    main()
