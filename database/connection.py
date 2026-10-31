"""Database configuration and secret-safe connectivity checks."""

from functools import lru_cache
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError


load_dotenv()


def _configured_url() -> str | None:
    return os.getenv("DATABASE_URL_POOLED") or os.getenv("DATABASE_URL")


def database_configuration() -> tuple[bool, str]:
    """Return presence/type only; never return the configured URL."""
    url = _configured_url()
    if not url:
        return False, "Not configured"
    try:
        parsed = make_url(url)
    except Exception:
        return True, "Invalid URL"
    if parsed.drivername.startswith("postgres"):
        return True, "PostgreSQL configured"
    if parsed.drivername.startswith("sqlite"):
        return True, "SQLite configured (local development only)"
    return True, "Unsupported database configured"


def _normalize_url(url: str) -> str:
    parsed = make_url(url)
    if parsed.drivername == "postgres":
        parsed = parsed.set(drivername="postgresql+psycopg")
    elif parsed.drivername == "postgresql":
        parsed = parsed.set(drivername="postgresql+psycopg")
    return parsed.render_as_string(hide_password=False)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    url = _configured_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    options: dict[str, object] = {"pool_pre_ping": True}
    if url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        options["connect_args"] = {"connect_timeout": 8, "sslmode": "require"}
    return create_engine(_normalize_url(url), **options)


def check_database() -> tuple[bool, str]:
    """Test connectivity without exposing driver messages or connection details."""
    if not _configured_url():
        return False, "Database is not configured. Set DATABASE_URL in your local .env file."
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, "Database connection successful."
    except (SQLAlchemyError, RuntimeError, ValueError):
        return False, "Database connection failed. Check the local DATABASE_URL and provider status. Details are hidden to protect credentials."
