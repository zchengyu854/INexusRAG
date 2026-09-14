"""混合检索：向量通道 + 关键词通道，RRF（倒数排名融合）合并；复杂问题多查询分解。"""
from __future__ import annotations

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import jieba

from src.storage.database import keyword_chunks, search_chunks, search_doc_index, upsert_doc_index

# 提问里常见的无检索价值词（jieba 精确命中才过滤）
_JUNK = set((
    "的 了 吗 呢 啊 吧 么 是 在 有 和 与 或 及 着 被 把 对 向 于 从 到 "
    "什么 怎么 如何 哪些 哪个 为什么 可以 能否 是否 这个 那个 一个 我们 你们 他们 你 我"
    "条是 个是 个有"
).split())
_ASCII = re.compile(r"[0-9A-Za-z]")
_CJK = re.compile(r"[\u4e00-\u9fff]+\Z")
# 句尾疑问/修辞后缀：jieba 会把 "条是什么" 切成 ["条是", "什么"]， both 过滤后仍漏 "条是"；
# 预处理直接抹掉这类后缀及其后的标点，减少对关键词通道的污染。
_QUESTION_SUFFIXES = re.compile(r"(?:是什么|是多少|有哪些|是什么东西|怎么样|行吗|对吗|吗|呢|吧|啊|么)[^A-Za-z0-9\u4e00-\u9fff]*$")
# 页码引用（如「第4页」「第 12 页」「第四页」）：jieba 会把它切碎，需整段抽出当关键词
_PAGE_REF = re.compile(r"第\s*[0-9一二三四五六七八九十百千]+\s*页")


def extract_terms(question: str, max_terms: int = 12) -> list[str]:
    """从问题中提取关键词：结构化引用（页码/法条）+ jieba 分词，去掉停用词、单字与疑问后缀。

    结构化引用要先抽：jieba 会把「第4页」切成 第/4/页、「第二百三十条」切成 二百三十/条，
    切碎后要么被单字规则滤掉、要么丢掉「第…条/页」这个决定性的边界信息。这类 token
    在语料里是强信号（只有少数切片含「第4页」），直接按正则整段取出才能命中。
    """
    cleaned = _QUESTION_SUFFIXES.sub("", question)
    terms: list[str] = []
    seen: set[str] = set()

    def _add(token: str) -> bool:
        if token and token not in seen:
            seen.add(token)
            terms.append(token)
        return len(terms) >= max_terms

    for match in _PAGE_REF.finditer(cleaned):
        if _add(re.sub(r"\s+", "", match.group(0))):
            return terms

    for token in jieba.lcut(cleaned):
        token = token.strip()
        if len(token) < 2 or token in _JUNK:
            continue
        if not (_ASCII.search(token) or _CJK.match(token)):
            continue
        if _add(token):
            break
    return terms


# 同义词组：组内任一词命中即视为该概念命中。
# 典型场景：问「第4页的插图是什么」而切片里写的是「（图片）」，只按字面匹配永远召回不到。
# 关键词通道与相关性过滤共用这张表——只扩召回不过滤，扩出来的候选仍会被过滤掉。
_SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("插图", "图片", "配图", "图注", "图示", "figure", "figures", "illustration", "illustrations"),
    ("条文", "法条", "条款"),
    ("作者", "著者", "撰稿人"),
    ("摘要", "概述", "梗概"),
    ("数据集", "语料", "语料库"),
    ("参考文献", "引用文献", "参考书目"),
    ("模型", "大模型"),
)

_SYNONYM_LOOKUP: dict[str, tuple[str, ...]] = {}
for _group in _SYNONYM_GROUPS:
    for _word in _group:
        _SYNONYM_LOOKUP.setdefault(_word.lower(), _group)
del _group, _word


def synonym_group(term: str) -> tuple[str, ...]:
    """返回该词所属的同义词组；无同义词时返回只含自身的单元素组。"""
    return _SYNONYM_LOOKUP.get(term.lower(), (term,))


def expand_terms(terms: list[str]) -> list[str]:
    """把关键词展开出同义词（去重保序），供关键词通道使用。"""
    expanded: list[str] = []
    for term in terms:
        for variant in synonym_group(term):
            if variant not in expanded:
                expanded.append(variant)
    return expanded


