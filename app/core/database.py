"""Database models for session and message persistence."""
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
from pathlib import Path

DB_DIR = Path("data")
DB_DIR.mkdir(exist_ok=True)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_DIR / 'v7ai.db'}"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


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
    processed = Column(String(10))  # success, failed
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


def init_db():
    """Initialize the database tables."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Get a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
