# v7ai-fast 开发路线图

## 已完成 ✅

### Phase 1 — 基础框架
- [x] FastAPI 项目骨架 + PostgreSQL + uv 依赖管理
- [x] JWT 用户认证（注册/登录/Token）
- [x] WOA 企业IM 消息回调（签名验证 + 解密 + AI 回复）
- [x] DeepSeek AI 模型调用服务
- [x] Web Chat 界面 + 多会话管理

### Phase 2 — 知识库
- [x] MinIO 对象存储集成（文件上传/下载/删除）
- [x] 知识库管理前端页面（拖拽上传 + 列表 + 统计）
- [x] 文档解析（TXT/PDF/Excel/Word/Markdown/CSV）
- [x] 文档分片（1000字符/chunk，200重叠）
- [x] HuggingFace Embedding（all-MiniLM-L6-v2，384维）
- [x] pgvector 向量存储与语义检索
- [x] 批量索引 + 单个索引

### Phase 3 — 智能增强
- [x] LangGraph RAG Agent（classify → retrieve → generate）
- [x] 相似度阈值过滤（< 0.45 丢弃）
- [x] 内容去重（词重合度 >60% 过滤）
- [x] Token 预算控制（最大 3000 字符上下文）
- [x] 来源引用标注（[来源: 文件名]）
- [x] Prompt 模板管理（数据库 CRUD + 激活切换）
- [x] 多模型动态切换（Admin 面板管理）

---

## 下一步开发 📋

### Phase 4 — 记忆系统 (Memory)

**目标**：让 Agent 记住对话上下文，支持多轮对话和用户偏好。

| 任务 | 说明 | 优先级 |
|------|------|--------|
| **对话记忆** | LangGraph 集成 `MemorySaver`，自动持久化对话状态到 PostgreSQL | 🔴 高 |
| **上下文窗口管理** | 智能截断历史消息，保留最近 N 轮 + 摘要压缩 | 🔴 高 |
| **用户偏好记忆** | 记录用户常用模型、语言偏好、高频问题 | 🟡 中 |
| **长期记忆** | 将重要对话摘要存储为知识库文档，可被后续检索 | 🟡 中 |
| **会话摘要** | 超长对话自动生成摘要，替换旧消息节省 token | 🟢 低 |

**技术方案**：
```
LangGraph MemorySaver → PostgreSQL checkpoint 表
    ├── 短期记忆：对话历史（最近10轮）
    ├── 摘要记忆：超长对话自动压缩
    └── 长期记忆：关键信息写入知识库
```

---

### Phase 5 — MCP 模块 (Model Context Protocol)

**目标**：Agent 通过 MCP 协议调用外部工具和服务。

| 任务 | 说明 | 优先级 |
|------|------|--------|
| **MCP Server 框架** | FastAPI 内嵌 MCP Server，注册工具 | 🔴 高 |
| **内置工具集** | 知识库检索、文件查询、模型切换 | 🔴 高 |
| **数据库查询工具** | Agent 可通过 SQL 查询业务数据库 | 🟡 中 |
| **HTTP 工具调用** | Agent 可调用外部 REST API | 🟡 中 |
| **工具编排** | LangGraph ToolNode 动态工具选择 | 🟡 中 |
| **权限控制** | 工具调用需鉴权，操作日志记录 | 🟢 低 |

**技术方案**：
```
User → LangGraph Agent
         ├── Tool: search_knowledge(query)
         ├── Tool: query_database(sql)
         ├── Tool: get_file_content(file_id)
         └── Tool: switch_model(model_name)
```

---

### Phase 6 — 日志监控 (Observability)

**目标**：可观测的 AI 调用链路，成本分析与告警。

| 任务 | 说明 | 优先级 |
|------|------|--------|
| **调用日志** | 每次 AI 调用的 token 消耗、延迟、模型记录 | 🔴 高 |
| **LangSmith 集成** | LangGraph 链路追踪可视化 | 🟡 中 |
| **成本看板** | Admin 面板显示各模型调用量、费用统计 | 🟡 中 |
| **异常告警** | 模型不可用、token 超限、错误率过高推送通知 | 🟢 低 |
| **用户行为分析** | 高频问题统计、热门文档排行 | 🟢 低 |

---

### Phase 7 — 高级功能

| 任务 | 说明 | 优先级 |
|------|------|--------|
| **流式输出 (SSE)** | Chat 接口支持 Server-Sent Events 流式回答 | 🔴 高 |
| **多租户** | 不同部门的独立知识库、模型、Prompt 隔离 | 🟡 中 |
| **文档自动同步** | 监听 MinIO 事件，新文件自动索引 | 🟡 中 |
| **混合检索** | BM25 关键词 + 语义向量混合检索，提升召回率 | 🟡 中 |
| **Reranker 重排序** | 检索后 BGE-Reranker 二次排序，提升准确率 | 🟡 中 |
| **多模态** | 支持图片、OCR 识别、表格理解 | 🟢 低 |
| **知识图谱** | 实体关系抽取，构建企业知识图谱 | 🟢 低 |

---

## 技术债务 & 改进

| 任务 | 说明 |
|------|------|
| **jinja2 缓存修复** | Windows 下 `cache_size=0` 无效，当前用内联 HTML 规避，需彻底解决 |
| **错误处理统一化** | 各端点错误返回格式不一致，需统一 `error_handler` |
| **API 限流** | 当前无 QPS 限制，需添加 `slowapi` 或 Redis 限流 |
| **单元测试** | 当前零测试，需补充 service 层 + endpoint 层测试 |
| **Docker 部署** | 补充 docker-compose 一键部署（含 PostgreSQL + MinIO） |
| **配置文档** | `.env.example` 模板文件 |

---

## 优先级排序建议

```
Phase 4 记忆系统  ← 下一步
    ↓
Phase 5 MCP 模块  ← 能力扩展
    ↓
Phase 6 日志监控  ← 生产化
    ↓
流式输出 (SSE)   ← 体验优化
    ↓
Phase 7 高级功能  ← 竞争力提升
```
