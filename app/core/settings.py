"""Settings and configuration for the application."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    server_port: int = 18081
    
    # WOA Configuration
    woa_config_app_id: str = ""
    woa_config_app_key: str = ""
    woa_host: str = "https://im2.yungongplat.com:9000"
    
    # DeepSeek Configuration
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
