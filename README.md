# v7ai-fast

基于 FastAPI + LangGraph 构建的企业内部知识库 RAG 智能问答助手平台，AI 辅助开发完成。

## 概述

v7ai-fast 面向企业内部的智能化知识管理与问答平台，集成 WOA（企业IM）消息回调、**LangGraph RAG 智能体**、多模型 AI 对话、知识库文件管理等功能，为企业员工提供即时的智能问答和知识管理能力。

### 核心亮点

- 🧠 **LangGraph RAG Agent** — 智能判断是否检索知识库，自动路由：闲聊直接回答 vs 业务问题检索后回答
- 💬 **WOA 企业IM 集成** — 员工在 IM 中 @机器人 即可提问，自动 AI 回复
- 📚 **知识库管理** — 上传文档 → 自动分片 → pgvector 向量索引 → 语义检索
- 🔍 **智能检索** — 相似度阈值过滤 + 内容去重 + Token 预算控制 + 来源标注
- ⚙️ **多模型管理** — 动态切换 LLM/Embedding 模型，支持 OpenAI 兼容 API
- 📝 **Prompt 模板管理** — 数据库管理提示词模板，一键切换激活

## 系统架构

```
┌──────────────┐     ┌───────────────────────────────┐     ┌─────────────────┐
│   WOA 企业IM  │────>│       FastAPI (v7ai-fast)      │────>│  DeepSeek / OpenAI│
│  消息回调      │     │        端口: 18081              │     │  兼容 AI 服务    │
└──────────────┘     └───────────────┬───────────────┘     └─────────────────┘
                                     │
           ┌─────────────────────────┼─────────────────────────┐
           ▼                         ▼                          ▼
  ┌────────────────┐    ┌──────────────────────┐    ┌──────────────────┐
  │  PostgreSQL     │    │  MinIO (对象存储)      │    │  Web Chat UI     │
  │  + pgvector     │    │  文件 + Embedding     │    │  + Admin Panel   │
  └────────────────┘    └──────────────────────┘    └──────────────────┘
```

### RAG Pipeline

```
用户提问 → LangGraph Agent
              │
              ├─ classify ────── 闲聊 ──→ generate (直接回答)
              │
              └─ classify ────── 业务 ──→ retrieve (pgvector)
                                              │
                                              ▼
                                         generate (带上下文回答)
                                              │
                                              ▼
                                     [来源: xxx文档] 标注引用
```

## 功能清单

| 模块 | 状态 | 功能 |
|------|------|------|
| 🤖 **LangGraph RAG** | ✅ 已完成 | 智能路由 classify→retrieve→generate |
| 💬 **AI 对话** | ✅ 已完成 | Web Chat + WOA IM 双通道 |
| 📚 **知识库** | ✅ 已完成 | 上传/下载/删除/索引/检索 |
| 🔍 **向量检索** | ✅ 已完成 | pgvector 语义搜索 + 相似度过滤 + 去重 |
| ⚙️ **模型管理** | ✅ 已完成 | LLM/Embedding 多模型配置，一键激活 |
| 📝 **Prompt 管理** | ✅ 已完成 | 提示词模板 CRUD + 激活 + 变量占位 |
| 🔐 **用户认证** | ✅ 已完成 | JWT 登录/注册 |
| 💾 **数据持久化** | ✅ 已完成 | PostgreSQL 全量持久化 |
| 🗄️ **对象存储** | ✅ 已完成 | MinIO S3，文件 UUID 命名 |
| 📊 **管理面板** | ✅ 已完成 | Admin 页面：模型配置 + 会话 + Prompt |
| 🧠 **记忆系统** | 📋 规划中 | 多轮对话上下文 + 用户偏好 + 长期记忆 |
| 🔌 **MCP 模块** | 📋 规划中 | Model Context Protocol，工具调用 |
| 📈 **日志监控** | 📋 规划中 | 调用统计 + 成本分析 + 告警 |

## 项目结构

