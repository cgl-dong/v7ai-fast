"""Initialize database with config from .env file."""
import os
import sys
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Add app to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.database import SessionLocal, ModelConfig, SystemSetting, init_db
from app.services.model_config import ModelConfigService


def init_from_env():
    """Initialize database with config from environment variables."""
    db = SessionLocal()
    service = ModelConfigService(db)
    
    # Create system settings from .env
    env_settings = [
        ("server_port", os.getenv("SERVER_PORT", "8000"), "服务端口"),
        ("woa_config_app_id", os.getenv("WOA_CONFIG_APP_ID", ""), "WOA应用ID"),
        ("woa_config_app_key", os.getenv("WOA_CONFIG_APP_KEY", ""), "WOA应用密钥"),
        ("woa_host", os.getenv("WOA_HOST", ""), "WOA服务地址"),
        ("deepseek_api_key", os.getenv("DEEPSEEK_API_KEY", ""), "DeepSeek API密钥"),
        ("deepseek_model", os.getenv("DEEPSEEK_MODEL", "deepseek-chat"), "DeepSeek模型名称"),
        ("remote_ip", os.getenv("REMOTE_IP", ""), "远程服务器IP"),
        ("db_host", os.getenv("DB_HOST", "localhost"), "数据库主机"),
        ("db_port", os.getenv("DB_PORT", "5432"), "数据库端口"),
        ("db_user", os.getenv("DB_USER", ""), "数据库用户名"),
        ("db_password", os.getenv("DB_PASSWORD", ""), "数据库密码"),
        ("db_name", os.getenv("DB_NAME", ""), "数据库名称"),
    ]
    
    for key, value, description in env_settings:
        service.set_system_setting(key, value, description)
        print(f"Set setting: {key} = {'***' if 'key' in key.lower() or 'password' in key.lower() else value}")
    
    # Create default DeepSeek LLM config if not exists
    existing_llm = service.get_active_config("llm")
    if not existing_llm:
        deepseek_config = {
            "model_type": "llm",
            "name": "DeepSeek",
            "provider": "deepseek",
            "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
            "api_url": "https://api.deepseek.com/v1",
            "model_name": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            "description": "DeepSeek LLM模型配置",
            "is_active": True,
            "is_default": True
        }
        service.create_config(deepseek_config)
        print("Created default DeepSeek LLM config")
    
    db.close()
    print("Configuration initialization completed!")


if __name__ == "__main__":
    print("Initializing database configuration from .env...")
    print("Creating database tables...")
    init_db()
    print("Tables created successfully")
    init_from_env()