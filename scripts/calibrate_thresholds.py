"""阈值校准：用带标注的查询集扫描 _MIN_ROUTE_SCORE 与 MIN_ANCHOR_SCORE。

两个阈值在代码里都标了 ponytail: 未校准，这里给它们一个数据支撑的取值。

  uv run python scripts/calibrate_thresholds.py            # 全部
  uv run python scripts/calibrate_thresholds.py --only route
  uv run python scripts/calibrate_thresholds.py --only graph

查询集 = 库里已有的 eval_cases（含 doc+chunk 级标注）+ 下面手写的 QUERIES
（只标到 doc 级，用于补齐 eval_cases 没覆盖的文档）。手写部分与当前语料绑定，
换语料后需要重写，脚本结构与指标定义仍然通用。

指标口径见各函数 docstring；结论只作参考，改阈值后要重跑 tests/ 与评测页消融。
"""
from __future__ import annotations

import argparse
import statistics
import sys

# (query, 期望命中的 doc_name) —— 覆盖 eval_cases 未涉及的文档，3 条/篇
QUERIES: list[tuple[str, str]] = [
    # fastapi_readme.md
    ("FastAPI 的性能表现如何，基准测试里排在什么位置？", "fastapi_readme.md"),
    ("How do you declare request body models with Pydantic in FastAPI?", "fastapi_readme.md"),
    ("FastAPI 的依赖注入系统是怎么用的？", "fastapi_readme.md"),
    # RAG.pdf（ReCite 论文）
    ("ReCite 在哪些数据集上做了评测？", "RAG.pdf"),
    ("What is the overall F1 improvement reported by ReCite?", "RAG.pdf"),
    ("ReCite 的 CiteLocator 和 QueryPlanner 是如何协作的？", "RAG.pdf"),
    # en_paper_RAG_arXiv2005.11401.pdf（Lewis et al. 原始 RAG）
    ("What is the difference between RAG-Sequence and RAG-Token?", "en_paper_RAG_arXiv2005.11401.pdf"),
    ("RAG 模型使用的检索器是基于什么向量索引？", "en_paper_RAG_arXiv2005.11401.pdf"),
    ("Which question answering datasets does the RAG paper evaluate on?", "en_paper_RAG_arXiv2005.11401.pdf"),
    # en_news_multihop_15篇.md
    ("What happened to ASX and Wall Street in September?", "en_news_multihop_15篇.md"),
    ("亚马逊卖家对 FTC 的反垄断诉讼有什么反应？", "en_news_multihop_15篇.md"),
    ("Which products were highlighted in the Cyber Monday sale?", "en_news_multihop_15篇.md"),
    # en_novel_pride_and_prejudice.txt
    ("How does Elizabeth Bennet first react to Mr Darcy's proposal?", "en_novel_pride_and_prejudice.txt"),
    ("Mr Collins 向谁求婚被拒绝了？", "en_novel_pride_and_prejudice.txt"),
    ("What is the Bennet family's entailment problem?", "en_novel_pride_and_prejudice.txt"),
    # zh_novel_施公案_节选.txt
    ("胡秀才为什么告状鸣冤？", "zh_novel_施公案_节选.txt"),
    ("施贤臣是怎么通过做梦得到破案线索的？", "zh_novel_施公案_节选.txt"),
    ("施公案第一回里出现了哪些人物？", "zh_novel_施公案_节选.txt"),
    # zh_law_民法典.md
    ("民法典物权编里相邻关系怎么处理？", "zh_law_民法典.md"),
    ("业主的建筑物区分所有权包括哪些内容？", "zh_law_民法典.md"),
    ("物权受到侵害时权利人可以通过哪些途径解决？", "zh_law_民法典.md"),
    # zh_paper_cnki_摘要300篇.md
    ("投影寻踪模型在中小企业电子商务采纳决策里怎么应用？", "zh_paper_cnki_摘要300篇.md"),
    ("碱金属掺杂对 ZnO 薄膜发光性能有什么影响？", "zh_paper_cnki_摘要300篇.md"),
    ("金融危机通过什么传导机制影响服务外包产业？", "zh_paper_cnki_摘要300篇.md"),
]

ROUTE_THRESHOLDS = [round(0.05 * i, 2) for i in range(0, 15)]  # 0.00 .. 0.70
ANCHOR_THRESHOLDS = [round(0.05 * i, 2) for i in range(6, 19)]  # 0.30 .. 0.90


def _load_cases() -> list[tuple[str, str]]:
    """eval_cases 的 expected_refs 形如 'RAG.pdf:155|RAG.pdf:277'，取 doc 部分。"""
    from src.evaluation import load_cases

    out = []
    for case in load_cases():
        docs = {ref.rsplit(":", 1)[0] for ref in case["expected"] if ref}
        if docs:
            out.append((case["question"], docs))
    return out  # type: ignore[return-value]


def build_query_set() -> list[tuple[str, set[str]]]:
    queries = [(q, {doc}) for q, doc in QUERIES]
    queries += _load_cases()
    return queries


# ---------------------------------------------------------------- 路由阈值


