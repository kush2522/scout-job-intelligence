from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite:///./jobs.db"
    cors_origins: str = "http://localhost:3000"
    admin_api_token: str = ""
    user_agent: str = "ScoutJobIntel/0.2 (contact: ops@example.com)"
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_graph_version: str = "v23.0"
    request_timeout_seconds: int = 20
    max_career_pages: int = 12
    min_source_interval_seconds: float = 2.0
    auto_create_schema: bool = True
    scheduler_interval_minutes: int = 30
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
