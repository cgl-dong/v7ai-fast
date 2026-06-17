"""Service for managing chat sessions and messages."""
import logging
import uuid
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional, List

from app.core.database import ChatSession, ChatMessage, EventLog

logger = logging.getLogger("v7ai-fast.session")


class SessionService:
    """Service for managing chat sessions."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_or_create_session(self, chat_id: str, user_id: str = None) -> ChatSession:
        """Get or create a chat session."""
        session = self.db.query(ChatSession).filter(ChatSession.chat_id == chat_id).first()
        if not session:
            session = ChatSession(
                chat_id=chat_id,
                user_id=user_id,
                created_at=datetime.now()
            )
            self.db.add(session)
            self.db.commit()
            self.db.refresh(session)
        return session
    
    def add_message(self, session_id: int, message_id: str, role: str, content: str):
        """Add a message to a session."""
        if not message_id:
            message_id = uuid.uuid4().hex
        message = ChatMessage(
            session_id=session_id,
            message_id=message_id,
            role=role,
            content=content,
            created_at=datetime.now()
        )
        self.db.add(message)
        self.db.commit()
    
    def get_session_messages(self, chat_id: str, limit: int = None) -> List[ChatMessage]:
        """Get messages for a session, most recent first if limit is set."""
        session = self.db.query(ChatSession).filter(ChatSession.chat_id == chat_id).first()
        if not session:
            return []
        q = self.db.query(ChatMessage)\
            .filter(ChatMessage.session_id == session.id)\
            .order_by(ChatMessage.created_at.asc())
        if limit:
            # Get last N messages
            total = q.count()
            q = q.offset(max(0, total - limit)).limit(limit)
        return q.all()
    
    def log_event(self, topic: str, operation: str, chat_id: str, user_id: str, 
                  raw_data: str, processed: str = "success", error_message: str = None):
        """Log an event."""
        log = EventLog(
            topic=topic,
            operation=operation,
            chat_id=chat_id,
            user_id=user_id,
            raw_data=raw_data[:5000] if raw_data else None,
            processed=processed,
            error_message=error_message,
            created_at=datetime.now()
        )
        self.db.add(log)
        self.db.commit()
    
    def get_recent_events(self, limit: int = 50) -> List[EventLog]:
        """Get recent events."""
        return self.db.query(EventLog)\
            .order_by(EventLog.created_at.desc())\
            .limit(limit)\
            .all()
    
    def get_sessions(self, limit: int = 20) -> List[ChatSession]:
        """Get recent sessions."""
        return self.db.query(ChatSession)\
            .order_by(ChatSession.created_at.desc())\
            .limit(limit)\
            .all()
    
    def get_sessions_with_user(self, limit: int = 20):
        """Get recent sessions with user information."""
        return self.db.query(ChatSession)\
            .order_by(ChatSession.created_at.desc())\
            .limit(limit)\
            .all()
