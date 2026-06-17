"""Database engine, session factory, and ORM models.
Uses PostgreSQL — configure via DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME in .env.
"""
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

from app.core.settings import settings

try:
    from pgvector.sqlalchemy import Vector
    VECTOR_AVAILABLE = True
except ImportError:
    Vector = None
    VECTOR_AVAILABLE = False

# -- Engine ----------------------------------------------------------
DATABASE_URL = (
    f"postgresql://{settings.db_user}:{settings.db_password}"
    f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
)

engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


# -- ORM Models ------------------------------------------------------

class ChatSession(Base):
    """Represents a chat session."""
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(String(100), unique=True, index=True)
    user_id = Column(String(100))
    user_name = Column(String(100))
    title = Column(String(200), default="", comment="自定义会话标题，空则用预览")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    messages = relationship("ChatMessage", back_populates="session")


class DocumentChunk(Base):
    """知识库文档分片向量表"""
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(Integer, ForeignKey("knowledge_files.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, default=0, comment="分片序号")
    content = Column(Text, nullable=False, comment="分片文本内容")
    embedding = Column(Vector(768), nullable=True, comment="文本向量(768维, bge-base-zh-v1.5)") if VECTOR_AVAILABLE else Column(Text, nullable=True)
    metadata_json = Column(Text, comment="元数据JSON(来源/页码/工作表等)")
    created_at = Column(DateTime, default=datetime.now)


class ChatMessage(Base):
    """Represents a chat message."""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"))
    message_id = Column(String(100), unique=True, index=True)
    role = Column(String(20))  # user, assistant
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    session = relationship("ChatSession", back_populates="messages")


class EventLog(Base):
    """Represents an event log entry."""
    __tablename__ = "event_logs"

    id = Column(Integer, primary_key=True, index=True)
    topic = Column(String(100))
    operation = Column(String(50))
    chat_id = Column(String(100))
    user_id = Column(String(100))
    raw_data = Column(Text)
    processed = Column(String(10))   # success, failed
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


class User(Base):
    """Represents a user for authentication."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    email = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ModelConfig(Base):
    """Represents a model configuration."""
    __tablename__ = "model_configs"

    id = Column(Integer, primary_key=True, index=True)
    model_type = Column(String(50), nullable=False, index=True)  # llm, embedding
    name = Column(String(100), nullable=False)
    provider = Column(String(50), nullable=False)  # deepseek, openai, huggingface, custom
    api_key = Column(String(255))
    api_url = Column(String(500))
    model_name = Column(String(200))
    description = Column(Text)
    is_active = Column(Boolean, default=False)
    is_default = Column(Boolean, default=False)
    extra_config = Column(Text)  # JSON string for extra configuration
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class SystemSetting(Base):
    """Represents system-wide settings."""
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text)
    description = Column(String(255))
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class KnowledgeBase(Base):
    """知识库分类"""
    __tablename__ = "knowledge_bases"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, comment="知识库名称")
    description = Column(String(500), comment="知识库描述")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class KnowledgeFile(Base):
    """知识库文件记录"""
    __tablename__ = "knowledge_files"

    id = Column(Integer, primary_key=True, index=True)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True, index=True, comment="所属知识库ID")
    filename = Column(String(500), nullable=False, comment="原始文件名")
    stored_name = Column(String(500), nullable=False, comment="MinIO存储对象名")
    file_type = Column(String(20), nullable=False, index=True, comment="文件类型: txt/pdf/xlsx/docx/md/csv")
    file_size = Column(Integer, default=0, comment="文件大小(字节)")
    file_path = Column(String(1000), nullable=False, comment="MinIO对象名")
    status = Column(String(20), default="uploaded", index=True, comment="状态: uploaded/indexed/error")
    error_msg = Column(Text, comment="错误信息")
    chunk_count = Column(Integer, default=0, comment="分片数量")
    chunk_strategy = Column(String(20), comment="切分策略: recursive/sentence/section/qa/semantic/token/paragraph/fixed/excel")
    chunk_size = Column(Integer, comment="每片字符数")
    chunk_overlap = Column(Integer, comment="重叠字符数")
    uploader = Column(String(100), comment="上传者")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class PromptTemplate(Base):
    """Prompt 模板管理"""
    __tablename__ = "prompt_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, comment="模板名称(唯一标识)")
    description = Column(String(500), comment="模板描述")
    category = Column(String(50), default="general", index=True, comment="分类: general/rag/code/custom")
    system_prompt = Column(Text, nullable=False, comment="系统提示词")
    user_prompt = Column(Text, comment="用户提示词模板, 支持 {question} {context} {chat_history} 占位符")
    variables = Column(Text, comment="JSON: 变量定义及默认值")
    is_active = Column(Boolean, default=True, comment="是否启用")
    sort_order = Column(Integer, default=0, comment="排序")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class AITrace(Base):
    """AI 调用链路追踪 - 可观测性数据"""
    __tablename__ = "ai_traces"

    id = Column(Integer, primary_key=True, index=True)
    trace_id = Column(String(50), nullable=False, index=True, comment="追踪ID(UUID)")
    session_id = Column(String(100), index=True, comment="会话ID")
    node_name = Column(String(50), nullable=False, index=True, comment="节点: classify/retrieve/generate/fallback")
    trace_type = Column(String(20), default="agent_node", comment="类型: agent_node/llm_call/tool_call")
    model_name = Column(String(100), comment="使用的模型名称")
    input_summary = Column(Text, comment="输入摘要(前200字符)")
    output_summary = Column(Text, comment="输出摘要(前500字符)")
    status = Column(String(20), default="success", index=True, comment="状态: success/error")
    latency_ms = Column(Integer, default=0, comment="耗时(毫秒)")
    token_count = Column(Integer, default=0, comment="Token消耗估算")
    error_msg = Column(Text, comment="错误信息")
    metadata_json = Column(Text, comment="元数据JSON")
    created_at = Column(DateTime, default=datetime.now)


class TraceRating(Base):
    """评分系统 - Trace/Observation 多维度质量评估。支持 AI 裁判 + 人工复核。"""
    __tablename__ = "trace_ratings"

    id = Column(Integer, primary_key=True, index=True)
    target_type = Column(String(20), nullable=False, index=True, comment="评分目标: trace(对话轮次) / observation(观测步骤)")
    target_id = Column(String(100), nullable=False, index=True, comment="目标ID: trace_id 或 observation序号")
    session_id = Column(String(100), index=True, comment="关联会话ID")
    node_name = Column(String(50), index=True, comment="节点名称(observation级别)")
    rater_type = Column(String(20), default="human", index=True, comment="评价来源: ai(LLM裁判) / human(人工)")
    scorer = Column(String(100), comment="评分人: ai_judge_{model} 或 用户名")
    judge_model = Column(String(100), comment="裁判模型名称(ai评价时)")
    dimension_scores = Column(Text, nullable=False, comment="多维度评分JSON: {维度:分数}")
    dimension_reasons = Column(Text, comment="各维度评价理由JSON: {维度:理由}")
    overall_score = Column(Float, default=0.0, comment="综合评分(加权平均)")
    comment = Column(Text, comment="评语/反馈")
    created_at = Column(DateTime, default=datetime.now)


# -- Helpers ---------------------------------------------------------

def init_db():
    """Initialize the database -- create all tables."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency -- yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
