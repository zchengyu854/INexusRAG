#!/usr/bin/env bash
# NexusRAG 启动脚本
# 用法:
#   ./run.sh [backend|ui|preview|all]
#   ./run.sh preview data/test_docs/fastapi_readme.md [--chunk-size 300] [-v]

set -e

case "${1:-all}" in
  backend)
    echo "🚀 启动后端 :8000 ..."
    uv run uvicorn src.api.app:app --reload --port 8000
    ;;
  ui)
    echo "🎨 启动 UI :8501 ..."
    uv run streamlit run ui/app.py --server.port 8501
    ;;
  preview)
    shift
    echo "🔍 预览文档切分 ..."
    exec uv run python -m src.cli.preview "$@"
    ;;
  all)
    echo "🚀 启动后端 :8000 ..."
    uv run uvicorn src.api.app:app --reload --port 8000 &
    PID_API=$!
    echo "🎨 启动 UI :8501 ..."
    uv run streamlit run ui/app.py --server.port 8501 &
    PID_UI=$!
    echo ""
    echo "✅ 全部启动完成"
    echo "   后端: http://localhost:8000"
    echo "   UI:   http://localhost:8501"
    echo ""
    echo "按 Ctrl+C 停止所有服务"
    wait $PID_API $PID_UI
    ;;
  *)
    echo "用法: ./run.sh [backend|ui|preview|all]"
    exit 1
    ;;
esac