def search_terms(question: str) -> list[str]:
    """检索用关键词：分词后再展开同义词。multi_query_search 与 agent 工具共用。"""
    return expand_terms(extract_terms(question))


def rrf_merge(channels: list[list[dict]], top_k: int, k: int = 60) -> list[dict]:
    """RRF 融合多个有序结果通道，返回带融合分的行（按 chunk_id 去重）。

    同时保留每个 chunk 的最佳向量余弦分（vector_score），供后续相关性阈值过滤使用。
    关键词通道没有向量分（视为 0.0），靠精确命中保命。
    """
    scores: dict[str, float] = {}
    rows: dict[str, dict] = {}
    vector_scores: dict[str, float] = {}
    for channel in channels:
        for rank, row in enumerate(channel):
            key = row["chunk_id"]
            rows.setdefault(key, row)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            # vector_score 已存在则复用（来自 two_stage_search 的二次融合），否则取当前 score（cosine）
            vector_scores[key] = max(
                vector_scores.get(key, 0.0),
                row.get("vector_score") if row.get("vector_score") is not None else row.get("score", 0.0),
            )
    ranked = sorted(scores, key=scores.get, reverse=True)[:top_k]
    return [dict(rows[key], score=round(scores[key], 6), vector_score=round(vector_scores[key], 6)) for key in ranked]


# 纯数字串作为查询词时召回太宽泛（如 "230" 会命中体育赔率、页码等），
# 不能单独作为 coverage 依据，需要配合向量分阈值或非数字实体词。
_PURE_NUMBER = re.compile(r"^[0-9]+$")
# 对 bge-m3 余弦分实测：无相关实体的查询约 0.40–0.45，相关查询通常 > 0.50。
_MIN_RELEVANCE_SCORE = 0.45
# 完整法条编号（如 '第二百三十条' / '第230条'）：带 '第…条' 边界，比 extract_terms 切出的
# '二百三十' 更精确——'第一千二百三十条' 是 '一' + '千二百三十条'，并不包含子串 '第二百三十条'，
# 因此套上边界后可排除同数字串污染。
_ARTICLE_RE = re.compile(r"第[一二三四五六七八九十百千零两0-9]+条")
# 用户常省略 '第'（如 "民法典的二百三十条"），补回 '第' 还原成规范法条串再做精确匹配。
# 仅接受含 百/千/十 或长度≥2 的中文数字串 + 条，避免把 '一条鱼' 这类量词误当法条。
# 负向后查同时排除阿拉伯数字与中文数字，避免 "第二百三十条" 内部的 "百三十条" 被重复截取成 "第百三十条"。
_ARTICLE_NO_LEAD_RE = re.compile(
    r"(?<!第)(?<![0-9一二三四五六七八九十百千零两])((?:[一二三四五六七八九十百千零两]*[百千万][一二三四五六七八九十百千零两]*|[一二三四五六七八九十百千零两]{2,})条)"
)


def _extract_article_terms(question: str) -> list[str]:
    """从问题中提取完整法条编号字符串（带 '第…条' 边界）。

    用于精确匹配，避免 extract_terms 切出的 '二百三十' 误命中 '第一千二百三十条' 这类同数字串。
    查询省略 '第' 时（"二百三十条"）会自动补成 '第二百三十条' 再匹配。
    """
    cleaned = _QUESTION_SUFFIXES.sub("", question)
    found: list[str] = list(_ARTICLE_RE.findall(cleaned))
    for m in _ARTICLE_NO_LEAD_RE.findall(cleaned):
        found.append("第" + m)
    # 去重保序
    return list(dict.fromkeys(found))


def _extract_page_terms(question: str) -> list[str]:
    """从问题中提取页码引用（如「第4页」「第 12 页」）。"""
    cleaned = _QUESTION_SUFFIXES.sub("", question)
    return [re.sub(r"\s+", "", match.group(0)) for match in _PAGE_REF.finditer(cleaned)]


def _extract_ref_terms(question: str) -> list[str]:
    """结构化引用：法条编号 + 页码。

    两者共性极强——在语料里都近乎「命中即唯一」（实测「第4页」只命中 1 块切片），
    所以给它们单独一档，避免被普通语义词的高频匹配淹没。
    """
    return list(dict.fromkeys(_extract_article_terms(question) + _extract_page_terms(question)))


