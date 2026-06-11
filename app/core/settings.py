"""Settings and configuration for the application."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    server_port: int = 18081
    server_ip: str = "0.0.0.0"
    remote_ip: str = "10.12.33.92"

    # WOA Configuration
    woa_config_app_id: str = ""
    woa_config_app_key: str = ""
    woa_host: str = "https://im2.yungongplat.com:9000"

    # DeepSeek Configuration
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"

    # JWT Configuration
    secret_key: str = "your-secret-key-here-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Database Configuration (PostgreSQL)
    db_host: str = "10.12.33.92"
    db_port: int = 5432
    db_user: str = "admin"
    db_password: str = "secret123"
    db_name: str = "appdb"

    @property
    def database_url(self) -> str:
        """PostgreSQL connection string."""
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
