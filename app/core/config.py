"""Application configuration loaded from environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Application
    app_env: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Database
    database_url: str = "sqlite:///./geospatial.db"

    # Upload limits
    max_upload_bytes: int = 50 * 1024 * 1024  # 50 MB
    max_archive_expansion_bytes: int = 250 * 1024 * 1024  # 250 MB
    max_feature_count: int = 10_000

    # Pagination
    default_page_limit: int = 50
    max_page_limit: int = 500

    # File storage
    upload_dir: Path = Path("./uploads")
    temp_dir: Path = Path("./tmp")

    # Security
    api_key: str = "change-me-in-production"
    require_auth: bool = False

    # Archive safety
    max_zip_ratio: float = 100.0  # max decompressed/compressed ratio

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


settings = Settings()