def calibrate_route(queries: list[tuple[str, set[str]]], embed) -> None:
    """_MIN_ROUTE_SCORE 决定「是否额外补一路全局向量兜底」。

    注意它不是「要不要路由」——路由通道总会跑。所以好的阈值应当：
      - 路由已经命中正确文档时不兜底（省一次全局检索）
      - 路由命中错误文档时必须兜底（否则召回被锁死在错文档里）

    wasted  = 兜底了但路由其实是对的（白跑一次）
    rescued = 兜底了且路由确实错了（救命）
    missed  = 没兜底且路由错了（有害，召回损失）
    clean   = 没兜底且路由是对的（理想）
    """
    from src.storage.database import search_doc_index

    vectors = embed([q for q, _ in queries])
    observations = []
    for (query, gt_docs), vector in zip(queries, vectors):
        routed = search_doc_index(vector, top_k=3)
        top_score = float(routed[0]["score"]) if routed else 0.0
        hit = any(row["doc_name"] in gt_docs for row in routed)
        observations.append((query, gt_docs, top_score, hit))

    scores = [o[2] for o in observations]
    hits = [o[3] for o in observations]
    print(f"\n[路由] 查询 {len(observations)} 条，路由 top-3 命中正确文档 {sum(hits)} 条 "
          f"({sum(hits) / len(hits):.0%})")
    print(f"[路由] top-1 分数分布: min={min(scores):.3f} "
          f"p25={statistics.quantiles(scores, n=4)[0]:.3f} "
          f"median={statistics.median(scores):.3f} "
          f"p75={statistics.quantiles(scores, n=4)[2]:.3f} max={max(scores):.3f}")
    print(f"[路由] 命中组 vs 未命中组 平均分: "
          f"{statistics.mean([o[2] for o in observations if o[3]]):.3f} / "
          f"{statistics.mean([o[2] for o in observations if not o[3]]) or 0:.3f}")

    print("\n  阈值   兜底率   clean  wasted  rescued  missed   净收益")
    best = None
    for t in ROUTE_THRESHOLDS:
        clean = wasted = rescued = missed = 0
        for _, _, top_score, hit in observations:
            fallback = top_score < t
            if hit:
                clean += not fallback
                wasted += fallback
            else:
                rescued += fallback
                missed += not fallback
        gain = clean + rescued - (wasted + missed)
        rate = (wasted + rescued) / len(observations)
        print(f"  {t:>5.2f}  {rate:>6.0%}  {clean:>6}  {wasted:>6}  {rescued:>7}  {missed:>6}  {gain:>7}")
        if best is None or gain > best[1]:
            best = (t, gain)
    print(f"\n  → 路由阈值建议 {best[0]:.2f}（当前 0.30）；missed 是有害项，宁可 wasted 也不要 missed。")


# ---------------------------------------------------------------- 图谱锚点阈值


def calibrate_anchor(queries: list[tuple[str, set[str]]], embed) -> None:
    """MIN_ANCHOR_SCORE 决定问题向量能锚定到哪些实体。

    太低 → 锚到噪声实体，图通道把无关文档的切片带进来（精度差）
    太高 → 锚不到实体，图通道干脆不触发（覆盖率差）

    这里用「锚点来源文档是否正确」作为精度代理，因为手写查询只标到 doc 级。
    """
    import src.graph as G
    from src.storage.database import search_entities

    vectors = embed([q for q, _ in queries])
    per_query = []
    for (query, gt_docs), vector in zip(queries, vectors):
        try:
            candidates = search_entities(vector, G.ANCHOR_TOP * 3)
        except Exception as exc:  # 图谱未构建
            print(f"[图谱] 查询锚点失败（图谱可能未构建）: {exc}")
            return
        per_query.append((gt_docs, candidates))

    all_scores = [c["score"] for _, cs in per_query for c in cs]
    print(f"\n[图谱] 候选锚点 {len(all_scores)} 个，分数 min={min(all_scores):.3f} "
          f"median={statistics.median(all_scores):.3f} max={max(all_scores):.3f}")

    print("\n  阈值  有锚点  锚点数  文档准确率  图召回(GT文档切片占比)")
    best = None
    for t in ANCHOR_THRESHOLDS:
        covered = 0
        anchor_total = 0
        anchor_correct = 0
        chunk_hits = 0
        chunk_total = 0
        for gt_docs, candidates in per_query:
            anchors = [c for c in candidates if c["score"] >= t][: G.ANCHOR_TOP]
            if not anchors:
                continue
            covered += 1
            anchor_total += len(anchors)
            try:
                chunks = G.graph_chunks([a["entity_id"] for a in anchors], hops=G.HOPS, limit=20)
            except Exception:
                chunks = []
            for chunk in chunks:
                chunk_total += 1
                if chunk.get("doc_name") in gt_docs:
                    chunk_hits += 1
            # 锚点来源：用实体证据切片判断实体归属哪篇文档
            for anchor in anchors:
                try:
                    from src.storage.database import entity_evidence_chunks

                    evidence = entity_evidence_chunks(anchor["entity_id"], limit=3)
                    if any(e.get("doc_name") in gt_docs for e in evidence):
                        anchor_correct += 1
                except Exception:
                    pass
        n = len(per_query)
        prec = chunk_hits / chunk_total if chunk_total else 0.0
        acc = anchor_correct / anchor_total if anchor_total else 0.0
        print(f"  {t:>5.2f}  {covered / n:>6.0%}  {anchor_total:>6}  {acc:>9.0%}  {prec:>9.0%}")
        # 目标：保住覆盖率的同时把文档准确率做上去
        score = acc * 0.7 + prec * 0.3 if covered else 0.0
        if covered / n >= 0.6 and (best is None or score > best[1]):
            best = (t, score)
    if best:
        print(f"\n  → 锚点阈值建议 {best[0]:.2f}（当前 {G.MIN_ANCHOR_SCORE}）；"
              f"要求至少 60% 查询能锚到实体。")
    else:
        print("\n  → 没有任何阈值能让 60% 以上的查询锚到实体，先检查图谱是否已 build。")


