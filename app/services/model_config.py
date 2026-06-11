"""Service for managing model configurations."""
from typing import List, Optional
from sqlalchemy.orm import Session
from app.core.database import ModelConfig, SystemSetting
import json


class ModelConfigService:
    """Service for model configuration management."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_all_configs(self, model_type: str = None) -> List[ModelConfig]:
        """Get all model configurations, optionally filtered by type."""
        query = self.db.query(ModelConfig)
        if model_type:
            query = query.filter(ModelConfig.model_type == model_type)
        return query.order_by(ModelConfig.model_type, ModelConfig.name).all()
    
    def get_config_by_id(self, config_id: int) -> Optional[ModelConfig]:
        """Get a model configuration by ID."""
        return self.db.query(ModelConfig).filter(ModelConfig.id == config_id).first()
    
    def get_active_config(self, model_type: str) -> Optional[ModelConfig]:
        """Get the active configuration for a model type."""
        return self.db.query(ModelConfig).filter(
            ModelConfig.model_type == model_type,
            ModelConfig.is_active == True
        ).first()
    
    def create_config(self, data: dict) -> ModelConfig:
        """Create a new model configuration."""
        config = ModelConfig(
            model_type=data["model_type"],
            name=data["name"],
            provider=data["provider"],
            api_key=data.get("api_key"),
            api_url=data.get("api_url"),
            model_name=data.get("model_name"),
            description=data.get("description"),
            is_active=data.get("is_active", False),
            is_default=data.get("is_default", False),
            extra_config=json.dumps(data.get("extra_config", {})) if data.get("extra_config") else None
        )
        
        if config.is_active:
            self._deactivate_other_type(config.model_type)
        
        self.db.add(config)
        self.db.commit()
        self.db.refresh(config)
        return config
    
    def update_config(self, config_id: int, data: dict) -> Optional[ModelConfig]:
        """Update an existing model configuration."""
        config = self.get_config_by_id(config_id)
        if not config:
            return None
        
        if "model_type" in data:
            config.model_type = data["model_type"]
        if "name" in data:
            config.name = data["name"]
        if "provider" in data:
            config.provider = data["provider"]
        if "api_key" in data:
            config.api_key = data["api_key"]
        if "api_url" in data:
            config.api_url = data["api_url"]
        if "model_name" in data:
            config.model_name = data["model_name"]
        if "description" in data:
            config.description = data["description"]
        if "is_active" in data:
            config.is_active = data["is_active"]
            if config.is_active:
                self._deactivate_other_type(config.model_type)
        if "is_default" in data:
            config.is_default = data["is_default"]
        if "extra_config" in data:
            config.extra_config = json.dumps(data["extra_config"])
        
        self.db.commit()
        self.db.refresh(config)
        return config
    
    def delete_config(self, config_id: int) -> bool:
        """Delete a model configuration."""
        config = self.get_config_by_id(config_id)
        if not config:
            return False
        
        self.db.delete(config)
        self.db.commit()
        return True
    
    def activate_config(self, config_id: int) -> Optional[ModelConfig]:
        """Activate a model configuration (deactivates others of same type)."""
        config = self.get_config_by_id(config_id)
        if not config:
            return None
        
        self._deactivate_other_type(config.model_type)
        config.is_active = True
        self.db.commit()
        self.db.refresh(config)
        return config
    
    def _deactivate_other_type(self, model_type: str):
        """Deactivate all configurations of the same type."""
        self.db.query(ModelConfig).filter(
            ModelConfig.model_type == model_type,
            ModelConfig.is_active == True
        ).update({"is_active": False})
        self.db.flush()
    
    def get_system_setting(self, key: str) -> Optional[str]:
        """Get a system setting value."""
        setting = self.db.query(SystemSetting).filter(SystemSetting.key == key).first()
        return setting.value if setting else None
    
    def set_system_setting(self, key: str, value: str, description: str = "") -> SystemSetting:
        """Set a system setting."""
        setting = self.db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if setting:
            setting.value = value
            if description:
                setting.description = description
        else:
            setting = SystemSetting(key=key, value=value, description=description)
            self.db.add(setting)
        
        self.db.commit()
        self.db.refresh(setting)
        return setting
