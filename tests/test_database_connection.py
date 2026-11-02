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


def test_database_health_falls_back_from_pooled_to_direct_without_leaking_url(monkeypatch):
    import database.connection as connection_module

    pooled = "postgresql://pool@pool.example.test/app"
    direct = "postgresql://direct@direct.example.test/app"
    monkeypatch.setenv("DATABASE_URL_POOLED", pooled)
    monkeypatch.setenv("DATABASE_URL", direct)
    attempted = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, statement):
            return None

    class Engine:
        def __init__(self, should_fail):
            self.should_fail = should_fail

        def connect(self):
            if self.should_fail:
                raise RuntimeError("synthetic connection failure")
            return Connection()

    def fake_get_engine(url):
        attempted.append(url)
        return Engine(url == pooled)

    monkeypatch.setattr(connection_module, "get_engine", fake_get_engine)
    success, message = check_database()

    assert success
    assert message == "Database connected through DATABASE_URL; the pooled URL is unavailable. Check DATABASE_URL_POOLED."
    assert attempted == [pooled, direct]
    assert pooled not in message
    assert direct not in message


def test_initial_schema_has_expected_tables_and_constraints():
    assert set(Base.metadata.tables) == {
        "events",
        "event_provider_references",
        "strategy_evaluations",
        "execution_intents",
        "markets",
        "market_outcomes",
        "market_snapshots",
        "match_snapshots",
        "watchlist_items",
    }
    outcomes = Base.metadata.tables["market_outcomes"]
    assert any(constraint.name == "uq_market_outcomes_market_key" for constraint in outcomes.constraints)
    assert "market_volume_usd" in Base.metadata.tables["market_snapshots"].columns
