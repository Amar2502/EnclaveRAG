"""Application settings loaded from .env."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """Runtime configuration for EnclaveRAG."""

    app_name: str = "EnclaveRAG"
    database_url: str = "postgresql://enclave_app:enclave_dev_password@localhost:5433/enclave_rag"
    admin_database_url: str = "postgresql://postgres:postgres_dev_only@localhost:5433/enclave_rag"

    jwt_secret_key: str = "dev-only-change-this-secret-key-min-32-bytes"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    enable_demo_mode: bool = True
    app_base_url: str = "http://localhost:3000"

    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_api_key: str = ""
    gemini_embedding_model: str = "gemini-embedding-001"
    embedding_dimension: int = 768

    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    storage_provider: str = "local"
    local_storage_dir: str = "./storage"
    s3_endpoint_url: str = "https://t3.storage.dev"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_bucket_name: str = "enclave-rag-uploads"
    s3_region: str = "auto"

    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = "enclave-rag-uploads"

    org_rate_limit_per_min: int = 60
    stripe_webhook_secret: str = ""

    model_config = SettingsConfigDict(env_file=(".env", str(_ROOT_ENV)), extra="ignore")


settings = Settings()
