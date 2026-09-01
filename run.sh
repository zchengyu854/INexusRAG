#!/usr/bin/env bash
# NexusRAG 启动脚本
# 用法: ./run.sh [backend|ui|all]

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
    echo "用法: ./run.sh [backend|ui|all]"
    exit 1
    ;;
esac
