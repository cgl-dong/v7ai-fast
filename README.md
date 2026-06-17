# v7ai-fast

基于 FastAPI + LangGraph 构建的企业内部知识库 RAG 智能问答助手平台，AI 辅助开发完成。

## 概述

v7ai-fast 面向企业内部的智能化知识管理与问答平台，集成 WOA（企业IM）消息回调、**LangGraph RAG 智能体**、多模型 AI 对话、知识库文件管理、**AI 裁判自动评价**等功能，为企业员工提供即时的智能问答和知识管理能力。

### 核心亮点

- 🧠 **LangGraph RAG Agent** — 智能判断是否检索知识库，自动路由：闲聊直接回答 vs 业务问题检索后回答
- 🤖 **AI Judge 双轨评价** — LLM-as-Judge 自动评分 + 人工复核，多维度质量量化
- 📚 **知识库管理** — 上传文档 → 自动分片（LlamaIndex）→ pgvector 向量索引 → 语义检索
- 🔍 **智能检索** — 多策略分片（句子/段落/Token/章节）+ 相似度过滤 + 知识库分类
- ⭐ **评分系统** — Trace/Observation 多维度打分，AI vs 人工对比分析
- 📊 **可观测性** — AI 调用链路追踪 + 日志文件滚动存储
- ⚙️ **多模型管理** — 动态切换 LLM/Embedding 模型，支持 OpenAI 兼容 API
- 📝 **Prompt 模板管理** — 数据库管理提示词模板，一键切换激活
- 💬 **WOA 企业IM 集成** — 员工在 IM 中 @机器人 即可提问，自动 AI 回复
- ⚡ **SSE 流式对话** — Server-Sent Events 逐 token 推送，打字机效果实时渲染
- 🧠 **智能记忆** — 历史对话注入 + Token 预算控制 + 自动摘要压缩

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
                          ┌───────────────────┘
                          ▼
                    AI Judge (fire-and-forget)
                    独立模型自动评分 + 维度理由
```

### AI Judge 双轨评价

```
每次回答完成后 ──→ AI Judge (t=0.1, 独立模型)
                     │
                     ├─ 评分维度: accuracy / fluency / usefulness...
                     ├─ 每个维度附带评价理由 (dimension_reasons)
                     └─ 存入 trace_ratings (rater_type="ai")
                             │
人工后续评价 ─────────────────┤
                             ├─ 存入 trace_ratings (rater_type="human")
                             │
