"""Database configuration and secret-safe connectivity checks."""

from functools import lru_cache
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError


load_dotenv()


def _configured_urls() -> list[str]:
    """Return pooled-first URLs, with direct connection as a safe fallback."""
    urls = [os.getenv("DATABASE_URL_POOLED"), os.getenv("DATABASE_URL")]
    return list(dict.fromkeys(url for url in urls if url))


def database_configuration() -> tuple[bool, str]:
    """Return presence/type only; never return the configured URL."""
    urls = _configured_urls()
    if not urls:
        return False, "Not configured"
    try:
        parsed = make_url(urls[0])
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


@lru_cache(maxsize=2)
def get_engine(url: str | None = None) -> Engine:
    url = url or next(iter(_configured_urls()), None)
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    options: dict[str, object] = {"pool_pre_ping": True}
    if url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        options["connect_args"] = {"connect_timeout": 8, "sslmode": "require"}
    return create_engine(_normalize_url(url), **options)


def check_database() -> tuple[bool, str]:
    """Test connectivity without exposing driver messages or connection details."""
    urls = _configured_urls()
    if not urls:
        return False, "Database is not configured. Set DATABASE_URL in your local .env file."
    for index, url in enumerate(urls):
        try:
            with get_engine(url).connect() as connection:
                connection.execute(text("SELECT 1"))
            if index:
                return True, "Database connected through DATABASE_URL; the pooled URL is unavailable. Check DATABASE_URL_POOLED."
            return True, "Database connection successful."
        except (SQLAlchemyError, RuntimeError, ValueError):
            continue
    return False, "Database connection failed. Check the local DATABASE_URL settings and provider status. Details are hidden to protect credentials."
