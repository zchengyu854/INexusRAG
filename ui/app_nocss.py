"""
NexusRAG — 多文档智能问答系统
设计风格：Minimalist Editorial × Premium Utilitarian
色板：warm bone (#F7F6F3) / off-black (#1A1A1A) / muted pastels
字体：system-ui, Georgia serif for headings
"""
from __future__ import annotations

import json
import math
from typing import Optional

import requests
import streamlit as st

# ── 自定义 CSS：Minimalist Editorial 设计系统 ──────────────────────────────
STYLES = """
<style>
/* ── Reset & Base ─────────────────────────────────────────────── */
:root {
  --bg:          #F7F6F3;
  --surface:     #FFFFFF;
  --surface-alt: #F0EFEB;
  --border:      rgba(0,0,0,0.08);
  --text-primary:#1A1A1A;
  --text-secondary:#787774;
  --accent:      #2C2C2C;
  --pastel-green:#EDF3EC;
  --pastel-green-text:#346538;
  --pastel-blue:#E1F3FE;
  --pastel-blue-text:#1F6C9F;
  --pastel-red: #FDEBEC;
  --pastel-red-text:#9F2F2D;
  --pastel-yellow:#FBF3DB;
  --pastel-yellow-text:#956400;

# CSS 已临时禁用以调试
# st.markdown(STYLES, unsafe_allow_html=True)

# 其余代码保持不变
  --font-serif:  'Georgia', 'Newsreader', 'Playfair Display', serif;
  --font-mono:   'SF Mono', 'Geist Mono', 'JetBrains Mono', monospace;
}

/* Hide default Streamlit chrome */
#MainMenu {visibility: hidden;}
header[data-testid='stHeader'] {visibility: hidden;}
footer {visibility: hidden;}
section[data-testid='stSidebar'] > div:first-child {padding-top: 1.5rem;}

/* ── Canvas ───────────────────────────────────────────────────── */
.main > div {
  background: var(--bg);
  font-family: var(--font-sans);
  color: var(--text-primary);
}

/* ── Typography ───────────────────────────────────────────────── */
.stTitle, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
  font-family: var(--font-serif) !important;
  letter-spacing: -0.02em !important;
  line-height: 1.15 !important;
  color: var(--text-primary) !important;
}
.stTitle { font-size: 2rem !important; font-weight: 400 !important; }
.stCaption { font-size: 0.8rem !important; color: var(--text-secondary) !important; letter-spacing: 0.04em !important; text-transform: uppercase; }

/* ── Sidebar ──────────────────────────────────────────────────── */
.css-1d391kg, [data-testid='stSidebar'] {
  background: var(--surface-alt) !important;
  border-right: 1px solid var(--border) !important;
}
.css-1d391kg h2, [data-testid='stSidebar'] h2 {
  font-family: var(--font-sans) !important;
  font-weight: 600 !important;
  font-size: 0.7rem !important;
  letter-spacing: 0.08em !important;
  text-transform: uppercase !important;
  color: var(--text-secondary) !important;
  padding: 0 1rem !important;
  margin-bottom: 0.75rem !important;
}

/* ── Document List Items ──────────────────────────────────────── */
.doc-item {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.75rem 1rem;
  margin-bottom: 0.5rem;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}
.doc-item:hover {
  border-color: rgba(0,0,0,0.15);
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
}

/* ── Buttons ──────────────────────────────────────────────────── */
.stButton > button {
  background: var(--accent) !important;
  color: #fff !important;
  border: none !important;
  border-radius: 6px !important;
  font-size: 0.8rem !important;
  font-weight: 500 !important;
  padding: 0.5rem 1rem !important;
  transition: all 0.15s ease !important;
  cursor: pointer;
}
.stButton > button:hover { background: #3A3A3A !important; transform: scale(0.98); }
.stButton > button:active { transform: scale(0.97); }

/* Delete button - muted */
.stButton > button[kind='secondary'],
.stButton > button[data-testid='baseButton-secondary'] {
  background: transparent !important;
  color: var(--text-secondary) !important;
  border: 1px solid var(--border) !important;
  font-size: 0.75rem !important;
  padding: 0.35rem 0.75rem !important;
}
.stButton > button[kind='secondary']:hover {
  background: var(--pastel-red) !important;
  color: var(--pastel-red-text) !important;
  border-color: var(--pastel-red) !important;
}

/* ── File Uploader ────────────────────────────────────────────── */
.stFileUploader > div {
  border: 1px dashed var(--border) !important;
  border-radius: var(--radius) !important;
  background: var(--surface) !important;
  transition: border-color 0.2s ease !important;
}
.stFileUploader > div:hover { border-color: rgba(0,0,0,0.25) !important; }

/* ── Stats Bar ────────────────────────────────────────────────── */
.stats-bar {
  display: flex;
  gap: 2rem;
  padding: 0.75rem 0;
  border-bottom: 1px solid var(--border);
  margin-bottom: 1.5rem;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: var(--text-secondary);
  letter-spacing: 0.02em;
}
.stats-bar span { display: flex; align-items: center; gap: 0.4rem; }
.stats-bar .stat-value { color: var(--text-primary); font-weight: 600; }

/* ── Chat ─────────────────────────────────────────────────────── */
.stChatMessage {
  border-radius: var(--radius-lg) !important;
  padding: 1rem 1.25rem !important;
}
.stChatMessage[data-testid='stChatMessageAvatar'] {
  background: var(--surface-alt) !important;
  border: 1px solid var(--border) !important;
}
.stChatInput {
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-lg) !important;
  background: var(--surface) !important;
}
.stChatInput:focus-within {
  border-color: rgba(0,0,0,0.2) !important;
  box-shadow: 0 0 0 3px rgba(0,0,0,0.04) !important;
}

/* ── Expander ─────────────────────────────────────────────────── */
.stExpander {
  border: 1px solid var(--border) !important;
  border-radius: var(--radius) !important;
  background: var(--surface) !important;
}
.stExpander:hover { border-color: rgba(0,0,0,0.15) !important; }

/* ── Code Blocks ──────────────────────────────────────────────── */
.stCodeBlock {
  background: var(--surface-alt) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius) !important;
  font-family: var(--font-mono) !important;
  font-size: 0.78rem !important;
  line-height: 1.6 !important;
  color: var(--text-primary) !important;
}

/* ── Status Badges ────────────────────────────────────────────── */
.badge-ready   { background: var(--pastel-green);  color: var(--pastel-green-text);  font-size: 0.65rem; padding: 0.15rem 0.5rem; border-radius: 999px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; }
.badge-indexing { background: var(--pastel-blue);   color: var(--pastel-blue-text);   font-size: 0.65rem; padding: 0.15rem 0.5rem; border-radius: 999px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; }
.badge-failed  { background: var(--pastel-red);    color: var(--pastel-red-text);    font-size: 0.65rem; padding: 0.15rem 0.5rem; border-radius: 999px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; }
.badge-pending { background: var(--pastel-yellow); color: var(--pastel-yellow-text); font-size: 0.65rem; padding: 0.15rem 0.5rem; border-radius: 999px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; }

/* ── Divider ──────────────────────────────────────────────────── */
.stDivider hr { border-color: var(--border) !important; }

/* ── Info boxes ───────────────────────────────────────────────── */
.stAlert {
  background: var(--surface-alt) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius) !important;
  color: var(--text-secondary) !important;
  font-size: 0.8rem !important;
}

/* ── Streamlit default overrides ──────────────────────────────── */
.block-container { padding-top: 1.5rem; padding-bottom: 4rem; max-width: 1100px; }
.css-1r6slb0 { padding-top: 0; }
</style>
"""