def inject_ref_channel(question: str, merged: list[dict], top_k: int) -> list[dict]:
    """结构化引用精确通道：把「第二百三十条」「第4页」这类唯一命中的切片补进候选集。

    让相关性过滤能优先返回它，避免被向量通道/高频语义词排在前面的同数字串
    （如「第一千二百三十条」）或其它页的图片块挤掉。仅当问题含此类引用时生效。
    multi_query_search 与 agent 的 search_knowledge 工具共用，保证两条范式行为一致。
    """
    ref_terms = _extract_ref_terms(question)
    if not ref_terms:
        return merged
    injected = keyword_chunks(ref_terms, limit=max(top_k * 5, 25))
    if injected:
        seen_ids = {r["chunk_id"] for r in merged}
        for r in injected:
            if r["chunk_id"] not in seen_ids:
                r.setdefault("vector_score", 0.0)
                merged.append(r)
    return merged


def rewrite_query(question: str) -> str:
    """检索友好的查询改写（确定性，无需 LLM，永远在线）：

    1) 去掉句尾疑问/修辞后缀（避免「是什么」参与向量召回稀释语义）；
    2) 归一法条编号为带「第…条」边界的规范串；
    3) 用实体词 + 法条串拼接待检索查询，剔除纯数字噪声词。

    改写只在能提取到有效实体/法条时生效，否则返回原查询，避免画蛇添足。
    这是针对 bge-m3 模糊性的核心兜底：原问题「民法典的二百三十条是什么？」经 embedding
    后会被判为与「第一千二百三十条」高度相似；改写为「民法典 第二百三十条」后向量通道才能
    精准命中，配合 _extract_article_terms 注入的关键词通道形成「向量 + 精确」双保险。

    例：
      '民法典的二百三十条是什么？' -> '民法典 二百三十 第二百三十条'
      'RAG 是什么'                -> 'RAG'   （去后缀，无实体可补）
      '你好'                      -> '你好'  （无实体/法条，原样）
    """
    terms = [t for t in extract_terms(question) if not _PURE_NUMBER.match(t)]
    articles = _extract_article_terms(question)
    if not terms and not articles:
        return question
    # 实体词在前、法条串在后，去重保序
    parts = list(dict.fromkeys(terms + articles))
    return " ".join(parts)


def _relevance_filter(results: list[dict], question: str) -> list[dict]:
    """相关性过滤：分三档精确匹配，最后才退回向量分阈值。

    匹配优先级（命中即返回该档）：
      1) 实体词 + 结构化引用（法条编号/页码）全部命中（最精确）；
      2) 仅结构化引用命中（法条编号与页码在语料里近乎唯一命中，如「第4页」只对应 1 块）；
      3) 仅实体词命中（容忍法条编号写法差异，如 '第二百三十条' vs '第230条'）；
      — 以上皆无全命中时，看向量余弦最高分：≥ 阈值则保留，否则清空（防止 LLM 基于噪声幻觉）。

    匹配以「同义词组」为单位：组间 AND、组内 OR。这样问「插图」而切片写「图片」也能算命中，
    否则同义词扩召回出来的候选紧接着又会被这里滤掉。无同义词的词自成单元素组，
    与改动前的全词 AND 语义完全一致。

    典型场景：
    - 问"民点发的230条"，知识库没有"民点"，向量靠"230"捞出体育赔率等噪声 → 清空。
    - 问"民法典的二百三十条"，最相关切片（#21/#50）未排第一；第 1 档 AND 过滤可去掉只含"民法典"
      但不含"二百三十"的通用切片（#0），显著降低 hallucination。
    - 第 2 档法条边界可排除"第一千二百三十条"：'第二百三十条' 不是 '第一千二百三十条' 的子串，
      因此错误法条不会被同数字串卷进来。
    """
    if not results:
        return results
    terms = [t for t in extract_terms(question) if not _PURE_NUMBER.match(t)]
    refs = _extract_ref_terms(question)
    if not terms and not refs:
        return results
    term_groups = [synonym_group(t) for t in terms]
    ref_groups = [(r,) for r in refs]

    def covers(row: dict, groups: list[tuple[str, ...]]) -> bool:
        """每个同义词组至少命中一个变体（组内 OR、组间 AND）。"""
        text = row.get("text", "")
        return all(any(variant in text for variant in group) for group in groups)

    exact = [row for row in results if covers(row, term_groups + ref_groups)]
    if exact:
        return exact
    if ref_groups:
        # 结构化引用（法条 / 页码）近乎唯一命中，单独成档以免被高频语义词淹没
        exact_ref = [row for row in results if covers(row, ref_groups)]
        if exact_ref:
            return exact_ref
    if term_groups:
        exact_loose = [row for row in results if covers(row, term_groups)]
        if exact_loose:
            return exact_loose
    max_vector = max(row.get("vector_score", 0.0) for row in results)
    if max_vector >= _MIN_RELEVANCE_SCORE:
        return results
    return []


