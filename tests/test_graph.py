"""GraphRAG P1 单元测试：归一化 / 谓词白名单 / 抽取容错 / 实体消歧 / 图通道接线。

全部离线：LLM 与数据库函数均以 mock 替换，不打真实网络与库。
"""
from __future__ import annotations

from unittest.mock import patch

import unittest

from src import graph
from src.graph import (
    HOPS,
    MIN_ANCHOR_SCORE,
    build_document,
    extract_graph,
    graph_channel,
    norm_relation,
    normalize_name,
    resolve_entity,
)

_EMPTY = {"entities": [], "relations": []}
_ONE_ENTITY = {"entities": [{"name": "CiteLocator", "kind": "method", "description": ""}], "relations": []}


class _DisabledLLM:
    enabled = False


class _RaisingLLM:
    enabled = True

    def tool_call(self, prompt, tool, history=None):
        raise RuntimeError("upstream down")


class NormalizeTests(unittest.TestCase):
    def test_cjk_whitespace_removed(self):
        self.assertEqual(normalize_name("  向量 数据库 "), "向量数据库")

    def test_ascii_internal_space_kept_single(self):
        # 英文多词实体不能被压成一个词，否则向量检索语义丢失
        self.assertEqual(normalize_name("Vector  Database"), "vector database")

    def test_trailing_punctuation_stripped(self):
        self.assertEqual(normalize_name("RAG。"), "rag")

    def test_fullwidth_folded(self):
        self.assertEqual(normalize_name("ＲＡＧ"), "rag")


class RelationTests(unittest.TestCase):
    def test_alias_collapses_to_same_predicate(self):
        self.assertEqual(norm_relation("采用"), norm_relation("使用"))
        self.assertNotEqual(norm_relation("使用"), "")

    def test_bilingual_synonyms_share_one_canonical_form(self):
        # 语料是英文论文、提问是中文，中英同义谓词必须落到同一个规范值，否则关系全被白名单丢掉
        self.assertEqual(norm_relation("uses"), norm_relation("使用"))
        self.assertEqual(norm_relation("includes"), norm_relation("包括"))

    def test_generic_predicate_dropped(self):
        # "是"/"is" 无区分度，不该进图
        self.assertEqual(norm_relation("是"), "")
        self.assertEqual(norm_relation("is"), "")


class _PayloadLLM:
    enabled = True

    def __init__(self, payload: dict):
        self.payload = payload

    def tool_call(self, prompt, tool, history=None):
        return self.payload


class ExtractTests(unittest.TestCase):
    # 注意：graph.py 在模块级 from-import 了 get_llm，patch 必须打在 src.graph 上，
    # 打在 src.llm.client 对其无效（会变成真实 API 调用）
    def test_disabled_llm_returns_empty_shape(self):
        with patch.object(graph, "get_llm", return_value=_DisabledLLM()):
            self.assertEqual(extract_graph("任意文本"), _EMPTY)

    def test_llm_failure_returns_empty_shape(self):
        with patch.object(graph, "get_llm", return_value=_RaisingLLM()), \
             patch.object(graph, "_RETRY_BACKOFF", ()):  # 去退避，否则测试要睡 85 秒
            self.assertEqual(extract_graph("任意文本"), _EMPTY)

    def test_junk_entities_and_dangling_relations_are_dropped(self):
        payload = {
            "entities": [
                {"name": "CiteLocator", "kind": "method", "description": "引用位置预测"},
                {"name": "a", "kind": "concept", "description": "过短"},
                {"name": "123", "kind": "other", "description": "纯数字"},
            ],
            "relations": [
                {"src": "CiteLocator", "rel": "uses", "dst": "没抽出来的实体"},  # 端点不在实体集
                {"src": "CiteLocator", "rel": "是", "dst": "CiteLocator"},        # 谓词不在白名单
            ],
        }
        with patch.object(graph, "get_llm", return_value=_PayloadLLM(payload)):
            out = extract_graph("任意文本")
        self.assertEqual([e["name"] for e in out["entities"]], ["CiteLocator"])
        self.assertEqual(out["relations"], [])

    def test_kept_relation_carries_normalized_endpoints(self):
        # build_document 依赖这个契约：关系两端是归一化名，否则 idmap 查不到
        payload = {
            "entities": [{"name": "ReCite", "kind": "method", "description": ""},
                         {"name": "PPO", "kind": "method", "description": ""}],
            "relations": [{"src": "ReCite", "rel": "uses", "dst": "PPO"}],
        }
        with patch.object(graph, "get_llm", return_value=_PayloadLLM(payload)):
            out = extract_graph("ReCite uses PPO")
        self.assertEqual(out["relations"], [{"src": "recite", "rel": "uses", "dst": "ppo"}])


