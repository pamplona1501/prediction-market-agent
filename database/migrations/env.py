from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from database.connection import _normalize_url
from database.models import Base


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL_POOLED")
    if not url:
        raise RuntimeError("Set DATABASE_URL before running database migrations")
    context.configure(url=_normalize_url(url), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL_POOLED")
    if not url:
        raise RuntimeError("Set DATABASE_URL before running database migrations")
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _normalize_url(url)
    connect_args = {"sslmode": "require", "connect_timeout": 8} if url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")) else {}
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool, connect_args=connect_args)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
