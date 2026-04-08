"""全域設定，從 .env 讀取 API 金鑰與系統參數"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    llm_writing_model: str = Field(default="claude-sonnet-4-5", alias="LLM_WRITING_MODEL")
    llm_lite_model: str = Field(default="gpt-4o-mini", alias="LLM_LITE_MODEL")

    # NCBI / PubMed
    ncbi_api_key: str = Field(default="", alias="NCBI_API_KEY")
    ncbi_email: str = Field(default="", alias="NCBI_EMAIL")

    # SERP
    serper_api_key: str = Field(default="", alias="SERPER_API_KEY")

    # Google
    google_service_account_file: str = Field(
        default="credentials/google-service-account.json",
        alias="GOOGLE_SERVICE_ACCOUNT_FILE",
    )
    google_sheets_schedule_id: str = Field(
        default="", alias="GOOGLE_SHEETS_SCHEDULE_ID"
    )

    # WordPress
    wordpress_site_url: str = Field(default="", alias="WORDPRESS_SITE_URL")
    wordpress_username: str = Field(default="", alias="WORDPRESS_USERNAME")
    wordpress_app_password: str = Field(default="", alias="WORDPRESS_APP_PASSWORD")

    # 資料庫
    database_url: str = Field(
        default="sqlite:///./data/contentflow.db", alias="DATABASE_URL"
    )

    # 系統
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    output_dir: str = Field(default="./outputs", alias="OUTPUT_DIR")
    max_articles_per_run: int = Field(default=5, alias="MAX_ARTICLES_PER_RUN")


settings = Settings()
