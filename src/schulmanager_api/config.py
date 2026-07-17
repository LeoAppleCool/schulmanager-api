from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SM_", extra="ignore")

    app_name: str = "Schulmanager API"
    environment: str = "development"
    backend: str = "mock"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 14
    admin_emails_csv: str = ""
    viewer_emails_csv: str = ""

    # Timezone the school's wall-clock times (lesson start/end, events) are in.
    school_timezone: str = "Europe/Berlin"

    cache_enabled: bool = True
    cache_backend: str = "sqlite"  # memory | sqlite
    cache_db_path: str = "data/cache.sqlite3"
    cache_ttl_schedule_seconds: int = 120
    cache_ttl_homework_seconds: int = 90
    cache_ttl_exams_seconds: int = 180
    cache_ttl_grades_seconds: int = 180
    cache_ttl_events_seconds: int = 180
    cache_ttl_absences_seconds: int = 180
    cache_ttl_messages_seconds: int = 60

    rate_limit_enabled: bool = True
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60

    webhooks_enabled: bool = True
    webhook_timeout_seconds: int = 8
    webhook_hmac_secret: str = "change-webhook-secret"

    selenium_headless: bool = True
    selenium_driver_path: str | None = None
    selenium_login_timeout_seconds: int = 25
    selenium_require_browser: bool = False
    # Schulmanager ignores the bundleVersion *content* (any placeholder works); this is only
    # a fallback when auto-discovery fails. Must be a non-empty hex-ish string.
    selenium_bundle_version: str = "42424242424242424242"
    selenium_bundle_cache_ttl_seconds: int = 3600
    selenium_term_id: int = 28592

    discord_bot_token: str | None = None
    discord_api_base_url: str = "http://127.0.0.1:8000"
    discord_sync_interval_seconds: int = 120
    discord_db_path: str = "data/discord_bot.sqlite3"
    discord_guild_id: int | None = None
    discord_timezone: str = "Europe/Berlin"
    discord_category_prefix: str = "schulmanager"
    discord_digest_time: str = "07:00"  # HH:MM in discord_timezone
    discord_digest_enabled: bool = True

    log_format: str = "text"   # text | json
    log_level: str = "INFO"
    metrics_require_auth: bool = False

    @property
    def admin_emails(self) -> set[str]:
        return self._csv_to_set(self.admin_emails_csv)

    @property
    def viewer_emails(self) -> set[str]:
        return self._csv_to_set(self.viewer_emails_csv)

    @staticmethod
    def _csv_to_set(raw: str) -> set[str]:
        return {part.strip().lower() for part in raw.split(",") if part.strip()}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
