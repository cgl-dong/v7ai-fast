"""Knowledge Base CRUD service."""
import logging
from typing import List, Optional
from sqlalchemy.orm import Session
from app.core.database import KnowledgeBase

logger = logging.getLogger("v7ai-fast.kb")


class KnowledgeBaseService:
    def __init__(self, db: Session):
        self.db = db

    def get_all(self, include_inactive: bool = False) -> List[KnowledgeBase]:
        q = self.db.query(KnowledgeBase)
        if not include_inactive:
            q = q.filter(KnowledgeBase.is_active == True)
        return q.order_by(KnowledgeBase.name).all()

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

    def deactivate(self, kb_id: int) -> bool:
        """软删除：停用知识库（不物理删除，文档绑定保留）"""
        kb = self.get_by_id(kb_id)
        if not kb:
            return False
        kb.is_active = False
        self.db.commit()
        logger.info(f"KB deactivated: id={kb_id}, name={kb.name}")
        return True

    def activate(self, kb_id: int) -> bool:
        """重新启用已停用的知识库"""
        kb = self.get_by_id(kb_id)
        if not kb:
            return False
        kb.is_active = True
        self.db.commit()
        logger.info(f"KB activated: id={kb_id}, name={kb.name}")
        return True

    def hard_delete(self, kb_id: int) -> bool:
        """物理删除知识库（会级联清除文档的 kb_id）"""
        kb = self.get_by_id(kb_id)
        if not kb:
            return False
        # Clear kb_id on associated files first
        from app.core.database import KnowledgeFile
        self.db.query(KnowledgeFile).filter(KnowledgeFile.kb_id == kb_id).update({"kb_id": None})
        self.db.delete(kb)
        self.db.commit()
        logger.info(f"KB hard deleted: id={kb_id}, name={kb.name}")
        return True

    def get_with_file_counts(self) -> List[dict]:
        """返回知识库列表，附带文档数量"""
        from app.core.database import KnowledgeFile
        kbs = self.get_all(include_inactive=True)
        result = []
        for kb in kbs:
            file_count = self.db.query(KnowledgeFile).filter(KnowledgeFile.kb_id == kb.id).count()
            result.append({
                "id": kb.id, "name": kb.name, "description": kb.description,
                "is_active": kb.is_active, "file_count": file_count,
                "created_at": kb.created_at.isoformat() if kb.created_at else "",
            })
        return result
