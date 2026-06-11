# v7ai-fast

基于 FastAPI 构建的企业内部知识库智能问答助手平台，AI 辅助开发完成。

## 概述

v7ai-fast 是一个面向企业内部的智能化知识管理与问答平台，集成 WOA（企业IM）消息回调、多模型 AI 对话、知识库文件管理等功能，为企业员工提供即时的智能问答服务和知识管理能力。

核心能力：
- 通过 WOA 消息回调，员工在企业 IM 中直接向 AI 提问
- 支持多模型切换（DeepSeek、OpenAI、自定义 API），灵活配置
- 文件上传自动存储至 MinIO 对象存储，支持文档知识库管理
- Web 聊天界面，支持多会话、会话持久化
- 用户注册/登录，JWT 认证

## 功能特性

### 核心功能

| 模块 | 功能 | 说明 |
|------|------|------|
| 🤖 **AI 对话** | 智能问答 | 支持流式对话，可切换后端模型 |
| 📚 **知识库** | 文件管理 | 上传/下载/删除文档，支持 TXT/PDF/Excel/Word/Markdown/CSV |
| 💬 **WOA 集成** | 企业IM回调 | 接收 WOA 消息，自动 AI 回复，支持 KSO-1/WPS-3 签名 |
| ⚙️ **模型管理** | 动态切换 | 多模型配置，一键激活，支持自定义 API 地址/密钥 |
| 🔐 **用户认证** | JWT | 注册/登录，会话管理，Token 鉴权 |
| 💾 **数据持久化** | PostgreSQL | 聊天记录、会话、模型配置、知识库文件记录全量持久化 |
| 🗄️ **对象存储** | MinIO | 文件存储于 MinIO S3 兼容存储，UUID 命名防冲突 |

### 模型支持

- DeepSeek（deepseek-chat / deepseek-v4-pro 等）
- OpenAI 兼容 API（支持 New API、One API 等网关）
- 自定义 API 端点（自建模型服务）

## 项目结构

```
v7ai-fast/
├── app/
│   ├── api/                        # API 路由层
│   │   └── v1/
│   │       ├── endpoints/
│   │       │   ├── auth.py         # 认证 API（注册/登录/Token）
│   │       │   ├── knowledge.py    # 知识库 API（上传/下载/列表/删除/统计）
│   │       │   ├── model.py        # 模型配置 CRUD API
│   │       │   ├── web.py          # Web 页面路由 + 聊天 API
│   │       │   └── woa.py          # WOA 事件回调 API
│   │       └── __init__.py         # v1 路由聚合
│   │   └── __init__.py             # 根路由
│   ├── core/                       # 核心模块
│   │   ├── database.py             # ORM 模型 + 数据库会话
│   │   ├── logging.py              # 日志配置
│   │   ├── security.py             # 安全工具（签名验证、加密解密）
│   │   └── settings.py             # 配置管理（Pydantic Settings）
│   ├── services/                   # 业务服务层
│   │   ├── auth.py                 # JWT 认证服务
│   │   ├── deepseek.py             # AI 模型调用服务
│   │   ├── knowledge.py            # 知识库文件管理服务（MinIO SDK）
│   │   ├── model_config.py         # 模型配置管理服务
│   │   ├── session.py              # 会话管理服务
│   │   └── woa.py                  # WOA 消息服务
│   └── templates/                  # HTML 模板
│       ├── admin.html              # 管理面板
│       ├── chat_full.html          # 聊天界面（含侧边栏）
│       ├── knowledge.html          # 知识库管理页面
│       ├── login.html              # 登录页面
│       └── register.html           # 注册页面
├── static/                         # 静态资源
│   └── index.html
├── main.py                         # 应用入口
├── pyproject.toml                  # 项目配置（uv 管理）
├── .env                            # 环境变量
└── README.md
```

## 架构

```
┌──────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│   WOA 企业IM  │────>│  FastAPI (v7ai-fast) │────>│  DeepSeek / 自建  │
│  消息回调      │     │  端口: 18081          │     │  AI 模型服务      │
└──────────────┘     └──────────┬───────────┘     └─────────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                  ▼
     ┌────────────┐   ┌──────────────┐   ┌──────────────┐
     │ PostgreSQL │   │   MinIO      │   │  Web 浏览器   │
     │ 10.12.33.92│   │ 10.12.33.92 │   │  (Chat UI)   │
     └────────────┘   └──────────────┘   └──────────────┘
```

## 技术栈

| 组件 | 用途 |
|------|------|
| **FastAPI** | Web 框架 |
| **SQLAlchemy** | ORM |
| **PostgreSQL** | 数据库 |
| **MinIO** | 对象存储（S3 兼容） |
| **Jinja2** | 模板引擎 |
| **Pydantic** | 数据验证 |
| **python-jose** | JWT 认证 |
| **passlib + bcrypt** | 密码哈希 |
| **httpx** | 异步 HTTP 客户端 |
| **uv** | 依赖管理 |

## 快速开始

### 1. 环境要求

- Python >= 3.11
- PostgreSQL（服务器 `10.12.33.92:5432`）
- MinIO（服务器 `10.12.33.92:9000`）

### 2. 安装依赖

```bash
uv sync
```

### 3. 配置环境变量

编辑 `.env` 文件：

```env
# 服务配置
SERVER_PORT=18081

# WOA 配置
WOA_CONFIG_APP_ID=你的APP_ID
WOA_CONFIG_APP_KEY=你的APP_KEY
WOA_HOST=https://im2.yungongplat.com:9000

# DeepSeek 配置
DEEPSEEK_API_KEY=你的API_KEY
DEEPSEEK_MODEL=deepseek-chat

# 数据库（PostgreSQL）
DB_HOST=10.12.33.92
DB_PORT=5432
DB_USER=admin
DB_PASSWORD=你的密码
DB_NAME=appdb

# MinIO 对象存储
MINIO_ENDPOINT=10.12.33.92:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=knowledge-base
MINIO_SECURE=false
```

### 4. 启动服务

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 18081 --reload
```

### 5. 访问

| 地址 | 说明 |
|------|------|
| `http://localhost:18081/` | 健康检查 |
| `http://localhost:18081/chat` | 聊天界面 |
| `http://localhost:18081/knowledge` | 知识库管理 |
| `http://localhost:18081/admin` | 管理面板 |
| `http://localhost:18081/docs` | Swagger API 文档 |

## 依赖中间件部署

### MinIO

```bash
docker run -d --name minio \
  -p 9000:9000 -p 9001:9001 \
  -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD=minioadmin \
  -v /data/minio:/data \
  minio/minio:RELEASE.2024-08-03T04-33-23Z server /data --console-address ":9001"
```

安装后访问 `http://10.12.33.92:9001` 创建 Bucket `knowledge-base`。


## License

MIT