# ── API Helper ──────────────────────────────────────────────────────────────
API_BASE = "http://localhost:8000/api"


def _api(path: str, method: str = "GET", **kwargs):
    url = f"{API_BASE}{path}"
    fn = getattr(requests, method.lower())
    resp = fn(url, timeout=30, **kwargs)
    resp.raise_for_status()
    return resp.json()


def _upload_file(file) -> Optional[dict]:
    try:
        resp = _api("/upload", "POST", files={"file": (file.name, file.read())})
        return resp
    except Exception as e:
        st.error(f"上传失败：{e}")
        return None


def _trigger_ingest(doc_id: str) -> dict:
    try:
        return _api(f"/ingest/{doc_id}", "POST")
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def _query(question: str) -> tuple[str, list[dict]]:
    body = {"question": question, "stream": True}
    resp = requests.post(f"{API_BASE}/query", json=body, stream=True, timeout=60)
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


def _status_badge(status: str) -> str:
    cls = {
        "ready": "badge-ready",
        "indexing": "badge-indexing",
        "failed": "badge-failed",
        "pending": "badge-pending",
    }.get(status, "badge-pending")
    label = {"ready": "已入库", "indexing": "入库中", "failed": "失败", "pending": "待入库"}.get(status, status)
    return f'<span class="{cls}">{label}</span>'


# ── 注入全局样式 ────────────────────────────────────────────────────────────
st.markdown(STYLES, unsafe_allow_html=True)


# ── 页面初始化 ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="NexusRAG", page_icon="◆", layout="wide")

# 顶部标题区
st.markdown("<div class='stats-bar' id='stats-bar'></div>", unsafe_allow_html=True)
st.markdown("<h1 style='font-size:1.75rem;font-weight:400;letter-spacing:-0.02em;margin-bottom:0.25rem;'>NexusRAG</h1>", unsafe_allow_html=True)
st.markdown("<p class='stCaption' style='margin-top:-0.5rem;margin-bottom:1.5rem;'>多文档智能问答系统 · FastAPI + Streamlit</p>", unsafe_allow_html=True)


# ── 加载统计数据 ────────────────────────────────────────────────────────────
try:
    stats = _api("/stats")
    st.markdown(f"""
    <div class='stats-bar'>
      <span>DOCUMENTS <span class='stat-value'>{stats['total_documents']}</span></span>
      <span>CHUNKS <span class='stat-value'>{stats['total_chunks']}</span></span>
      <span>DIMENSION <span class='stat-value'>{stats['embedding_dimension']}</span></span>
      <span>STORAGE <span class='stat-value'>{stats['total_size_kb']} KB</span></span>
    </div>
    """, unsafe_allow_html=True)