class ResolveTests(unittest.TestCase):
    def test_exact_norm_hit_skips_ann_and_insert(self):
        with patch.object(graph, "get_entity_by_norm", return_value={"entity_id": "e-1"}) as exact, \
             patch.object(graph, "search_entities") as ann, \
             patch.object(graph, "upsert_entity") as upsert:
            self.assertEqual(resolve_entity("RAG", "concept", "", [0.0] * 1024), "e-1")
            ann.assert_not_called()
            upsert.assert_not_called()
            exact.assert_called_once()

    def test_near_duplicate_merges_into_existing(self):
        with patch.object(graph, "get_entity_by_norm", return_value=None), \
             patch.object(graph, "search_entities", return_value=[{"entity_id": "e-2", "kind": "concept", "score": 0.99}]), \
             patch.object(graph, "upsert_entity") as upsert:
            self.assertEqual(resolve_entity("向量检索", "concept", "", [0.0] * 1024), "e-2")
            upsert.assert_not_called()

    def test_new_entity_is_inserted(self):
        with patch.object(graph, "get_entity_by_norm", return_value=None), \
             patch.object(graph, "search_entities", return_value=[{"entity_id": "e-9", "kind": "concept", "score": 0.40}]), \
             patch.object(graph, "upsert_entity", return_value="e-new") as upsert:
            self.assertEqual(resolve_entity("Rerank", "method", "重排", [0.0] * 1024), "e-new")
            upsert.assert_called_once()

    def test_empty_embedding_skips_ann_instead_of_crashing(self):
        # batch 编码只覆盖新实体，已入库的名字可能拿到空向量；不能让它走到 vector_literal
        with patch.object(graph, "get_entity_by_norm", return_value=None), \
             patch.object(graph, "search_entities") as ann, \
             patch.object(graph, "upsert_entity", return_value="e-x"):
            self.assertEqual(resolve_entity("新实体", "concept", "", []), "e-x")
            ann.assert_not_called()


class GraphChannelTests(unittest.TestCase):
    def test_no_anchor_above_threshold_returns_empty(self):
        weak = [{"entity_id": "e-1", "score": MIN_ANCHOR_SCORE - 0.01}]
        with patch.object(graph, "search_entities", return_value=weak), \
             patch.object(graph, "graph_chunks") as chunks:
            self.assertEqual(graph_channel([0.0] * 1024, top_k=5), [])
            chunks.assert_not_called()

    def test_anchors_forwarded_with_hops_and_filters(self):
        anchors = [{"entity_id": "e-1", "score": 0.9}, {"entity_id": "e-2", "score": 0.7}]
        with patch.object(graph, "search_entities", return_value=anchors), \
             patch.object(graph, "graph_chunks", return_value=[{"chunk_id": "c-1"}]) as chunks:
            rows = graph_channel([0.0] * 1024, top_k=25, filters={"page": 3})
        self.assertEqual(rows, [{"chunk_id": "c-1"}])
        args, kwargs = chunks.call_args
        self.assertEqual(args[0], ["e-1", "e-2"])
        self.assertEqual(kwargs.get("hops", HOPS), HOPS)
        self.assertEqual(kwargs.get("limit"), 25)
        self.assertEqual(kwargs.get("filters"), {"page": 3})

    def test_lookup_failure_degrades_to_empty(self):
        with patch.object(graph, "search_entities", side_effect=RuntimeError("db down")):
            self.assertEqual(graph_channel([0.0] * 1024, top_k=5), [])


