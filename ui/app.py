"""
NexusRAG — 多文档智能问答系统
设计：Minimalist Editorial × Premium Utilitarian
色板：warm bone #F7F6F3 / off-black #1A1A1A / muted pastels
"""
from __future__ import annotations

import json
from typing import Optional

import requests
import streamlit as st
from streamlit import dialog

# ── 设计系统 ─────────────────────────────────────────────────────────────────
STYLES = """
<style>
:root {
  --bg: #F7F6F3; --surface: #FFFFFF; --surface-alt: #F0EFEB;
  --border: rgba(0,0,0,0.08);
  --ink: #1A1A1A; --ink-2: #787774;
  --serif: Georgia, 'Times New Roman', serif;
  --mono: 'SF Mono', Menlo, monospace;
}

/* 只隐藏 footer，保留 header（sidebar toggle 在 header 里） */
footer { visibility: hidden; }

.stApp { background: var(--bg); color: var(--ink); }

/* 锁定亮色：header 与底部输入区不跟随系统暗色 */
header[data-testid="stHeader"] { background: var(--bg) !important; }
[data-testid="stBottom"] { background: var(--bg) !important; }
[data-testid="stBottom"] > div { background: var(--bg) !important; }
[data-testid="stChatInput"], [data-testid="stChatInput"] > div,
[data-testid="stChatInput"] div[data-testid="stChatInput"] ~ * { background: var(--surface) !important; }
[data-testid="stChatInput"] div { border-color: var(--border) !important; }
[data-testid="stChatInput"] textarea { color: var(--ink) !important; background: var(--surface) !important; }
[data-testid="stChatInput"] textarea::placeholder { color: var(--ink-2) !important; }
[data-testid="stChatInput"] button { color: var(--ink) !important; }
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li { color: var(--ink); }

/* 衬线标题 */
h1, h2, h3 { font-family: var(--serif) !important; letter-spacing: -0.02em; }

/* 侧边栏 */
[data-testid="stSidebar"] { background: var(--surface-alt) !important; border-right: 1px solid var(--border); }
[data-testid="stSidebar"] h3 {
  font-family: var(--mono) !important;
  font-size: 0.7rem !important; font-weight: 600;
  letter-spacing: 0.1em; color: var(--ink-2) !important;
  margin-bottom: 0.5rem;
}

/* 文档卡片 */
.doc-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 0.65rem 0.85rem; margin-bottom: 0.5rem;
  transition: border-color 0.15s ease;
}
.doc-card:hover { border-color: rgba(0,0,0,0.2); }
.doc-card .doc-name { font-size: 0.82rem; font-weight: 600; color: var(--ink); }
.doc-card .doc-meta { font-family: var(--mono); font-size: 0.68rem; color: var(--ink-2); margin-top: 0.2rem; }

/* 状态徽章（muted pastels） */
.badge { display: inline-block; font-size: 0.6rem; font-weight: 600; letter-spacing: 0.05em;
  padding: 0.1rem 0.5rem; border-radius: 999px; vertical-align: middle; }
.badge-ready   { background: #EDF3EC; color: #346538; }
.badge-indexing{ background: #E1F3FE; color: #1F6C9F; }
.badge-failed  { background: #FDEBEC; color: #9F2F2D; }
.badge-pending { background: #FBF3DB; color: #956400; }

/* 统计条 */
.stats-bar {
  display: flex; gap: 2.5rem; padding: 0.6rem 0;
  border-bottom: 1px solid var(--border); margin-bottom: 1.25rem;
  font-family: var(--mono); font-size: 0.72rem; color: var(--ink-2);
}
.stats-bar b { color: var(--ink); font-weight: 600; margin-left: 0.35rem; }

/* 按钮 */
.stButton > button {
  background: #1A1A1A !important; color: #fff !important;
  border: none !important; border-radius: 6px !important;
  font-size: 0.78rem !important; font-weight: 500 !important;
  transition: transform 0.12s ease !important;
}
.stButton > button * { color: #fff !important; }
.stButton > button:hover { background: #333 !important; transform: scale(0.98); }

/* 文件上传框（暗色主题残留） */
[data-testid="stFileUploader"],
[data-testid="stFileUploaderDropzone"],
[data-testid="stFileUploader"] > div,
[data-testid="stFileUploader"] section > div > div {
  background: var(--surface) !important;
  border-color: var(--border) !important;
  color: var(--ink) !important;
}
[data-testid="stFileUploader"] * { color: var(--ink) !important; }
[data-testid="stFileUploader"] small { color: var(--ink-2) !important; }
[data-testid="stFileUploader"] button {
  background: var(--surface-alt) !important;
  border: 1px solid var(--border) !important;
  color: var(--ink) !important;
}

/* 聊天 */
[data-testid="stChatInput"] textarea { font-size: 0.9rem; }
[data-testid="stChatMessage"] { border-radius: 12px; }

/* Expander */
[data-testid="stExpander"] {
  border: 1px solid var(--border) !important; border-radius: 8px !important;
  background: var(--surface) !important;
}
[data-testid="stExpander"] details { border: none !important; }

/* Chunk Viewer Modal */
[data-testid="stDialog"] > div {
  max-width: 820px !important;
  border-radius: 12px !important;
}
[data-testid="stDialog"] [data-testid="stCodeBlock"] {
  max-height: 240px; overflow-y: auto;
}
</style>
"""

