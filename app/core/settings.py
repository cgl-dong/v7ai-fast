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

    # MinIO Configuration
    minio_endpoint: str = "10.12.33.92:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "knowledge-base"
    minio_secure: bool = False

    # AI Judge Configuration (LLM-as-Judge 自动评价)
    judge_enabled: bool = False       # 是否在每次回答后自动触发 AI 评价
    judge_model: str = ""             # 裁判模型，为空则复用 deepseek_model
    judge_temperature: float = 0.1    # 低温度保证评分一致性

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

    # RAG retrieval configuration
    rag_search_mode: str = "hybrid"  # dense | hybrid
    rag_dense_candidates: int = 20
    rag_bm25_candidates: int = 20
    rag_rrf_k: int = 60

    # RAG query rewrite
    rag_query_rewrite_enabled: bool = True  # Enable Multi-Query + HyDE rewrite before retrieval

    # RAG rerank configuration
    rag_rerank_enabled: bool = True         # Enable Cross-Encoder reranking
    rag_rerank_model: str = "BAAI/bge-reranker-base"  # Cross-Encoder model
    rag_rerank_top_n: int = 5               # Final results after rerank

    # Web Search Configuration
    web_search_enabled: bool = True         # 启用Web搜索增强（bing_html无需Key，默认开启）
    web_search_provider: str = "bing_html" # 搜索后端: bing_html | bing | duckduckgo | custom
    web_search_api_key: str = ""            # Bing Search API Key (bing模式必填)
    web_search_api_url: str = ""            # Bing API URL或自定义搜索端点
    web_search_max_results: int = 5         # 每次搜索返回结果数
    web_search_fallback_threshold: float = 0.6  # 知识库相似度低于此值时触发联网补充

    @property
    def database_url(self) -> str:
        """PostgreSQL connection string."""
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
