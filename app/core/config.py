from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"


def _env(name: str, default: str = "") -> str:
    """Read the MADZI_<name> environment variable."""
    return os.getenv(f"MADZI_{name}", default)


DEFAULT_SQLITE_URL = f"sqlite:///{(DATA_DIR / 'madzihub.db').as_posix()}"
DEFAULT_SECRET_FILE = str(DATA_DIR / "madzihub.secret")


@dataclass
class Settings:
    env: str = _env("ENV", os.getenv("ENV", "development")).strip().lower()
    database_url: str = os.getenv("DATABASE_URL", DEFAULT_SQLITE_URL).strip()
    secret_key: str = _env("SECRET_KEY", os.getenv("SECRET_KEY", "")).strip()
    upload_limit_mb: int = int(os.getenv("UPLOAD_LIMIT_MB", "50"))
    allowed_origins_raw: str = _env("ALLOWED_ORIGINS", "http://localhost,http://127.0.0.1,http://localhost:8000,http://127.0.0.1:8000").strip()
    allow_local_secret_file: bool = _env("ALLOW_LOCAL_SECRET_FILE", "true").strip().lower() in {"1", "true", "yes"}
    secret_file_path: Path = Path(_env("SECRET_FILE", DEFAULT_SECRET_FILE))
    # Passwordless local preview login. Off unless explicitly enabled AND env=development.
    dev_preview_enabled: bool = _env("DEV_PREVIEW", "false").strip().lower() in {"1", "true", "yes"}
    tenant: str = _env("TENANT", "demo").strip() or "demo"

    @property
    def is_production(self) -> bool:
        return self.env in {"prod", "production"}

    @property
    def dev_preview_allowed(self) -> bool:
        return self.dev_preview_enabled and self.env == "development"

    @property
    def allowed_origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins_raw.split(",") if item.strip()]

    def validate_startup(self) -> None:
        insecure_defaults = {"", "supersecret", "changeme", "dev-secret", "default-secret"}

        if self.is_production:
            if self.secret_key in insecure_defaults and not (self.allow_local_secret_file and self.secret_file_path.exists()):
                raise RuntimeError(
                    "Production startup blocked: set MADZI_SECRET_KEY or provide a secure secret file via MADZI_SECRET_FILE."
                )

            if not self.allowed_origins:
                raise RuntimeError(
                    "Production startup blocked: MADZI_ALLOWED_ORIGINS must contain at least one trusted origin."
                )

            if "*" in self.allowed_origins:
                raise RuntimeError(
                    "Production startup blocked: wildcard CORS origin '*' is not allowed."
                )


settings = Settings()