```
v7ai-fast/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── endpoints/
│   │       │   ├── auth.py         # 认证 API
│   │       │   ├── knowledge.py    # 知识库 API（上传/索引/检索）
│   │       │   ├── model.py        # 模型配置 CRUD API
│   │       │   ├── prompt.py       # Prompt 模板 CRUD API
│   │       │   ├── web.py          # Web 页面 + Chat API + Admin
│   │       │   └── woa.py          # WOA 事件回调
│   │       └── __init__.py
│   │   └── __init__.py
│   ├── core/
│   │   ├── database.py             # 7 个 ORM 模型 (PostgreSQL)
│   │   ├── logging.py              # 日志配置
│   │   ├── security.py             # 签名验证 + 加密解密
│   │   └── settings.py             # Pydantic Settings
│   ├── services/
│   │   ├── agent.py                # LangGraph RAG Agent
│   │   ├── auth.py                 # JWT 认证
│   │   ├── deepseek.py             # AI 模型调用（OpenAI 兼容）
│   │   ├── embedding.py            # HuggingFace 向量化
│   │   ├── indexer.py              # 文档解析 + 分片 + 向量存储
│   │   ├── knowledge.py            # 知识库文件管理（MinIO）
│   │   ├── model_config.py         # 模型配置管理
│   │   ├── prompt.py               # Prompt 模板管理
│   │   ├── session.py              # 会话管理
│   │   └── woa.py                  # WOA 消息发送
│   └── templates/
│       ├── admin.html              # 管理面板
│       ├── chat_full.html          # Chat UI
│       ├── knowledge.html          # 知识库管理
│       ├── login.html / register.html
│       └── session_detail.html
├── main.py
├── pyproject.toml
└── .env
```

## 数据库模型

| 表名 | 用途 |
|------|------|
| `users` | 用户认证 |
| `chat_sessions` | 聊天会话 |
| `chat_messages` | 聊天消息 |
| `model_configs` | AI 模型配置 |
| `knowledge_files` | 知识库文件记录 |
| `document_chunks` | 文档分片向量 (pgvector) |
| `prompt_templates` | Prompt 提示词模板 |
| `system_settings` | 系统参数 |
| `event_logs` | WOA 事件日志 |

## API 端点

| 前缀 | 功能 |
|------|------|
| `/api/v1/auth/*` | 注册/登录/Token |
| `/api/v1/model/*` | 模型配置 CRUD |
| `/api/v1/knowledge/*` | 文件上传/下载/索引/检索 |
| `/api/v1/prompt/*` | Prompt 模板 CRUD |
| `/callback/eventmsg` | WOA 事件回调 |
| `/api/chat` | Web 聊天 |
| `/admin` | 管理面板 |

## 技术栈

| 类别 | 组件 |
|------|------|
| **框架** | FastAPI + Uvicorn |
| **Agent** | LangGraph |
| **LLM** | langchain-openai (DeepSeek / OpenAI 兼容) |
| **Embedding** | sentence-transformers (all-MiniLM-L6-v2) |
| **向量库** | pgvector (PostgreSQL 扩展) |
| **存储** | MinIO (S3 兼容) |
| **ORM** | SQLAlchemy 2.0 |
| **认证** | python-jose (JWT) + passlib (bcrypt) |
| **解析** | openpyxl + pypdf + python-docx |
| **依赖** | uv |

## 快速开始

### 1. 环境要求

- Python >= 3.11
- PostgreSQL + pgvector 扩展
- MinIO 对象存储

### 2. 安装

```bash
uv sync
cp .env.example .env  # 编辑配置
```

### 3. 数据库初始化

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 4. 启动

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 18081 --reload
```

### 5. 访问

| URL | 说明 |
|-----|------|
| `http://localhost:18081/chat` | 聊天界面 |
| `http://localhost:18081/knowledge` | 知识库管理 |
| `http://localhost:18081/admin` | 管理面板 |
| `http://localhost:18081/docs` | API 文档 |

## License

MIT
