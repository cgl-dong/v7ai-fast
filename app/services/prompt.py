"""Prompt template management service."""
import json
import logging
from typing import Optional, List
from sqlalchemy.orm import Session
from app.core.database import PromptTemplate

logger = logging.getLogger("v7ai-fast.prompt")


class PromptService:
    """Manage prompt templates in database."""

    def __init__(self, db: Session):
        self.db = db

    def get_all(self, category: str = None) -> List[PromptTemplate]:
        q = self.db.query(PromptTemplate)
        if category:
            q = q.filter(PromptTemplate.category == category)
        return q.order_by(PromptTemplate.sort_order, PromptTemplate.name).all()

    def get_by_id(self, template_id: int) -> Optional[PromptTemplate]:
        return self.db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()

    def get_by_name(self, name: str) -> Optional[PromptTemplate]:
        return self.db.query(PromptTemplate).filter(PromptTemplate.name == name).first()

    def create(self, data: dict) -> PromptTemplate:
        if "variables" in data and isinstance(data["variables"], dict):
            data["variables"] = json.dumps(data["variables"], ensure_ascii=False)
        template = PromptTemplate(**data)
        self.db.add(template)
        self.db.commit()
        self.db.refresh(template)
        return template

    def update(self, template_id: int, data: dict) -> Optional[PromptTemplate]:
        template = self.get_by_id(template_id)
        if not template:
            return None
        if "variables" in data and isinstance(data["variables"], dict):
            data["variables"] = json.dumps(data["variables"], ensure_ascii=False)
        for key, value in data.items():
            setattr(template, key, value)
        self.db.commit()
        self.db.refresh(template)
        return template

    def delete(self, template_id: int) -> bool:
        template = self.get_by_id(template_id)
        if not template:
            return False
        self.db.delete(template)
        self.db.commit()
        return True

    def get_active_prompt(self, category: str = "rag") -> Optional[dict]:
        """Get the active prompt template for a category, with variables resolved."""
        template = (
            self.db.query(PromptTemplate)
            .filter(PromptTemplate.category == category, PromptTemplate.is_active == True)
            .order_by(PromptTemplate.sort_order)
            .first()
        )
        if not template:
            return None
        variables = {}
        if template.variables:
            try:
                variables = json.loads(template.variables)
            except (json.JSONDecodeError, TypeError):
                pass
        return {
            "id": template.id,
            "name": template.name,
            "system_prompt": template.system_prompt,
            "user_prompt": template.user_prompt or "{question}",
            "variables": variables,
        }
