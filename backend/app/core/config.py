from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SignalPulse API"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "sqlite:///./signalpulse.db"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    wikipedia_user_agent: str = "SignalPulse/0.1.0 (https://github.com/signalpulse)"
    wikipedia_timeout_seconds: float = 5.0
    wikipedia_lang: str = "en"
    wikipedia_max_results: int = 10

    guardian_api_key: str = ""
    guardian_api_url: str = "https://content.guardianapis.com/search"
    guardian_user_agent: str = "SignalPulse/0.1.0 (https://github.com/signalpulse)"
    guardian_timeout_seconds: float = 5.0
    guardian_max_results: int = 10

    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "SignalPulse/0.1.0 (https://github.com/signalpulse)"
    reddit_token_url: str = "https://www.reddit.com/api/v1/access_token"
    reddit_api_base: str = "https://oauth.reddit.com"
    reddit_timeout_seconds: float = 5.0
    reddit_max_results: int = 10

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()