API_BASE = "http://localhost:8000/api"


# ── API Helper ──────────────────────────────────────────────────────────────
def _api(path: str, method: str = "GET", **kwargs):
    resp = getattr(requests, method.lower())(f"{API_BASE}{path}", timeout=30, **kwargs)
    resp.raise_for_status()
    return resp.json()


def _trigger_ingest(doc_id: str) -> dict:
    try:
        return _api(f"/ingest/{doc_id}", "POST")
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def _query(question: str) -> tuple[str, list[dict]]:
    resp = requests.post(f"{API_BASE}/query", json={"question": question, "stream": True},
                         stream=True, timeout=60)
    resp.raise_for_status()
    answer_parts: list[str] = []
    sources: list[dict] = []
    for line in resp.iter_lines():
        if not line or not line.startswith(b"data:"):
            continue
        event = json.loads(line[5:])
        if event.get("type") == "token":
            answer_parts.append(event["data"])
        elif event.get("type") == "source":
            sources.append(event["data"])
    return "".join(answer_parts), sources


def _badge(status: str) -> str:
    cls = {"ready": "ready", "indexing": "indexing", "failed": "failed"}.get(status, "pending")
    label = {"ready": "已入库", "indexing": "入库中", "failed": "失败", "pending": "待入库"}.get(status, status)
    return f'<span class="badge badge-{cls}">{label}</span>'


# ── 页面 ─────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="NexusRAG", page_icon="◆", layout="wide")
st.markdown(STYLES, unsafe_allow_html=True)

# 标题区
st.markdown(
    "<h1 style='font-size:1.9rem;font-weight:400;margin-bottom:0.1rem;'>NexusRAG</h1>"
    "<p style='font-family:var(--mono);font-size:0.72rem;letter-spacing:0.08em;"
    "color:#787774;text-transform:uppercase;margin-bottom:1rem;'>多文档智能问答系统</p>",
    unsafe_allow_html=True,
)

# 统计条
try:
    s = _api("/stats")
    st.markdown(
        f"<div class='stats-bar'>"
        f"<span>DOCUMENTS<b>{s['total_documents']}</b></span>"
        f"<span>CHUNKS<b>{s['total_chunks']}</b></span>"
        f"<span>DIMENSION<b>{s['embedding_dimension']}</b></span>"
        f"<span>STORAGE<b>{s['total_size_kb']:.0f} KB</b></span>"
        f"</div>",
        unsafe_allow_html=True,
    )
