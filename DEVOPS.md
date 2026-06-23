# v7ai-fast DevOps 部署指南

## 概述

本文档描述如何将 v7ai-fast 项目容器化并实现一键部署。

## 新增文件

| 文件 | 用途 |
|------|------|
| `Dockerfile` | 应用容器镜像定义（多阶段构建） |
| `.dockerignore` | 排除不打包进镜像的文件 |
| `.env.docker` | Docker 环境专用配置（容器名通信） |
| `deploy.sh` | 一键部署/管理脚本 |
| `docker-compose.yml` | **已更新**，新增 `app` 服务 |

## 架构变化

```
Before（Plan A 前）:
  docker compose up → PostgreSQL + MinIO
  应用直接跑在宿主机 python main.py

After（Plan A 后）:
  docker compose up → PostgreSQL + MinIO + v7ai-fast(容器)
  三个服务统一由 docker compose 管理
```

## 快速开始

### 1. 确保数据目录存在
```bash
mkdir -p /home/cgl/v7ai-data/{postgres,minio,app/data,app/logs}
```

### 2. 一键部署
```bash
cd /mnt/e/ai/v7ai-fast
./deploy.sh full
```

### 3. 验证
```bash
# 查看运行状态
./deploy.sh status

# 访问服务
curl http://localhost:18081/
# → {"status":"ok","service":"v7ai-fast"}
```

## deploy.sh 命令速查

```bash
./deploy.sh build      # 仅构建镜像
./deploy.sh up         # 启动所有服务
./deploy.sh down       # 停止所有服务
./deploy.sh restart    # 重启应用
./deploy.sh logs       # 查看应用日志
./deploy.sh status     # 查看服务状态
./deploy.sh full       # 构建 + 启动
./deploy.sh clean      # 停止并清理
```

## 注意事项

1. **首次启动**可能需要几分钟，sentence-transformers 会自动下载 Embedding 模型
2. `.env.docker` 含密钥，**不要提交到 Git**
3. 数据持久化在 `/home/cgl/v7ai-data/` 下，删除容器不会丢数据
4. Docker 网络内服务通过容器名通信（`postgres`、`minio`）
