from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = "changeme"
    telegram_mode: str = "polling"  # "webhook" | "polling"
    telegram_webhook_url: str = ""

    # LLM
    groq_api_key: str = ""
    deepseek_api_key: str = ""

    # RAG / Study Pipeline
    rag_corpus_dir: str = ""        # path to PDF corpus (e.g. /data/corpus)
    rag_persist_dir: str = ""       # path for ChromaDB embeddings (e.g. /data/rag)

    # WhatsApp / open-wa sidecar
    openwa_base_url: str = "http://openwa:3000"
    openwa_api_key: str = ""        # optional — set WA_API_KEY in open-wa config
    wa_webhook_secret: str = "changeme-wa"  # shared secret for webhook validation

    # OrioSearch
    orio_base_url: str = "http://oriosearch:8080"

    # APIs externas gratuitas
    openalex_email: str = "bot@example.com"
    unpaywall_email: str = "bot@example.com"

    # Database
    sqlite_path: str = "/data/resusbot.db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 604800  # 7 dias

    # Dashboard
    dashboard_user: str = "admin"
    dashboard_password_hash: str = ""
    dashboard_domain: str = ""

    # Rate limiting
    rate_limit_per_ip: int = 60
    rate_limit_per_user: int = 20

    # Billing / Mercado Pago
    mp_access_token: str = ""
    mp_webhook_secret: str = "changeme"
    mp_notification_url: str = ""  # ex: https://seudominio.com/payments/webhook/mercadopago
    mp_return_url: str = ""  # ex: https://t.me/SeuBotUsername
    free_monthly_credits: int = 10
    credit_validity_days: int = 60

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    port: int = 8000

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.sqlite_path}"

    @property
    def sync_database_url(self) -> str:
        return f"sqlite:///{self.sqlite_path}"


settings = Settings()