def build_routing_summary(filename: str, chunks: list) -> str:
    """机械式路由摘要：文件名 + 前两级标题 + 开头 200 字。"""
    headings: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        for heading in ((chunk.metadata or {}).get("heading_path") or [])[:2]:
            if heading not in seen:
                seen.add(heading)
                headings.append(heading)
    lines = [filename]
    if headings:
        lines.append("章节: " + " / ".join(headings[:15]))
    if chunks:
        lines.append("开头: " + chunks[0].text.strip()[:200])
    return "\n".join(lines)


def index_document_route(doc_id: str, doc_name: str, chunks: list, encode) -> None:
    """生成/更新文档路由条目（ingest 与 rechunk 后调用）。"""
    summary = build_routing_summary(doc_name, chunks)
    upsert_doc_index(doc_id, doc_name, summary, encode([summary])[0])


_ROUTE_TOP = 3
# 路由置信度不足时走全局向量（不再同时扫路由文档，避免「兜底常开 + 错文档通道」双倍开销）。
# 校准（2026-09-11，8 篇文档 / 7077 切片 / bge-m3 1024 维，脚本 scripts/calibrate_thresholds.py）：
# 查询路由 top-1 分数实测落在 0.296–0.660（中位 0.497），且全局兜底通道在每一档阈值上
# 都提升召回——阈值从 0.30 提到 0.70，三个独立评测集上的变化是
# 段落查询(n=120) Hit@5 57%→88%、首句查询(n=71) 44%→69%、手写查询(n=32) MRR 0.678→0.932。
# 也就是说这个阈值的最优解是「兜底常开」：路由一次取 3 篇、其中往往 2 篇是错的，
# 少了全局通道，正确切片在 RRF 里会被错误文档的并列第一压掉。
# 0.70 取在实测最大值之上，等价于兜底常开；此时跳过 per-doc 扫描（否则 3 路错文档 + 1 路全局）。
# 仅当 top-1 ≥ 阈值时才做文档内检索。换语料或换 embedding 后重跑校准脚本再调。
_MIN_ROUTE_SCORE = 0.70


def two_stage_search(
    query_embedding: list[float],
    top_k: int,
    terms: list[str],
    filters: dict | None = None,
    use_routing: bool = True,
    stats: dict | None = None,
) -> list[dict]:
    """两级检索：先路由命中目标文档，再在目标文档内检索；关键词通道全局兑底。use_routing=False 时只做全局向量检索。

    路由 top-1 < 阈值时只跑全局向量（不叠加 per-doc），避免常开兜底下的冗余 ANN。
    stats 为可选的出参字典，仅在需要观测时传入（用于 /api/query 的 debug trace）。
    传 None 时全部记账代码被跳过，检索路径与不传时完全一致。
    """
    limit = max(top_k * 5, 25)
    channels: list[list[dict]] = []
    lock = stats.get("_lock") if stats is not None else None

    def _bump(key: str, n: int) -> None:
        if stats is None:
            return
        if lock is not None:
            with lock:
                stats[key] = stats.get(key, 0) + n
        else:
            stats[key] = stats.get(key, 0) + n

    if terms:
        keyword_rows = keyword_chunks(terms, limit=limit, filters=filters)
        _bump("keywords", len(keyword_rows))
        channels.append(keyword_rows)
    if not use_routing:
        vector_rows = search_chunks(query_embedding, top_k=limit, filters=filters)
        _bump("vector", len(vector_rows))
        channels.append(vector_rows)
        return rrf_merge(channels, top_k) if channels else []
    routed = search_doc_index(query_embedding, top_k=_ROUTE_TOP)
    if stats is not None:
        # 多查询时每条查询各自路由，这里按 doc_id 去重统计，避免「命中 8 篇文档」式的误读
        def _note_route() -> None:
            stats.setdefault("route_top_score", round(float(routed[0]["score"]), 4) if routed else 0.0)
            stats.setdefault("route_fallback", False)
            stats.setdefault("routed_doc_ids", set()).update(row["doc_id"] for row in routed)

        if lock is not None:
            with lock:
                _note_route()
        else:
            _note_route()
    top_score = float(routed[0]["score"]) if routed else 0.0
    if routed and top_score >= _MIN_ROUTE_SCORE:
        # 路由足够自信：只在命中文档内检索
        for row in routed:
            doc_rows = search_chunks(query_embedding, top_k=limit, doc_id=row["doc_id"], filters=filters)
            _bump("vector", len(doc_rows))
            channels.append(doc_rows)
    else:
        # 无命中，或置信不足：全局向量一路即可（不再叠加常错的 per-doc 通道）
        fallback_rows = search_chunks(query_embedding, top_k=limit, filters=filters)
        _bump("vector", len(fallback_rows))
        if stats is not None:
            if lock is not None:
                with lock:
                    stats["route_fallback"] = True
            else:
                stats["route_fallback"] = True
        channels.append(fallback_rows)
    if not channels:
        return []
    return rrf_merge(channels, top_k)


