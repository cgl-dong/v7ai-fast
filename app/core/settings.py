"""Settings and configuration for the application."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    server_port: int = 18081
    server_ip: str = "0.0.0.0"
    remote_ip: str = ""

    # WOA Configuration
    woa_config_app_id: str = ""
    woa_config_app_key: str = ""
    woa_host: str = ""

    # DeepSeek Configuration
    deepseek_api_key: str = ""
    deepseek_model: str = ""

    # JWT Configuration
    secret_key: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Database Configuration (PostgreSQL)
    db_host: str = ""
    db_port: int = 5432
    db_user: str = ""
    db_password: str = ""
    db_name: str = ""

    @property
    def database_url(self) -> str:
        """PostgreSQL connection string."""
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
