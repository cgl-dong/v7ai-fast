"""Prompt template management API."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.core.database import get_db
from app.services.prompt import PromptService
import json

router = APIRouter()


class PromptCreate(BaseModel):
    name: str
    description: str = ""
    category: str = "general"
    system_prompt: str
    user_prompt: str = ""
    variables: dict = None
    is_active: bool = True
    sort_order: int = 0


class PromptUpdate(BaseModel):
    name: str = None
    description: str = None
    category: str = None
    system_prompt: str = None
    user_prompt: str = None
    variables: dict = None
    is_active: bool = None
    sort_order: int = None


def _to_dict(t) -> dict:
    vars_dict = {}
    if t.variables:
        try:
            vars_dict = json.loads(t.variables)
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "id": t.id,
        "name": t.name,
        "description": t.description,
        "category": t.category,
        "system_prompt": t.system_prompt,
        "user_prompt": t.user_prompt,
        "variables": vars_dict,
        "is_active": t.is_active,
        "sort_order": t.sort_order,
        "created_at": t.created_at.isoformat() if t.created_at else "",
        "updated_at": t.updated_at.isoformat() if t.updated_at else "",
    }


@router.get("/templates")
async def list_templates(category: str = None, db: Session = Depends(get_db)):
    svc = PromptService(db)
    templates = svc.get_all(category=category)
    return {"templates": [_to_dict(t) for t in templates], "count": len(templates)}


@router.get("/templates/{template_id}")
async def get_template(template_id: int, db: Session = Depends(get_db)):
    svc = PromptService(db)
    t = svc.get_by_id(template_id)
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    return _to_dict(t)


@router.post("/templates")
async def create_template(data: PromptCreate, db: Session = Depends(get_db)):
    svc = PromptService(db)
    if svc.get_by_name(data.name):
        raise HTTPException(status_code=400, detail="模板名称已存在")
    try:
        t = svc.create(data.model_dump(exclude_none=True))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_dict(t)


@router.put("/templates/{template_id}")
async def update_template(template_id: int, data: PromptUpdate, db: Session = Depends(get_db)):
    svc = PromptService(db)
    t = svc.update(template_id, data.model_dump(exclude_none=True))
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    return _to_dict(t)


@router.delete("/templates/{template_id}")
async def delete_template(template_id: int, db: Session = Depends(get_db)):
    svc = PromptService(db)
    if not svc.delete(template_id):
        raise HTTPException(status_code=404, detail="模板不存在")
    return {"message": "删除成功"}


@router.post("/templates/{template_id}/activate")
async def activate_template(template_id: int, db: Session = Depends(get_db)):
    """Activate a prompt template (deactivates others in same category)."""
    svc = PromptService(db)
    t = svc.get_by_id(template_id)
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    # Deactivate all in same category
    all_in_cat = svc.get_all(category=t.category)
    for other in all_in_cat:
        other.is_active = False
    t.is_active = True
    db.commit()
    return _to_dict(t)
