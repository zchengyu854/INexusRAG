"""评测集构建器：采样过滤与出题逻辑。

模型调用全部打桩，保证离线可跑。
"""
import unittest

from src.eval_builder import (
    build_ref,
    generate_case,
    generate_multihop_case,
    is_suitable_chunk,
    sample_chunks,
)


class FakeBuilderLLM:
    def __init__(self, payload):
        self.enabled = True
        self._payload = payload
        self.prompts: list[str] = []

    def tool_call(self, prompt, tool):
        self.prompts.append(prompt)
        return self._payload


def _row(doc: str, index: int, text: str = "正文" * 80) -> dict:
    return {"doc_name": doc, "chunk_index": index, "text": text}


class SuitableChunkTests(unittest.TestCase):
    def test_short_fragment_is_rejected(self):
        self.assertFalse(is_suitable_chunk("第三章"))
        self.assertFalse(is_suitable_chunk(""))

    def test_table_of_contents_is_rejected(self):
        toc = "目录\n第一章 概论 ...... 1\n第二章 方法 ...... 15\n" + "正文" * 40
        self.assertFalse(is_suitable_chunk(toc))
        self.assertFalse(is_suitable_chunk("Table of Contents\n" + "x" * 200))

    def test_normal_prose_is_accepted(self):
        self.assertTrue(is_suitable_chunk("这一段说明了检索系统的实现细节。" * 10))

    def test_overlong_chunk_is_rejected(self):
        self.assertFalse(is_suitable_chunk("正" * 4000))


class SampleChunksTests(unittest.TestCase):
    def _rows(self):
        return (
            [_row("a.md", i) for i in range(10)]
            + [_row("b.md", i) for i in range(10)]
            + [_row("c.md", i) for i in range(10)]
        )

    def test_skips_already_used_refs(self):
        used = {build_ref("a.md", i) for i in range(10)}
        picked = sample_chunks(self._rows(), count=6, used_refs=used)
        self.assertTrue(all(row["doc_name"] != "a.md" for row in picked))

    def test_balances_across_documents(self):
        """大文档不能挤占全部名额：10 个名额应跨 3 篇文档分配。"""
        picked = sample_chunks(self._rows(), count=9)
        docs = {row["doc_name"] for row in picked}
        self.assertEqual(len(picked), 9)
        self.assertEqual(docs, {"a.md", "b.md", "c.md"})

    def test_respects_per_doc_cap(self):
        picked = sample_chunks(self._rows(), count=10, per_doc_cap=2)
        counts: dict[str, int] = {}
        for row in picked:
            counts[row["doc_name"]] = counts.get(row["doc_name"], 0) + 1
        self.assertTrue(all(n <= 2 for n in counts.values()))

    def test_is_deterministic_for_a_seed(self):
        first = sample_chunks(self._rows(), count=6, seed=7)
        second = sample_chunks(self._rows(), count=6, seed=7)
        self.assertEqual(
            [(r["doc_name"], r["chunk_index"]) for r in first],
            [(r["doc_name"], r["chunk_index"]) for r in second],
        )

    def test_never_exceeds_available(self):
        picked = sample_chunks(self._rows(), count=999)
        self.assertEqual(len(picked), 30)


class GenerateCaseTests(unittest.TestCase):
    def test_produces_case_with_ground_truth_ref(self):
        llm = FakeBuilderLLM({"suitable": True, "question": "民法典第二百三十条怎么规定的？",
                              "reference_answer": "因继承取得物权者，自继承开始时发生效力。"})
        case = generate_case(_row("zh_law_民法典.md", 21), llm)
        self.assertEqual(case["expected_refs"], "zh_law_民法典.md:21")
        self.assertEqual(case["origin"], "generated")
        self.assertIn("继承", case["reference_answer"])

    def test_unsuitable_chunk_is_skipped(self):
        llm = FakeBuilderLLM({"suitable": False})
        self.assertIsNone(generate_case(_row("a.md", 0), llm))

    def test_too_short_question_is_skipped(self):
        llm = FakeBuilderLLM({"suitable": True, "question": "啥"})
        self.assertIsNone(generate_case(_row("a.md", 0), llm))

    def test_prompt_carries_snippet_and_forbids_leaking(self):
        llm = FakeBuilderLLM({"suitable": True, "question": "问题是什么？", "reference_answer": "答"})
        generate_case(_row("a.md", 3, text="独特内容ABC"), llm)
        prompt = llm.prompts[0]
        self.assertIn("a.md:3", prompt)
        self.assertIn("独特内容ABC", prompt)
        self.assertIn("不要", prompt)  # 提示词里有限制条款


class GenerateMultihopCaseTests(unittest.TestCase):
    def test_joins_both_refs(self):
        llm = FakeBuilderLLM({"suitable": True, "question": "两处结论相比如何？", "reference_answer": "答"})
        case = generate_multihop_case([_row("RAG.pdf", 27), _row("RAG.pdf", 242)], llm)
        self.assertEqual(case["expected_refs"], "RAG.pdf:27|RAG.pdf:242")

    def test_needs_two_chunks(self):
        llm = FakeBuilderLLM({"suitable": True, "question": "随便问问看？", "reference_answer": "答"})
        self.assertIsNone(generate_multihop_case([_row("a.md", 0)], llm))


if __name__ == "__main__":
    unittest.main()