可观测性面板 ←────────────────┘
├─ 🤖 AI 裁判: 4.2/5
├─ 👤 人工: 3.8/5
└─ 对比分析、趋势图
```

### 知识库分片策略

使用 LlamaIndex 多策略文本切分，按文件类型自动选择：

| 策略 | 实现 | 适用类型 | 默认 chunk_size |
|------|------|---------|:-:|
| `sentence` | SentenceSplitter，句子边界切分 | PDF, DOCX | 1024 |
| `paragraph` | 段落切分 + SentenceSplitter | TXT, MD | 2048 |
| `token` | TokenTextSplitter，Token 精确切分 | 对齐模型窗口 | 512 |
| `fixed` | 固定长度切分 + 重叠 | CSV | 2048 |
| `excel` | 行分组切分，每 5 行一个 chunk | XLSX | — |

每文件可自定义策略和参数，索引时覆盖。

## 功能清单

| 模块 | 状态 | 功能 |
|------|------|------|
| 🤖 **LangGraph RAG** | ✅ 已完成 | 智能路由 classify→retrieve→generate |
| 🤖 **AI Judge** | ✅ 已完成 | LLM-as-Judge 自动评分 + 人工复核 |
| 💬 **AI 对话** | ✅ 已完成 | Web Chat + WOA IM 双通道 |
| 📚 **知识库** | ✅ 已完成 | 上传/预览/下载/索引/软删除/分类绑定 |
| 🔍 **向量检索** | ✅ 已完成 | pgvector 语义搜索 + 分片策略可选 |
| 📄 **文件预览** | ✅ 已完成 | PDF/DOCX/XLSX/TXT 在线预览 |
| ⭐ **评分系统** | ✅ 已完成 | Trace/Observation 多维度打分 + AI/人工对比 |
| 📊 **可观测性** | ✅ 已完成 | AI 调用链路追踪 + 日志文件 |
| 📝 **日志系统** | ✅ 已完成 | 全链路 DEBUG 日志 + 50MB 滚动文件 |
| ⚙️ **模型管理** | ✅ 已完成 | LLM/Embedding 多模型配置，一键激活 |
| 📝 **Prompt 管理** | ✅ 已完成 | 提示词模板 CRUD + 激活 + 变量占位 |
| 🔐 **用户认证** | ✅ 已完成 | JWT 登录/注册 |
| 💾 **数据持久化** | ✅ 已完成 | PostgreSQL 全量持久化 |
| 🗄️ **对象存储** | ✅ 已完成 | MinIO S3，文件 UUID 命名 |
| 🧠 **记忆系统** | ✅ 已完成 | 历史对话注入 + Token 预算 + 摘要压缩 |
| ⚡ **SSE 流式** | ✅ 已完成 | Server-Sent Events 逐 token 推送 |
| 📊 **管理面板** | ✅ 已完成 | Admin 页面：模型配置 + 会话 + Prompt |
| 🔌 **MCP 模块** | 📋 规划中 | Model Context Protocol，工具调用 |
| 📈 **日志监控** | 📋 规划中 | 调用统计 + 成本分析 + 告警 |

## 项目结构

```
v7ai-fast/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── endpoints/
│   │       │   ├── auth.py           # 认证 API
│   │       │   ├── knowledge.py      # 知识库 API（上传/预览/索引/检索/KB管理）
│   │       │   ├── model.py          # 模型配置 CRUD API
│   │       │   ├── prompt.py         # Prompt 模板 CRUD API
│   │       │   ├── web.py            # Web 页面 + Chat API + Admin + Knowledge
│   │       │   ├── woa.py            # WOA 事件回调
│   │       │   └── observability.py  # 可观测性 API（追踪 + 评分）
│   │       └── __init__.py
│   │   └── __init__.py
│   ├── core/
│   │   ├── database.py               # 11 个 ORM 模型 (PostgreSQL + pgvector)
│   │   ├── logging.py                # 日志配置（控制台 INFO + 文件 DEBUG, 50MB×5）
│   │   ├── security.py               # 签名验证 + 加密解密
│   │   └── settings.py               # Pydantic Settings
│   ├── services/
│   │   ├── agent.py                  # LangGraph RAG Agent + AI Judge 触发
│   │   ├── auth.py                   # JWT 认证
│   │   ├── chunking.py               # LlamaIndex 多策略文本切分
│   │   ├── deepseek.py               # AI 模型调用（OpenAI 兼容）
│   │   ├── embedding.py              # BGE-base-zh-v1.5 向量化 (768 dims)
│   │   ├── indexer.py                # 文档解析 + 分片 + 向量存储 + 内容校验
│   │   ├── judge.py                  # AI Judge 自动评价服务
│   │   ├── kb_service.py             # 知识库分类 CRUD + 软删除
│   │   ├── knowledge.py              # 知识库文件管理（MinIO）
│   │   ├── model_config.py           # 模型配置管理
│   │   ├── prompt.py                 # Prompt 模板管理
│   │   ├── rating.py                 # 多维度评分服务
│   │   ├── session.py                # 会话管理
│   │   ├── observability.py          # 可观测性追踪服务
│   │   └── woa.py                    # WOA 消息发送
│   └── templates/
│       └── chat_full.html            # Chat UI（marked.js Markdown 渲染）
├── logs/                             # 日志文件目录 (app.log)
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
| `knowledge_bases` | 知识库分类（支持软删除） |
| `knowledge_files` | 知识库文件记录（含切分策略） |
| `document_chunks` | 文档分片向量 (pgvector, 768 dims) |
| `prompt_templates` | Prompt 提示词模板 |
| `system_settings` | 系统参数 |
| `ai_traces` | AI 调用追踪（可观测性） |
| `trace_ratings` | 多维度质量评分（AI/人工） |
| `event_logs` | WOA 事件日志 |

## API 端点

| 前缀 | 功能 |
|------|------|
| `/api/v1/auth/*` | 注册/登录/Token |
| `/api/v1/model/*` | 模型配置 CRUD |
| `/api/v1/knowledge/*` | 文件上传/预览/下载/索引/检索/KB 管理 |
| `/api/v1/prompt/*` | Prompt 模板 CRUD |
| `/api/v1/observability/*` | 追踪记录查询 + 评分 + AI/人工对比 |
| `/api/chat` | Web 聊天（Markdown 渲染） |
| `/api/chat/stream` | SSE 流式聊天（逐 token 推送） |
| `/callback/eventmsg` | WOA 事件回调 |
| `/knowledge` | 知识库管理页面 |
| `/admin` | 管理面板 |
| `/observability` | 可观测性面板 |

## 技术栈

| 类别 | 组件 |
|------|------|
| **框架** | FastAPI + Uvicorn |
| **Agent** | LangGraph |
| **LLM** | langchain-openai (DeepSeek / OpenAI 兼容) |
| **Embedding** | sentence-transformers (BAAI/bge-base-zh-v1.5, 768 dims) |
| **分片** | LlamaIndex (SentenceSplitter / TokenTextSplitter) |
| **向量库** | pgvector (PostgreSQL 扩展) |
| **存储** | MinIO (S3 兼容) |
| **ORM** | SQLAlchemy 2.0 |
| **认证** | python-jose (JWT) + bcrypt |
| **解析** | openpyxl + pypdf + python-docx |
| **Markdown** | marked.js (前端渲染) |
| **依赖管理** | uv |

## 快速开始

### 1. 环境要求

- Python >= 3.10
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
uv run --active python main.py
```

### 5. 访问

| URL | 说明 |
|-----|------|
| `http://localhost:18081/chat` | 聊天界面（Markdown 渲染） |
| `http://localhost:18081/knowledge` | 知识库管理（上传/预览/索引/分类） |
| `http://localhost:18081/admin` | 管理面板 |
| `http://localhost:18081/observability` | 可观测性面板（追踪 + 评分对比） |
| `http://localhost:18081/docs` | API 文档 |

## License

MIT
