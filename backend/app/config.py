
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


def absolutize_sqlite(url: str) -> str:
    """Anchor relative SQLite paths to the project root."""

    prefix = "sqlite:///"

    if not url.startswith(prefix) or url.startswith("sqlite:////"):
        return url

    path = url[len(prefix):]

    if path in ("", ":memory:") or Path(path).is_absolute():
        return url

    return prefix + (ROOT / path).resolve().as_posix()


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./rescuemesh.db"
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
    CORS_ORIGINS: str = "http://localhost:3000"
    USGS_BASE_URL: str = "https://earthquake.usgs.gov/fdsnws/event/1/query"
    USGS_MIN_MAGNITUDE: float = 2.5
    USGS_LOOKBACK_HOURS: int = 24
    HTTP_TIMEOUT_SECONDS: int = 20
    FIRMS_MAP_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        extra="ignore",
        validate_default=True
    )

    @field_validator("DATABASE_URL")
    @classmethod
    def _anchor_sqlite(cls, v: str) -> str:
        return absolutize_sqlite(v)

    @field_validator("SECRET_KEY")
    @classmethod
    def _strong_secret(cls, v: str) -> str:
        if len(v) < 32 or v.lower().startswith(
            ("dev", "change", "secret")
        ):
            raise ValueError(
                "SECRET_KEY must be at least 32 characters "
                "and not a placeholder. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )

        return v


settings = Settings()