# function-calling 检索规划 schema：三项各带判据，LLM 按 schema 填参（不适用留空）
_PLAN_TOOL: dict = {
    "name": "plan_question",
    "description": "判断 subs/step_back/hyde 三项是否适用本题，不适用留 null/[]",
    "parameters": {
        "type": "object",
        "properties": {
            "subs": {
                "type": "array",
                "maxItems": 5,
                "description": "子问题：问题含多个子主题时拆成不超过 5 个可独立检索回答的具体子问题；已够具体则 []",
                "items": {"type": "string"},
            },
            "step_back": {
                "type": "string",
                "description": "退步概念问题：问题过于细节具体时，退一步写更宽泛的概念问题（答案需包含回答原问题的背景）；已够抽象则 null",
            },
            "hyde": {
                "type": "string",
                "description": "假想文档片段：150~300 字中文段落，描述回答该问题的文档会包含的关键信息（概念、术语、因果）；不直接答题；简单事实型问题置 null",
            },
        },
    },
}


def plan_question(question: str) -> dict:
    """检索规划：一次 LLM 调用（function calling 格式）决定子问题/退步抽象/HyDE 段落三项，让 LLM 自行门控。

    LLM 不可用或输出不合法时返回全空计划——检索永远不退化为失败。"""
    empty = {"subs": [], "step_back": None, "hyde": None}
    from src.llm.client import get_llm

    llm = get_llm()
    if not llm.enabled:
        return empty
    try:
        data = llm.tool_call(question, _PLAN_TOOL)
        subs = [str(s).strip() for s in data.get("subs", []) if str(s).strip()][:5]
        step = data.get("step_back")
        hyde = data.get("hyde")
        return {
            "subs": subs,
            "step_back": step.strip() if isinstance(step, str) and len(step.strip()) >= 8 else None,
            "hyde": hyde.strip() if isinstance(hyde, str) and len(hyde.strip()) >= 40 else None,
        }
    except Exception:
        return empty


ALL_FEATURES = ("routing", "keywords", "decompose", "stepback", "hyde", "rewrite", "rerank", "graph")
_DEFAULT_FEATURES = ("routing", "keywords", "decompose", "stepback", "hyde", "rewrite")  # rerank/graph 默认关，消融时显式传 features


