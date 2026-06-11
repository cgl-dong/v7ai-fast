"""Database engine, session factory, and ORM models.
Uses PostgreSQL — configure via DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME in .env.
"""
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

from app.core.settings import settings

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
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    messages = relationship("ChatMessage", back_populates="session")


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
