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
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")

    # Cloudflare R2
    r2_access_key_id: str = Field(default="", alias="R2_ACCESS_KEY_ID")
    r2_secret_access_key: str = Field(default="", alias="R2_SECRET_ACCESS_KEY")
    r2_endpoint_url: str = Field(default="", alias="R2_ENDPOINT_URL")
    r2_bucket_name: str = Field(default="contentflow-images", alias="R2_BUCKET_NAME")
    r2_public_url: str = Field(default="", alias="R2_PUBLIC_URL")
    llm_writing_model: str = Field(default="gemini-3-flash-preview", alias="LLM_WRITING_MODEL")
    llm_lite_model: str = Field(default="gemini-3-flash-preview", alias="LLM_LITE_MODEL")
    llm_seo_qa_max_completion_tokens: int = Field(
        default=4096,
        alias="LLM_SEO_QA_MAX_COMPLETION_TOKENS",
    )

    # NCBI / PubMed
    ncbi_api_key: str = Field(default="", alias="NCBI_API_KEY")
    ncbi_email: str = Field(default="", alias="NCBI_EMAIL")

    # SERP
    serper_api_key: str = Field(default="", alias="SERPER_API_KEY")
    serpapi_key: str = Field(default="", alias="SERPAPI_KEY")

    # DataForSEO
    dataforseo_login: str = Field(default="", alias="DATAFORSEO_LOGIN")
    dataforseo_password: str = Field(default="", alias="DATAFORSEO_PASSWORD")

    # Google
    google_api_key: str = Field(
        default="",
        alias="GOOGLE_API_KEY",
        description="Google PageSpeed Insights API key（P3 CWV 監控，可選）",
    )
    google_service_account_file: str = Field(
        default="credentials/google-service-account.json",
        alias="GOOGLE_SERVICE_ACCOUNT_FILE",
    )
    # alias for code that references the old name
    @property
    def google_service_account_json(self) -> str:
        return self.google_service_account_file

    google_sheets_schedule_id: str = Field(
        default="", alias="GOOGLE_SHEETS_SCHEDULE_ID"
    )
    ga4_property_id: str = Field(
        default="",
        alias="GA4_PROPERTY_ID",
        description="GA4 Property ID (numeric, e.g. 388856613)",
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
    strategic_daily_generate_limit: int = Field(
        default=5,
        alias="STRATEGIC_DAILY_GENERATE_LIMIT",
    )

    # API 認證
    api_secret_key: str = Field(default="", alias="API_SECRET_KEY")
    admin_reviewer_secret: str = Field(default="", alias="ADMIN_REVIEWER_SECRET")
    admin_editor_secret: str = Field(default="", alias="ADMIN_EDITOR_SECRET")
    connector_secret_key: str = Field(
        default="",
        alias="CONNECTOR_SECRET_KEY",
        description="Connector secret encryption key；留空則 fallback 到 API_SECRET_KEY",
    )

    # AgentOps
    agentops_api_key: str = Field(default="", alias="AGENTOPS_API_KEY")

    # ForgeBase
    forgebase_api_base_url: str = Field(default="", alias="FORGEBASE_API_BASE_URL")
    forgebase_api_token: str = Field(default="", alias="FORGEBASE_API_TOKEN")

    # 排程
    scheduler_enabled: bool = Field(default=False, alias="SCHEDULER_ENABLED")
    scheduler_required: bool = Field(default=True, alias="SCHEDULER_REQUIRED")
    scheduler_timezone: str = Field(default="Asia/Taipei", alias="SCHEDULER_TIMEZONE")
    scheduler_heartbeat_path: str = Field(
        default="./data/scheduler_heartbeat.json",
        alias="SCHEDULER_HEARTBEAT_PATH",
    )
    scheduler_heartbeat_max_age_seconds: int = Field(
        default=180,
        alias="SCHEDULER_HEARTBEAT_MAX_AGE_SECONDS",
    )

    # 通知（可選）
    slack_webhook_url: str = Field(default="", alias="SLACK_WEBHOOK_URL")

    # Build metadata（部署版本追蹤）
    contentflow_build_commit: str = Field(
        default="unknown",
        alias="CONTENTFLOW_BUILD_COMMIT",
    )
    contentflow_build_time: str = Field(
        default="unknown",
        alias="CONTENTFLOW_BUILD_TIME",
    )
    contentflow_build_source: str = Field(
        default="unknown",
        alias="CONTENTFLOW_BUILD_SOURCE",
    )

    # Reference Site（SEO 閉環驗證前端）
    site_url: str = Field(
        default="http://localhost:8000/site",
        alias="SITE_URL",
        description="Reference Site 對外根 URL（不含結尾斜線），用於 sitemap / canonical",
    )
    ga4_measurement_id: str = Field(
        default="",
        alias="GA4_MEASUREMENT_ID",
        description="Google Analytics 4 Measurement ID（e.g. G-XXXXXXXXXX）",
    )
    admin_url: str = Field(
        default="http://localhost:8000",
        alias="ADMIN_URL",
        description="Admin 介面對外根 URL（不含結尾斜線），用於通知連結",
    )
    site_name: str = Field(
        default="ContentFlow Health",
        alias="SITE_NAME",
    )
    site_description: str = Field(
        default="以科學文獻為基礎的健康知識平台，提供清楚、可追溯且持續更新的專業內容。",
        alias="SITE_DESCRIPTION",
    )
    site_contact_email: str = Field(
        default="editor@example.com",
        alias="SITE_CONTACT_EMAIL",
        description="Reference Site 對外聯絡信箱",
    )
    site_blog_path: str = Field(
        default="/blog",
        alias="SITE_BLOG_PATH",
        description="Reference Site 文章路徑前綴，預設為 /blog",
    )
    site_project_slug: str = Field(
        default="",
        alias="SITE_PROJECT_SLUG",
        description="Reference Site 綁定的 project slug；留空則沿用全域站點設定",
    )
    platform_mode: str = Field(
        default="hybrid",
        alias="PLATFORM_MODE",
        description="平台模式：hybrid / control-plane / managed-site",
    )
    managed_site_enabled: bool = Field(
        default=True,
        alias="MANAGED_SITE_ENABLED",
        description="是否啟用內建 managed site 前台；關閉後只保留 control plane/admin",
    )

    # 反向連結監控（DataForSEO）
    backlink_sync_enabled: bool = Field(
        default=False,
        alias="BACKLINK_SYNC_ENABLED",
        description="啟用每週 DataForSEO 反向連結摘要同步",
    )

    # Google 商家檔案（GBP）整合
    gbp_location_ids: str = Field(
        default="",
        alias="GBP_LOCATION_IDS",
        description="GBP location ID 清單（逗號分隔），例：123456789,987654321",
    )
    gbp_oauth_access_token: str = Field(
        default="",
        alias="GBP_OAUTH_ACCESS_TOKEN",
        description="Business Profile API OAuth access token",
    )
    gbp_sync_enabled: bool = Field(
        default=False,
        alias="GBP_SYNC_ENABLED",
        description="啟用 Google Business Profile 指標同步",
    )
    gbp_location_project_map: str = Field(
        default="",
        alias="GBP_LOCATION_PROJECT_MAP",
        description="GBP location_id 與 project_id 映射，格式如 123456789:2,987654321:5",
    )

    # Knowledge Base / Chroma
    chroma_persist_dir: str = Field(
        default="",
        alias="CHROMA_PERSIST_DIR",
    )


settings = Settings()