def multi_query_search(
    question: str,
    top_k: int,
    filters: dict | None = None,
    features: list[str] | None = None,
    debug: bool = False,
    rerank_strategy: str | None = None,
) -> list[dict] | dict:
    """多查询：features 控制通道开关（None = 默认全开除 rerank）→ 两级检索 → RRF → 可选 rerank。

    debug=True 时返回 {"results": [...], "trace": {...}}，只为把过程暴露给检视面板，不重复跑检索。
    trace 区分「请求的」与「真正生效的」：applied 是实际起了作用的通道，空转或被降级的进 skipped
    并附原因（例如 LLM 未配置导致规划类特性失效），避免面板把空转的开关显示成生效。
    debug=False（默认）时不构建 trace、不记账，检索路径与改动前一致。
    """
    import time as _time

    from src.ingestion.embedder import get_embedder

    t_start = _time.perf_counter() if debug else 0.0
    requested = set(_DEFAULT_FEATURES) if features is None else set(features)
    wants_plan = bool({"decompose", "stepback", "hyde"} & requested)
    # 只有启用规划类特性才付 LLM 规划调用
    plan = plan_question(question) if wants_plan else {"subs": [], "step_back": None, "hyde": None}
    t_planned = _time.perf_counter() if debug else 0.0

    queries = [question]
    sub_queries: list[str] = []
    if "decompose" in requested:
        sub_queries = [s for s in plan["subs"] if s != question]
        queries += sub_queries
    step_back_used = bool("stepback" in requested and plan["step_back"] and plan["step_back"] != question)
    if step_back_used:
        queries.append(plan["step_back"])
    # 查询改写通道：把原问题归一为检索友好的规范查询（去后缀/归一法条/拼实体词），
    # 作为额外向量+关键词通道并入 RRF。确定性实现，不依赖 LLM，网关抽风也不影响。
    rewrite_used = bool("rewrite" in requested)
    rewritten = rewrite_query(question) if rewrite_used else question
    rewrite_applied = rewrite_used and rewritten != question
    if rewrite_applied:
        queries.append(rewritten)
    hyde_used = bool("hyde" in requested and plan["hyde"])
    encode_inputs = list(queries)
    if hyde_used:
        encode_inputs.append(plan["hyde"])
    all_vectors = get_embedder().encode(encode_inputs)
    vectors = all_vectors[: len(queries)]
    hyde_vec = all_vectors[len(queries)] if hyde_used else None
    use_routing = "routing" in requested
    # 仅 debug 时记账；传 None 会让 two_stage_search 跳过全部计数代码
    stats: dict | None = {"_lock": threading.Lock()} if debug else None

    def _search(query: str, vector: list[float], terms: list[str] | None = None) -> list[dict]:
        return two_stage_search(
            vector, top_k=top_k,
            terms=(search_terms(query) if terms is None and "keywords" in requested else (terms or [])),
            filters=filters, use_routing=use_routing, stats=stats,
        )

    jobs: list[tuple[str, list[float], list[str] | None]] = [
        (query, vector, None) for query, vector in zip(queries, vectors)
    ]
    if hyde_used and hyde_vec is not None:
        jobs.append((plan["hyde"], hyde_vec, []))

    graph_rows: list[dict] = []
    want_graph = "graph" in requested
    workers = min(4, max(1, len(jobs) + (1 if want_graph else 0)))

    def _run_job(job: tuple[str, list[float], list[str] | None]) -> list[dict]:
        query, vector, terms = job
        return _search(query, vector, terms)

    if workers == 1 and not want_graph:
        channels = [_run_job(jobs[0])] if jobs else []
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            graph_future = None
            if want_graph:
                from src.graph import graph_channel
                graph_future = pool.submit(
                    graph_channel, vectors[0], max(top_k * 5, 25), filters
                )
            channels = list(pool.map(_run_job, jobs))
            if graph_future is not None:
                graph_rows = graph_future.result()
                channels.append(graph_rows)
    hyde_rows: list[dict] = channels[len(queries)] if hyde_used else []
    t_retrieved = _time.perf_counter() if debug else 0.0

    merged = rrf_merge(channels, top_k if "rerank" not in requested else top_k * 5)
    if "keywords" in requested:
        merged = inject_ref_channel(question, merged, top_k)
    merged = _relevance_filter(merged, question)
    fused_count = len(merged) if debug else 0
    rerank_used = False
    effective_strategy: str | None = None
    rerank_error: str | None = None
    if "rerank" in requested and merged:
        from src.rerank import rerank
        effective_strategy = (rerank_strategy or os.getenv("RERANK_STRATEGY", "rrf")).lower()
        try:
            merged = rerank(question, merged, top_k, strategy=effective_strategy)
            rerank_used = True
        except Exception as exc:
            # ponytail: cross/colbert 依赖本地模型，未下载时不能让整个问答 500，
            # 这里退回 RRF 序并在 trace 里记 reason（界面上表现为"请求了但空转"）。
            rerank_error = f"{type(exc).__name__}: {exc}"
            merged = merged[:top_k]  # 融合时为重排预留了 top_k*5 候选，降级后要收回

    if not debug:
        return merged

    from src.llm.client import get_llm

    assert stats is not None
    llm_available = get_llm().enabled if wants_plan else False
    routed_docs = len(stats.get("routed_doc_ids", ()))
    applied: list[str] = []
    skipped: list[dict] = []

    if "routing" in requested:
        if routed_docs > 0:
            applied.append("routing")
            if stats.get("route_fallback"):
                skipped.append({
                    "name": "routing",
                    "reason": (
                        f"最高路由分低于阈值 {_MIN_ROUTE_SCORE}，"
                        "跳过文档内检索，仅用全局向量"
                    ),
                })
        else:
            skipped.append({"name": "routing", "reason": "路由层未命中任何文档（doc_index 可能为空），已退回全局向量"})
    if "keywords" in requested:
        if stats.get("keywords", 0) > 0:
            applied.append("keywords")
        else:
            skipped.append({"name": "keywords", "reason": "未从问题中提取到有效关键词"})
    for name, used, absent_reason in (
        ("decompose", bool(sub_queries), "该问题无需拆分（未产出子问题）"),
        ("stepback", step_back_used, "该问题已足够抽象（未产出退步问题）"),
        ("hyde", hyde_used, "该问题为事实型（未产出假想段落）"),
    ):
        if name not in requested:
            continue
        if used:
            applied.append(name)
        else:
            skipped.append({
                "name": name,
                "reason": "LLM 未配置，检索规划未执行" if not llm_available else absent_reason,
            })
    if "rewrite" in requested:
        if rewrite_applied:
            applied.append("rewrite")
        else:
            skipped.append({
                "name": "rewrite",
                "reason": "原查询无可提取的实体/法条，改写无增益（已退回原查询）",
            })
    if "graph" in requested:
        if graph_rows:
            applied.append("graph")
        else:
            skipped.append({"name": "graph", "reason": "图谱通道无命中（图谱未构建，或问题与实体锚点不匹配）"})
    if "rerank" in requested:
        if rerank_used:
            applied.append("rerank")
        elif rerank_error:
            skipped.append({"name": "rerank", "reason": f"重排失败已退回 RRF 序（{rerank_error}）"})
        else:
            skipped.append({"name": "rerank", "reason": "候选为空，未执行重排"})

    trace_channels: list[dict] = []
    if "routing" in requested:
        note = "，已改走全局向量" if stats.get("route_fallback") else ""
        trace_channels.append({
            "name": "routing", "label": "路由", "hits": routed_docs,
            "detail": f"命中 {routed_docs} 篇文档{note}",
        })
    if "keywords" in requested:
        trace_channels.append({"name": "keywords", "label": "关键词", "hits": stats.get("keywords", 0), "detail": None})
    trace_channels.append({
        "name": "vector", "label": "向量", "hits": stats.get("vector", 0),
        "detail": f"{len(queries)} 条查询合并" if len(queries) > 1 else None,
    })
    if hyde_used:
        trace_channels.append({"name": "hyde", "label": "假想文档", "hits": len(hyde_rows), "detail": None})
    if "graph" in requested:
        trace_channels.append({"name": "graph", "label": "图谱", "hits": len(graph_rows), "detail": None})

    return {
        "results": merged,
        "trace": {
            "features": sorted(requested),
            "applied": applied,
            "skipped": skipped,
            "params": {
                "top_k": top_k,
                "filters": filters or {},
                "rerank_strategy": effective_strategy,
            },
            "plan": {
                "subs": list(plan["subs"]),
                "step_back": plan["step_back"],
                "hyde": plan["hyde"],
                "queries": list(queries),
                "rewritten": rewritten if rewrite_applied else None,
            },
            "routing": {
                "routed_docs": routed_docs,
                "top_score": stats.get("route_top_score", 0.0),
                "fallback": bool(stats.get("route_fallback")),
                "min_score": _MIN_ROUTE_SCORE,
            },
            "channels": trace_channels,
            "fusion": {
                "channels": len(channels),
                "pre_merge": len({row["chunk_id"] for channel in channels for row in channel}),
                "post_merge": fused_count,
                "rerank": effective_strategy if rerank_used else None,
                "final": len(merged),
            },
            "timings": {
                "plan_ms": round((t_planned - t_start) * 1000, 1),
                "retrieve_ms": round((t_retrieved - t_planned) * 1000, 1),
                "generate_ms": 0.0,
            },
        },
    }