except Exception:
    st.warning("无法连接后端 :8000，请先运行 `./run.sh backend`")


# ── 切片查看器 Modal ────────────────────────────────────────────────────────
@dialog("Chunk Viewer")
def _chunk_viewer(doc: dict):
    try:
        cfg = _api(f"/documents/{doc['id']}/chunks")
        st.caption(
            f"策略 {cfg.get('strategy', '-')} · "
            f"size {cfg.get('chunk_size', '-')} · "
            f"overlap {cfg.get('chunk_overlap', '-')}"
        )
        for ch in cfg.get("chunks", []):
            st.markdown(f"**#{ch['index']}** · {ch['length']} chars")
            st.code(ch["text"], language="text")
        total = cfg.get("total_chunks", 0)
        if total > len(cfg.get("chunks", [])):
            st.caption(f"… 后端仅返回前 {len(cfg.get('chunks', []))} 个（共 {total}）")
    except Exception as e:
        st.error(f"切片加载失败: {e}")

    if doc["status"] != "ready":
        if st.button("▶ Ingest", use_container_width=True, type="primary"):
            with st.spinner("Ingesting..."):
                _trigger_ingest(doc["id"])
            st.rerun()

    if st.button("Delete", use_container_width=True):
        try:
            _api(f"/documents/{doc['id']}", "DELETE")
            st.toast(f"已删除 {doc['filename']}")
        except Exception as e:
            st.error(f"删除失败: {e}")
        st.rerun()


# ── 侧边栏 ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### DOCUMENTS")

    if st.button("Refresh", use_container_width=True):
        st.rerun()

    try:
        docs = _api("/documents")
    except Exception:
        docs = []

    for doc in docs:
        chunks = doc.get("chunks", 0)
        st.markdown(
            f"<div class='doc-card'>"
            f"<div class='doc-name'>{doc['filename']}</div>"
            f"<div class='doc-meta'>{chunks} chunks · {_badge(doc['status'])}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        if st.button("查看切片", key=f"view_{doc['id']}", use_container_width=True):
            _chunk_viewer(doc)

    st.markdown("---")
    st.markdown("### UPLOAD")
    uploaded = st.file_uploader("PDF / MD / TXT", type=["pdf", "md", "markdown", "txt"], label_visibility="collapsed")
    if uploaded and st.button("Upload", use_container_width=True):
        with st.spinner(f"Uploading {uploaded.name}..."):
            try:
                resp = _api("/upload", "POST", files={"file": (uploaded.name, uploaded.read())})
                st.toast(f"已上传 {resp['filename']}")
                st.rerun()
            except Exception as e:
                st.error(f"上传失败: {e}")


# ── 对话区 ───────────────────────────────────────────────────────────────────
st.markdown("<h2 style='font-size:1.15rem;font-weight:500;'>Conversation</h2>", unsafe_allow_html=True)

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("sources"):
            with st.expander(f"Sources（{len(msg['sources'])} 个切片）"):
                for src in msg["sources"]:
                    score = src.get("score")
                    head = f"**{src.get('doc_name', '?')}**" + (f" · 相似度 {score:.2%}" if score is not None else "")
                    st.markdown(head)
                    st.text(src.get("text", ""))

if prompt := st.chat_input("Ask a question..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            answer, sources = _query(prompt)
            st.markdown(answer)
            if sources:
                with st.expander(f"Sources（{len(sources)} 个切片）"):
                    for src in sources:
                        score = src.get("score")
                        head = f"**{src.get('doc_name', '?')}**" + (f" · 相似度 {score:.2%}" if score is not None else "")
                        st.markdown(head)
                        st.text(src.get("text", ""))
            st.session_state.messages.append(
                {"role": "assistant", "content": answer, "sources": sources}
            )
        except Exception as e:
            st.error(f"查询失败: {e}")
