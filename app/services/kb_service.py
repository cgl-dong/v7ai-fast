"""Knowledge Base CRUD service."""
import logging
from typing import List, Optional
from sqlalchemy.orm import Session
from app.core.database import KnowledgeBase

logger = logging.getLogger("v7ai-fast.kb")


class KnowledgeBaseService:
    def __init__(self, db: Session):
        self.db = db

    def get_all(self) -> List[KnowledgeBase]:
        return self.db.query(KnowledgeBase).order_by(KnowledgeBase.name).all()

    def get_active(self) -> List[KnowledgeBase]:
        return self.db.query(KnowledgeBase).filter(KnowledgeBase.is_active == True).order_by(KnowledgeBase.name).all()

    def get_by_id(self, kb_id: int) -> Optional[KnowledgeBase]:
        return self.db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()

    def create(self, name: str, description: str = "") -> KnowledgeBase:
        kb = KnowledgeBase(name=name, description=description)
        self.db.add(kb)
        self.db.commit()
        self.db.refresh(kb)
        logger.info(f"KB created: id={kb.id}, name={name}")
        return kb

    def update(self, kb_id: int, data: dict) -> Optional[KnowledgeBase]:
        kb = self.get_by_id(kb_id)
        if not kb:
            return None
        for k, v in data.items():
            if hasattr(kb, k):
                setattr(kb, k, v)
        self.db.commit()
        self.db.refresh(kb)
        logger.info(f"KB updated: id={kb_id}, changes={list(data.keys())}")
        return kb

    def delete(self, kb_id: int) -> bool:
        kb = self.get_by_id(kb_id)
        if not kb:
            return False
        self.db.delete(kb)
        self.db.commit()
        logger.info(f"KB deleted: id={kb_id}")
        return True
