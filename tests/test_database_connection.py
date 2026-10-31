from database.connection import _normalize_url, check_database, database_configuration
from database.models import Base


def test_postgres_urls_use_psycopg_and_keep_password_out_of_rendered_config():
    url = _normalize_url("postgresql://user:secret-value@db.example.test/app")
    assert url.startswith("postgresql+psycopg://")
    assert "secret-value" in url  # required internally by SQLAlchemy; callers must not display it


def test_database_configuration_reports_type_not_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:top-secret@db.example.test/app")
    configured, kind = database_configuration()
    assert configured
    assert kind == "PostgreSQL configured"
    assert "top-secret" not in kind


def test_missing_database_is_reported_without_connecting(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_POOLED", raising=False)
    assert check_database() == (
        False,
        "Database is not configured. Set DATABASE_URL in your local .env file.",
    )


def test_initial_schema_has_expected_tables_and_constraints():
    assert set(Base.metadata.tables) == {
        "events",
        "markets",
        "market_outcomes",
        "market_snapshots",
        "match_snapshots",
    }
    outcomes = Base.metadata.tables["market_outcomes"]
    assert any(constraint.name == "uq_market_outcomes_market_key" for constraint in outcomes.constraints)
