from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str

    openrouter_api_key: str
    rawg_api_key: str

    database_url: str | None = None
    redis_url: str | None = None

    privat_card: str

    admin_ids: str

    bot_username: str = "SearchForGame_bot"
    bot_name: str = "ИгроПамять"

    default_language: str = "en"

    free_daily_search_limit: int = 2

    referral_premium_days: int = 5
    referrals_required: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore"
    )


settings = Settings()
