from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]      # D:\rescuemesh, wherever the server is launched from


def absolutize_sqlite(url: str) -> str:
    """Make a relative sqlite file URL absolute, anchored to the project root (not the current folder)."""
    prefix = "sqlite:///"
    if not url.startswith(prefix) or url.startswith("sqlite:////"):
        return url
    path = url[len(prefix):]
    if path in ("", ":memory:") or Path(path).is_absolute():
        return url
    return prefix + (ROOT / path).resolve().as_posix()


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./rescuemesh.db"
    SECRET_KEY: str = "dev-secret"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
    USGS_BASE_URL: str = "https://earthquake.usgs.gov/fdsnws/event/1/query"
    USGS_MIN_MAGNITUDE: float = 2.5
    USGS_LOOKBACK_HOURS: int = 24
    HTTP_TIMEOUT_SECONDS: int = 20
    FIRMS_MAP_KEY: str = ""
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", validate_default=True)

    @field_validator("DATABASE_URL")
    @classmethod
    def _anchor_sqlite(cls, v: str) -> str:
        return absolutize_sqlite(v)


settings = Settings()
