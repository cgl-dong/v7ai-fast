# v7ai-fast

基于 FastAPI 的 WOA 智能助手后端服务

## 功能特性

- 🔐 **WOA 事件回调** - 接收并处理 WOA 平台的事件回调
- 🤖 **DeepSeek AI 集成** - 调用 DeepSeek 模型进行智能问答
- ✉️ **消息发送** - 自动将 AI 回复发送给用户
- 🔑 **签名验证** - 支持 KSO-1 和 WPS-3 签名方式
- 🌐 **CORS 支持** - 跨域访问配置

## 项目结构

```
v7ai-fast/
├── app/
│   ├── controllers/
│   │   ├── callback_controller.py  # WOA 回调接口
│   │   └── index_controller.py     # 首页重定向
│   ├── services/
│   │   ├── deepseek_service.py     # DeepSeek 模型服务
│   │   ├── woa_service.py          # WOA 消息服务
│   │   └── spark_service.py        # Spark 模型服务
│   ├── utils/
│   │   ├── crypto.py               # 加密解密工具
│   │   └── wps_signature.py        # WPS3 签名工具
│   └── models.py                   # 数据模型
├── static/
│   └── index.html                  # 静态页面
├── main.py                         # 应用入口
├── pyproject.toml                  # 项目配置
└── .env.example                    # 环境变量示例
```

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env` 并配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
SERVER_PORT=18081

# WOA 配置
WOA_CONFIG_APP_ID=你的APP_ID
WOA_CONFIG_APP_KEY=你的APP_KEY
WOA_HOST=https://im2.yungongplat.com:9000

# DeepSeek 配置
DEEPSEEK_API_KEY=你的DEEPSEEK_API_KEY
DEEPSEEK_MODEL=deepseek-chat
```

### 3. 启动服务

```bash
uv run python main.py
```

或使用 uvicorn：

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 18081 --reload
```

### 4. 访问服务

- API 文档：http://localhost:18081/docs
- 健康检查：http://localhost:18081/
- 首页：http://localhost:18081/v7

## API 接口

### WOA 事件回调

```
POST /callback/eventmsg
```

接收 WOA 平台的事件回调，自动处理签名验证、数据解密、AI 问答和消息回复。

### 健康检查

```
GET /
```

返回服务状态信息。

## 环境变量说明

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `SERVER_PORT` | 服务端口 | 否 |
| `WOA_CONFIG_APP_ID` | WOA 应用 ID | 是 |
| `WOA_CONFIG_APP_KEY` | WOA 应用密钥 | 是 |
| `WOA_HOST` | WOA 服务器地址 | 是 |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | 是 |
| `DEEPSEEK_MODEL` | DeepSeek 模型名称 | 否 |

## 技术栈

- **框架**: FastAPI
- **服务器**: Uvicorn
- **HTTP 客户端**: httpx
- **数据验证**: Pydantic
- **环境管理**: uv

## License

MIT
