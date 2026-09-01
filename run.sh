#!/usr/bin/env bash
# NexusRAG 启动脚本
# 用法: ./run.sh [backend|ui|all]
#   backend : 仅启动 FastAPI 后端 (:8000)
#   ui      : 仅启动 Next.js 前端 (:3000)
#   all     : 同时启动后端 + 前端 (默认)

set -e

cd "$(dirname "$0")"

case "${1:-all}" in
  backend)
    echo "🚀 启动后端 :8000 ..."
    uv run uvicorn src.api.app:app --reload --port 8000
    ;;
  ui)
    echo "🎨 启动前端 :3000 ..."
    cd ui/web
    npm run dev
    ;;
  all)
    # 启动后端
    echo "🚀 启动后端 :8000 ..."
    cd "$(dirname "$0")"
    uv run uvicorn src.api.app:app --reload --port 8000 &
    PID_BACKEND=$!

    # 启动前端
    echo "🎨 启动前端 :3000 ..."
    cd ui/web
    npm run dev &
    PID_FRONTEND=$!

    echo ""
    echo "✅ 全部启动完成"
    echo "   后端: http://localhost:8000"
    echo "   前端: http://localhost:3000"
    echo ""
    echo "按 Ctrl+C 停止所有服务"
    wait $PID_BACKEND $PID_FRONTEND
    ;;
  *)
    echo "用法: ./run.sh [backend|ui|all]"
    exit 1
    ;;
esac