class _FakeEmbedder:
    def encode(self, texts):
        return [[0.0] * 1024 for _ in texts]


class BuildDocumentTests(unittest.TestCase):
    def test_extracts_resolves_and_links_each_chunk(self):
        chunk = {"chunk_id": "chunk-1", "chunk_index": 0, "text": "RAG 使用向量数据库存储嵌入。"}
        extracted = {
            "entities": [{"name": "RAG", "kind": "concept", "description": "检索增强生成"},
                         {"name": "向量数据库", "kind": "product", "description": ""}],
            "relations": [{"src": "rag", "rel": "uses", "dst": "向量数据库"}],
        }
        with patch.object(graph, "get_chunks_for_graph", return_value=[chunk]), \
             patch.object(graph, "extract_graph", return_value=extracted), \
             patch.object(graph, "get_entity_by_norm", return_value=None), \
             patch.object(graph, "search_entities", return_value=[]), \
             patch.object(graph, "upsert_entity", side_effect=["e-1", "e-2"]), \
             patch.object(graph, "get_embedder", return_value=_FakeEmbedder()), \
             patch.object(graph, "add_relation") as add_relation, \
             patch.object(graph, "link_chunk_entities") as link:
            processed = build_document("doc-1", resume=False)
        self.assertEqual(processed, 1)
        link.assert_called_once()
        linked_chunk_id, linked_ids = link.call_args[0][0], link.call_args[0][1]
        self.assertEqual(linked_chunk_id, "chunk-1")
        self.assertEqual(sorted(linked_ids), ["e-1", "e-2"])
        # 关系两端都解析成了实体 id
        self.assertEqual(add_relation.call_args[0][:2], ("e-1", "e-2"))

    def test_blank_chunks_are_skipped(self):
        chunks = [{"chunk_id": "c-1", "chunk_index": 0, "text": "   "},
                  {"chunk_id": "c-2", "chunk_index": 1, "text": "有效内容"}]
        with patch.object(graph, "get_chunks_for_graph", return_value=chunks), \
             patch.object(graph, "_store_chunk"), \
             patch.object(graph, "extract_graph", return_value=_ONE_ENTITY) as extract, \
             patch.object(graph, "get_embedder", return_value=_FakeEmbedder()):
            build_document("doc-1", resume=False)
        self.assertEqual(extract.call_count, 1)

    def test_resume_skips_already_linked_chunks(self):
        chunks = [{"chunk_id": "c-done", "chunk_index": 0, "text": "已建过"},
                  {"chunk_id": "c-todo", "chunk_index": 1, "text": "待建"}]
        with patch.object(graph, "get_chunks_for_graph", return_value=chunks), \
             patch.object(graph, "chunk_has_entities", side_effect=[True, False]), \
             patch.object(graph, "_store_chunk"), \
             patch.object(graph, "extract_graph", return_value=_ONE_ENTITY) as extract, \
             patch.object(graph, "get_embedder", return_value=_FakeEmbedder()):
            processed = build_document("doc-1")
        self.assertEqual(processed, 1)
        self.assertEqual(extract.call_count, 1)

    def test_all_empty_batch_raises_instead_of_writing_empty_graph(self):
        # 限流/故障时不能静默产出一张空图：构建要响亮地失败
        chunks = [{"chunk_id": f"c-{i}", "chunk_index": i, "text": "正文"} for i in range(3)]
        with patch.object(graph, "get_chunks_for_graph", return_value=chunks), \
             patch.object(graph, "_store_chunk"), \
             patch.object(graph, "extract_graph", return_value=_EMPTY), \
             patch.object(graph, "get_embedder", return_value=_FakeEmbedder()):
            with self.assertRaises(RuntimeError):
                build_document("doc-1", resume=False)


if __name__ == "__main__":
    unittest.main()
