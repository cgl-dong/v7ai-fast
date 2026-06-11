"""Model configuration management endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.core.database import get_db
from app.services.model_config import ModelConfigService
import json

router = APIRouter()


class ModelConfigCreate(BaseModel):
    """Schema for creating a new model configuration."""
    model_type: str
    name: str
    provider: str
    api_key: str = None
    api_url: str = None
    model_name: str = None
    description: str = None
    is_active: bool = False
    is_default: bool = False
    extra_config: dict = None


class ModelConfigUpdate(BaseModel):
    """Schema for updating a model configuration."""
    name: str | None = None
    provider: str | None = None
    api_key: str | None = None
    api_url: str | None = None
    model_name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    is_default: bool | None = None
    extra_config: dict | None = None


class ModelConfigResponse(BaseModel):
    """Schema for model configuration response."""
    id: int
    model_type: str
    name: str
    provider: str
    api_key: str | None = None
    api_url: str | None = None
    model_name: str | None = None
    description: str | None = None
    is_active: bool
    is_default: bool
    extra_config: dict | None = None
    created_at: str
    updated_at: str

    @classmethod
    def from_orm(cls, config):
        """Create response from ORM model."""
        data = {
            "id": config.id,
            "model_type": config.model_type,
            "name": config.name,
            "provider": config.provider,
            "api_key": config.api_key,
            "api_url": config.api_url,
            "model_name": config.model_name,
            "description": config.description,
            "is_active": config.is_active,
            "is_default": config.is_default,
            "created_at": config.created_at.isoformat(),
            "updated_at": config.updated_at.isoformat()
        }
        if config.extra_config:
            try:
                data["extra_config"] = json.loads(config.extra_config)
            except:
                data["extra_config"] = {}
        return cls(**data)


@router.get("/models", response_model=list[ModelConfigResponse])
async def get_all_models(
    model_type: str = None,
    db: Session = Depends(get_db)
):
    """Get all model configurations, optionally filtered by type."""
    service = ModelConfigService(db)
    configs = service.get_all_configs(model_type)
    return [ModelConfigResponse.from_orm(c) for c in configs]


@router.get("/models/{config_id}", response_model=ModelConfigResponse)
async def get_model_by_id(
    config_id: int,
    db: Session = Depends(get_db)
):
    """Get a model configuration by ID."""
    service = ModelConfigService(db)
    config = service.get_config_by_id(config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Model configuration not found")
    return ModelConfigResponse.from_orm(config)


@router.get("/models/active/{model_type}", response_model=ModelConfigResponse)
async def get_active_model(
    model_type: str,
    db: Session = Depends(get_db)
):
    """Get the active configuration for a model type."""
    service = ModelConfigService(db)
    config = service.get_active_config(model_type)
    if not config:
        raise HTTPException(status_code=404, detail="No active configuration found for this type")
    return ModelConfigResponse.from_orm(config)


@router.post("/models", response_model=ModelConfigResponse)
async def create_model(
    data: ModelConfigCreate,
    db: Session = Depends(get_db)
):
    """Create a new model configuration."""
    service = ModelConfigService(db)
    
    if data.model_type not in ["llm", "embedding"]:
        raise HTTPException(status_code=400, detail="Invalid model type. Must be 'llm' or 'embedding'")
    
    config = service.create_config(data.dict())
    return ModelConfigResponse.from_orm(config)


@router.put("/models/{config_id}", response_model=ModelConfigResponse)
async def update_model(
    config_id: int,
    data: ModelConfigUpdate,
    db: Session = Depends(get_db)
):
    """Update an existing model configuration."""
    service = ModelConfigService(db)
    config = service.update_config(config_id, data.model_dump(exclude_none=True))
    if not config:
        raise HTTPException(status_code=404, detail="Model configuration not found")
    return ModelConfigResponse.from_orm(config)


@router.delete("/models/{config_id}")
async def delete_model(
    config_id: int,
    db: Session = Depends(get_db)
):
    """Delete a model configuration."""
    service = ModelConfigService(db)
    success = service.delete_config(config_id)
    if not success:
        raise HTTPException(status_code=404, detail="Model configuration not found")
    return {"message": "Model configuration deleted successfully"}


@router.post("/models/{config_id}/activate", response_model=ModelConfigResponse)
async def activate_model(
    config_id: int,
    db: Session = Depends(get_db)
):
    """Activate a model configuration."""
    service = ModelConfigService(db)
    config = service.activate_config(config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Model configuration not found")
    return ModelConfigResponse.from_orm(config)


@router.get("/settings/{key}")
async def get_system_setting(
    key: str,
    db: Session = Depends(get_db)
):
    """Get a system setting."""
    service = ModelConfigService(db)
    value = service.get_system_setting(key)
    if value is None:
        raise HTTPException(status_code=404, detail="Setting not found")
    return {"key": key, "value": value}


@router.post("/settings/{key}")
async def set_system_setting(
    key: str,
    value: str,
    description: str = "",
    db: Session = Depends(get_db)
):
    """Set a system setting."""
    service = ModelConfigService(db)
    setting = service.set_system_setting(key, value, description)
    return {"key": setting.key, "value": setting.value, "description": setting.description}
