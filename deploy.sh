#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# v7ai-fast 一键部署脚本
# 用法: ./deploy.sh [build|up|down|restart|logs|status]
# ═══════════════════════════════════════════════════════════════
set -e

cd "$(dirname "$0")"
PROJECT="v7ai-fast"

show_help() {
    echo "v7ai-fast 部署脚本"
    echo ""
    echo "用法: ./deploy.sh <命令>"
    echo ""
    echo "命令:"
    echo "  build      仅构建镜像"
    echo "  up         启动所有服务（后台运行）"
    echo "  down       停止所有服务"
    echo "  restart    重启应用服务"
    echo "  logs       查看应用日志（Ctrl+C 退出）"
    echo "  status     查看服务运行状态"
    echo "  full       完整部署流程：构建 + 启动 + 状态"
    echo "  clean      清理：停止 + 删除镜像"
}

build() {
    echo "🔨 构建镜像..."
    docker compose build app
    echo "✅ 镜像构建完成"
}

up() {
    echo "🚀 启动所有服务..."
    docker compose up -d
    echo ""
    echo "⏳ 等待服务就绪..."
    sleep 5
    echo "✅ 服务已启动"
    echo ""
    status
}

down() {
    echo "🛑 停止所有服务..."
    docker compose down
    echo "✅ 服务已停止"
}

restart() {
    echo "🔄 重启应用服务..."
    docker compose restart app
    echo "✅ 应用已重启"
}

logs() {
    echo "📋 查看应用日志 (Ctrl+C 退出)..."
    docker compose logs -f app
}

status() {
    echo "📊 服务状态:"
    echo "───────────"
    docker compose ps
    echo ""
    echo "🌐 访问地址:"
    echo "   API 文档:  http://localhost:18081/docs"
    echo "   Web Chat:  http://localhost:18081/v7"
    echo "   MinIO:     http://localhost:9001"
}

clean() {
    echo "🧹 清理..."
    docker compose down -v
    docker rmi ${PROJECT}-app 2>/dev/null || true
    echo "✅ 清理完成"
}

full() {
    echo "══════════════════════════════════════════"
    echo "  v7ai-fast 完整部署"
    echo "══════════════════════════════════════════"
    build
    up
}

# ── 主入口 ─────────────────────────────────────────────────
case "${1:-}" in
    build)   build ;;
    up)      up ;;
    down)    down ;;
    restart) restart ;;
    logs)    logs ;;
    status)  status ;;
    clean)   clean ;;
    full)    full ;;
    *)       show_help ;;
esac