except Exception:
    pass


# ── 侧边栏 ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("<h2>DOCUMENTS</h2>", unsafe_allow_html=True)

    if st.button("Refresh", key="btn_refresh", use_container_width=True):
        st.rerun()

    try:
        docs = _api("/documents")
    except Exception:
        docs = []

    for doc in docs:
        badge = _status_badge(doc["status"])
        chunk_count = doc.get("chunks", 0)
        latency = doc.get("latency_ms", 0)

        st.markdown(f"""
        <div class='doc-item'>
          <div style='display:flex;align-items:center;justify-content:space-between;margin-bottom:0.25rem;'>
            <span style='font-size:0.85rem;font-weight:500;color:var(--text-primary);'>{doc['filename']}</span>
            {badge}
          </div>
          <div style='font-size:0.72rem;color:var(--text-secondary);font-family:var(--font-mono);'>
            {chunk_count} chunks · {latency:.0f}ms
          </div>
        </div>
        """, unsafe_allow_html=True)

        # 展开详情
        with st.expander("View Details"):
            if doc["status"] in ("pending", "") or chunk_count == 0:
                if st.button("▶ Ingest", key=f"ingest_{doc['id']}", use_container_width=True):
                    with st.spinner(f"Ingesting {doc['filename']}..."):
                        res = _trigger_ingest(doc['id'])
                    st.rerun()
            elif doc["status"] == "ready":
                st.success(f"Completed · {chunk_count} chunks · {latency:.0f}ms")
            elif doc["status"] == "failed":
                st.error(f"Error: {doc.get('error', 'Unknown')}")

            # 切片预览
            try:
                chunk_data = _api(f"/documents/{doc['id']}/chunks")
                cfg = chunk_data
                st.caption(f"Strategy: {cfg['strategy']} · Chunk: {cfg['chunk_size']} · Overlap: {cfg['chunk_overlap']}")
                for ch in cfg.get("chunks", [])[:8]:
                    with st.container():
                        col_idx, col_text = st.columns([1, 9])
                        col_idx.markdown(f"**#{ch['index']}**  ({ch['length']} chars)")
                        col_text.code(ch["text"][:200] + ("…" if len(ch["text"]) > 200 else ""), language="text")
                if cfg.get("total_chunks", 0) > 8:
                    st.caption(f"… {cfg['total_chunks'] - 8} more chunks")
            except Exception:
                st.caption("No chunk data available")

        # 删除按钮（放在 expander 外，循环末尾）
        if st.button("Delete", key=f"del_{doc['id']}"):
            try:
                _api(f"/documents/{doc['id']}", "DELETE")
                st.toast(f"已删除 {doc['filename']}", icon="✅")
            except Exception as e:
                st.error(f"删除失败：{e}")
            st.rerun()

    st.markdown("---")

    st.markdown("<h2>UPLOAD</h2>", unsafe_allow_html=True)
    uploaded = st.file_uploader("PDF / MD / TXT", type=["pdf", "md", "markdown", "txt"], key="file_uploader")
    if uploaded:
        if st.button("Upload", key="btn_upload", use_container_width=True):
            with st.spinner(f"Uploading {uploaded.name}..."):
                resp = _upload_file(uploaded)
            if resp:
                st.success(f"Uploaded: {resp['filename']}")
                st.rerun()

    st.markdown("---")
    st.markdown("""
    <div style='font-size:0.75rem;color:var(--text-secondary);line-height:1.6;'>
      <strong style='color:var(--text-primary);'>Learning Note</strong><br>
      Click a document to expand and inspect chunks.
      Compare different <code style='font-family:var(--font-mono);font-size:0.7rem;background:var(--surface-alt);padding:0.1rem 0.3rem;border-radius:4px;'>chunk_size</code> / <code style='font-family:var(--font-mono);font-size:0.7rem;background:var(--surface-alt);padding:0.1rem 0.3rem;border-radius:4px;'>overlap</code> configurations.
    </div>
    """, unsafe_allow_html=True)


# ── 主区域：对话 ────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("<h2 style='font-size:1.1rem;font-weight:500;letter-spacing:0.04em;text-transform:uppercase;color:var(--text-secondary);margin-bottom:1rem;'>Conversation</h2>", unsafe_allow_html=True)

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("sources"):
            with st.expander("Sources", icon="📎"):
                for s in msg["sources"]:
                    st.markdown(f"**{s.get('doc_name', '?')}**\n\n{s.get('text', '')}")

if prompt := st.chat_input("Ask a question..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        answer = ""
        sources = []
        try:
            answer, sources = _query(prompt)
            placeholder.markdown(answer)
        except Exception as e:
            placeholder.error(f"Query failed: {e}")
        else:
            st.session_state.messages.append({
                "role": "assistant",
                "content": answer,
                "sources": sources,
            })