# ---------------------------------------------------------------- 端到端复核


def _doc_level_metrics(results: list[dict], gt_docs: set[str], k: int) -> tuple[int, float]:
    """文档级 Hit@K / MRR：手写查询只标到 doc 级，用文档命中而非 chunk 命中。"""
    docs = [r.get("doc_name") for r in results[:k]]
    ranks = [i for i, name in enumerate(docs, 1) if name in gt_docs]
    return (1 if ranks else 0), (1.0 / ranks[0] if ranks else 0.0)


def _sweep(label: str, queries: list[tuple[str, set[str]]], setter, values, features):
    import src.retrieval as R
    from src.retrieval import multi_query_search

    original = setter(None)
    rows = []
    try:
        for value in values:
            setter(value)
            hits = mrr = 0.0
            for question, gt_docs in queries:
                hit, reciprocal = _doc_level_metrics(
                    multi_query_search(question, 5, features=features), gt_docs, 5
                )
                hits += hit
                mrr += reciprocal
            n = len(queries)
            rows.append((value, hits / n, mrr / n))
    finally:
        setter(original)
    print(f"\n[{label}] {len(queries)} 条查询 · 文档级 Hit@5 / MRR")
    print("  阈值   Hit@5     MRR")
    for value, hit, mrr in rows:
        print(f"  {value:>5.2f}  {hit:>6.0%}  {mrr:>6.3f}")
    best = max(rows, key=lambda r: (r[1], r[2]))
    print(f"  → 最佳 {best[0]:.2f}（Hit@5 {best[1]:.0%}, MRR {best[2]:.3f}）")
    return best


def end_to_end_check(queries: list[tuple[str, set[str]]]) -> None:
    """端到端复核。用路由/锚点各扫一遍，看阈值对真实召回的影响。

    只跑 8 条 eval_cases 噪声太大（±12 个百分点），所以这里用全部查询 +
    文档级指标：32 条查询、每条只需判断「top-5 里有没有期望文档的切片」。
    """
    import src.graph as G
    import src.retrieval as R

    def route_setter(value):
        previous = R._MIN_ROUTE_SCORE
        if value is not None:
            R._MIN_ROUTE_SCORE = value
        return previous

    def anchor_setter(value):
        previous = G.MIN_ANCHOR_SCORE
        if value is not None:
            G.MIN_ANCHOR_SCORE = value
        return previous

    # 特性集里不含 decompose/stepback/hyde：那三项每次查询都要打一次 LLM，
    # 32 条 × 7 档 = 224 次外部调用，既慢又会把网络抖动混进阈值结论。
    _sweep(
        "端到端·路由阈值",
        queries,
        route_setter,
        [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        ["routing", "keywords"],
    )
    _sweep(
        "端到端·锚点阈值（开启 graph 通道）",
        queries,
        anchor_setter,
        [0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7],
        ["routing", "keywords", "graph"],
    )
    # 基线对照：把「路由」和「图通道」分别摘掉，看上面两组的天花板到底是谁撑起来的
    _sweep(
        "基线·无路由（keywords + 全局向量）",
        queries,
        route_setter,
        [0.2],
        ["keywords"],
    )
    _sweep(
        "基线·无图通道",
        queries,
        anchor_setter,
        [0.5],
        ["routing", "keywords"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=["route", "graph", "e2e"], help="只跑其中一项")
    args = parser.parse_args()

    from src.ingestion.embedder import get_embedder

    embedder = get_embedder()
    print(f"embedding: {embedder.provider} / {embedder.model} / dim={embedder.dimension}")

    queries = build_query_set()
    print(f"查询集: {len(QUERIES)} 条手写 + {len(queries) - len(QUERIES)} 条 eval_cases")

    if args.only in (None, "route"):
        calibrate_route(queries, embedder.encode)
    if args.only in (None, "graph"):
        calibrate_anchor(queries, embedder.encode)
    if args.only in (None, "e2e"):
        end_to_end_check(queries)


if __name__ == "__main__":
    sys.exit(main())
