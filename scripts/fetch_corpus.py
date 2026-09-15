"""从公开合法来源批量下载语料，可选直接入库。

为什么需要它：原语料只有 8 篇 / 5,750 切片，评测集扩到 63 条后仍受「样本量」限制
（见 docs/eval-report-2026-09-14.md §十）。要提高结论的分辨率，先要把语料本身做厚。

来源选择（全部为公版或开放许可，不抓取受版权/ToS 限制的站点）：
- **Project Gutenberg**：公版书（英语小说/哲学 + 中文古籍小说），`cache/epub/{id}/pg{id}.txt`
- **arXiv**：开放获取论文 PDF（IR / RAG / Agent 主题）
- **jsDelivr CDN**：GitHub 开源仓库文档（英文 + 中文技术文档），`cdn.jsdelivr.net/gh/{owner}/{repo}@{ref}/{path}`

用法：
    uv run python scripts/fetch_corpus.py --probe          # 只探测可达性，不落盘
    uv run python scripts/fetch_corpus.py                  # 下载到 data/corpus/
    uv run python scripts/fetch_corpus.py --ingest         # 下载并入库（内容哈希幂等，可重复跑）
    uv run python scripts/fetch_corpus.py --only arxiv      # 只取某一类来源
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_ROOT = Path(__file__).resolve().parents[1]
_CORPUS_DIR = _ROOT / "data" / "corpus"
_UA = "Mozilla/5.0 (compatible; NexusRAG-corpus-fetcher/1.0)"

GUTENBERG = "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt"
ARXIV = "https://arxiv.org/pdf/{id}"
JSDELIVR = "https://cdn.jsdelivr.net/gh/{path}"

# (kind, slug, 扩展名, 标题, 来源参数)
MANIFEST: list[tuple[str, str, str, str, str]] = [
    # ---- 英文公版书（Gutenberg）----
    ("gutenberg", "en_book_moby_dick", "txt", "Moby Dick (Melville)", "2701"),
    ("gutenberg", "en_book_sherlock_holmes", "txt", "The Adventures of Sherlock Holmes", "1661"),
    ("gutenberg", "en_book_frankenstein", "txt", "Frankenstein (Shelley)", "84"),
    ("gutenberg", "en_book_dracula", "txt", "Dracula (Stoker)", "345"),
    ("gutenberg", "en_book_alice_wonderland", "txt", "Alice's Adventures in Wonderland", "11"),
    ("gutenberg", "en_book_the_prince", "txt", "The Prince (Machiavelli)", "1232"),
    ("gutenberg", "en_book_meditations", "txt", "Meditations (Marcus Aurelius)", "2680"),
    # ---- 中文公版古籍/小说（Gutenberg 中文书）----
    ("gutenberg", "zh_book_guiguzi", "txt", "鬼谷子", "7209"),
    ("gutenberg", "zh_book_renwuzhi", "txt", "人物志", "7217"),
    ("gutenberg", "zh_book_sanlue", "txt", "三略", "7218"),
    ("gutenberg", "zh_book_weiliazi", "txt", "尉繚子", "7219"),
    ("gutenberg", "zh_book_soushenji", "txt", "搜神記（卷一至卷三）", "7260"),
    ("gutenberg", "zh_book_fenzhuanglou", "txt", "粉妝樓（全八十回）", "4580"),
    # ---- 开放获取论文（arXiv PDF）----
    ("arxiv", "en_paper_dpr_2004.04906", "pdf", "Dense Passage Retrieval (Karpukhin et al.)", "2004.04906"),
    ("arxiv", "en_paper_hyde_2212.10496", "pdf", "Precise Zero-Shot Dense Retrieval without Relevance Labels (HyDE)", "2212.10496"),
    ("arxiv", "en_paper_rag_survey_2312.10997", "pdf", "Retrieval-Augmented Generation for LLMs: A Survey", "2312.10997"),
    ("arxiv", "en_paper_react_2210.03629", "pdf", "ReAct: Synergizing Reasoning and Acting in LMs", "2210.03629"),
    ("arxiv", "en_paper_cot_2201.11903", "pdf", "Chain-of-Thought Prompting Elicits Reasoning", "2201.11903"),
    ("arxiv", "en_paper_reflexion_2303.11366", "pdf", "Reflexion: Language Agents with Verbal RL", "2303.11366"),
    ("arxiv", "en_paper_t5_1910.10683", "pdf", "Exploring the Limits of Transfer Learning (T5)", "1910.10683"),
    ("arxiv", "en_paper_lora_2106.09685", "pdf", "LoRA: Low-Rank Adaptation of LLMs", "2106.09685"),
    # ---- 开源技术文档（jsDelivr → GitHub raw）----
    ("tech", "tech_fastapi_first_steps", "md", "FastAPI 教程：First Steps", "tiangolo/fastapi@master/docs/en/docs/tutorial/first-steps.md"),
    ("tech", "tech_pydantic_readme", "md", "Pydantic README", "pydantic/pydantic@main/README.md"),
    ("tech", "tech_uv_readme", "md", "uv README", "astral-sh/uv@main/README.md"),
    ("tech", "tech_pgvector_readme", "md", "pgvector README", "pgvector/pgvector@master/README.md"),
    ("tech", "zh_doc_vue_introduction", "md", "Vue 3 中文文档：简介", "vuejs-translations/docs-zh-cn@main/src/guide/introduction.md"),
    ("tech", "zh_doc_vue_reactivity", "md", "Vue 3 中文文档：响应式基础", "vuejs-translations/docs-zh-cn@main/src/guide/essentials/reactivity-fundamentals.md"),
    ("tech", "tech_sentence_transformers_readme", "md", "sentence-transformers README", "UKPLab/sentence-transformers@master/README.md"),
    ("tech", "tech_langchain_readme", "md", "LangChain README", "langchain-ai/langchain@master/README.md"),
]


def _url(item: tuple[str, str, str, str, str]) -> str:
    kind, _slug, _ext, _title, spec = item
    if kind == "gutenberg":
        return GUTENBERG.format(id=spec)
    if kind == "arxiv":
        return ARXIV.format(id=spec)
    return JSDELIVR.format(path=spec)


def _curl(url: str, dest: Path | None, timeout: int = 180) -> tuple[int, int]:
    """返回 (http_code, bytes)。dest=None 时只探测。"""
    cmd = ["curl", "-sSL", "--http1.1", "--retry", "2", "--max-time", str(timeout),
           "-A", _UA, "-w", "%{http_code} %{size_download}", "-o", str(dest or "/dev/null"), url]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
        parts = (out.stdout or "").strip().split()
        if len(parts) >= 2:
            return int(parts[-2]), int(parts[-1])
        return 0, 0
    except Exception:
        return 0, 0


def main() -> None:
    ap = argparse.ArgumentParser(description="下载公开语料到 data/corpus/")
    ap.add_argument("--only", choices=["gutenberg", "arxiv", "tech"], help="只处理某一类来源")
    ap.add_argument("--probe", action="store_true", help="只探测可达性，不落盘")
    ap.add_argument("--ingest", action="store_true", help="下载后直接入库（幂等）")
    ap.add_argument("--force", action="store_true", help="已存在的文件也重下")
    ns = ap.parse_args()

    items = [m for m in MANIFEST if not ns.only or m[0] == ns.only]
    _CORPUS_DIR.mkdir(parents=True, exist_ok=True)

    ok, failed, skipped = [], [], []
    for item in items:
        kind, slug, ext, title, _spec = item
        url = _url(item)
        dest = _CORPUS_DIR / f"{slug}.{ext}"
        if dest.exists() and dest.stat().st_size > 1024 and not ns.force and not ns.probe:
            skipped.append((slug, dest.stat().st_size))
            continue
        code, size = _curl(url, None if ns.probe else dest)
        if code == 200 and size > 1024:
            ok.append((slug, size))
            print(f"  ✓ {slug:<42} {size/1024:>8.1f} KB")
        else:
            failed.append((slug, code, size))
            print(f"  ✗ {slug:<42} http={code} size={size}")
            if not ns.probe:
                dest.unlink(missing_ok=True)

    print(f"\n成功 {len(ok)} / 失败 {len(failed)} / 跳过（已存在）{len(skipped)}")
    if failed:
        print("失败清单：", json.dumps([f[0] for f in failed], ensure_ascii=False))
    if ns.probe:
        return

    if ns.ingest:
        _ingest_all([slug for slug, _ in ok] + [slug for slug, _ in skipped])


def _ingest_all(slugs: list[str]) -> None:
    """走与 /api/upload + /api/ingest 相同的代码路径入库（内容哈希幂等）。"""
    from src.api.routes import _UPLOAD_DIR, _ingest_document
    from src.storage.database import create_document, find_document_by_hash, get_document

    by_slug = {m[1]: m for m in MANIFEST}
    print(f"\n=== 入库 {len(slugs)} 篇 ===")
    for slug in slugs:
        item = by_slug.get(slug)
        if not item:
            continue
        _kind, _slug, ext, title, _spec = item
        src = _CORPUS_DIR / f"{slug}.{ext}"
        if not src.exists():
            continue
        content = src.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        existing = find_document_by_hash(digest)
        if existing is not None and existing.get("deleted_at") is None:
            print(f"  = {slug:<42} 已入库（{existing['filename']}, {existing.get('chunks', 0)} 切片）")
            continue
        dst = _UPLOAD_DIR / f"{digest[:12]}_{src.name}"
        if not dst.exists():
            shutil.copy2(src, dst)
        doc_id = f"{datetime.now().isoformat(timespec='seconds')}_{digest[:8]}"
        try:
            create_document(doc_id, src.name, str(dst), digest)
            _ingest_document(doc_id)
        except Exception as exc:
            print(f"  ✗ {slug:<42} 入库失败：{exc}")
            continue
        doc = get_document(doc_id) or {}
        status = doc.get("status")
        print(f"  {'✓' if status == 'ready' else '✗'} {slug:<42} {status} chunks={doc.get('chunks', 0)}")


if __name__ == "__main__":
    main()
