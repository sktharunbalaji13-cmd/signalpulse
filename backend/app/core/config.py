from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SignalPulse API"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"

    # M3.5 pipeline-level per-source timeout (design §15.3.1): bounds a single
    # source unit (fetch + persist) with asyncio.wait_for so a hung adapter can
    # never block the whole search. Chosen so worst-case completed stays within
    # the locked <= 5 s target once the measured post-pass budget is added.
    source_timeout_seconds: float = 4.5

    # M11.1 semantic relevance stage (ADR 0012): ONNX-int8 MiniLM local
    # inference as an optional, failure-isolated ranking enhancement. When the
    # stage fails/times out/is disabled, ranking falls back to pure C4.
    # DEFAULT OFF: production rollout is a deliberate, separate step - set
    # SEMANTIC_ENABLED=true explicitly after deployment verification.
    semantic_enabled: bool = False
    semantic_timeout_seconds: float = 10.0
    semantic_model_dir: str = "models/minilm-int8"

    # M4 production CORS (design M4 §7): exact allow-list of frontend origins;
    # credentials are off for the public API.
    cors_allow_credentials: bool = False

    # M4 in-process rate limiting + in-flight protection (design M4 §12).
    # Per-client-IP sliding window on POST /searches and a global cap on the
    # number of concurrently running searches -> HTTP 429 when exceeded.
    rate_limit_requests: int = 30
    rate_limit_window_seconds: float = 60.0
    max_in_flight_searches: int = 8

    # M14.1 admin API key (fail-closed): protects /api/v1/admin/stats.
    # Empty string = deny all requests (key required but impossible to match).
    admin_api_key: str = ""

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

    gdelt_api_url: str = "https://api.gdeltproject.org/api/v2/doc/doc"
    gdelt_timeout_seconds: float = 30.0
    gdelt_max_results: int = 10

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()