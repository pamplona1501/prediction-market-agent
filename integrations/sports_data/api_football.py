"""Read-only API-Football client for live fixtures and team statistics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import os
import threading
import time
from typing import Any

import requests

from integrations.http import SafeReadError, read_only_get


BASE_URL = "https://v3.football.api-sports.io"
_FREE_PLAN_MIN_INTERVAL_SECONDS = 6.0
_request_rate_lock = threading.Lock()
_last_request_started = 0.0


class SportsDataError(RuntimeError):
    """Safe provider error; response bodies and authentication data are omitted."""


class SportsProviderNotConfigured(SportsDataError):
    pass


@dataclass(frozen=True)
class LiveFixture:
    fixture_id: int
    league: str
    home_team: str
    away_team: str
    scheduled_start_at: datetime | None
    status: str
    elapsed_minute: int | None
    home_score: int | None
    away_score: int | None
    received_at: datetime


@dataclass(frozen=True)
class TeamStatistics:
    team_id: int | None
    team_name: str
    shots_total: int | None
    possession_percent: float | None
    corners: int | None


@dataclass(frozen=True)
class FixtureStatistics:
    fixture_id: int
    teams: tuple[TeamStatistics, ...]
    received_at: datetime


class ApiFootballClient:
    """Read-only API client. No order, betting, or transaction endpoints exist here."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 10.0,
        minimum_request_interval_seconds: float = _FREE_PLAN_MIN_INTERVAL_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._session = session or requests.Session()
        self._timeout_seconds = timeout_seconds
        self._minimum_request_interval_seconds = max(0.0, minimum_request_interval_seconds)

    @classmethod
    def from_environment(cls) -> "ApiFootballClient":
        return cls(api_key=(os.getenv("API_FOOTBALL_KEY") or "").strip() or None)

    def _get(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        global _last_request_started
        if not self._api_key:
            raise SportsProviderNotConfigured("API_FOOTBALL_KEY is not configured.")
        with _request_rate_lock:
            now = time.monotonic()
            wait = self._minimum_request_interval_seconds - (now - _last_request_started)
            if _last_request_started and wait > 0:
                time.sleep(wait)
            _last_request_started = time.monotonic()
        try:
            response = read_only_get(
                self._session,
                f"{BASE_URL}/{path.lstrip('/')}",
                params=params,
                headers={"x-apisports-key": self._api_key},
                timeout_seconds=self._timeout_seconds,
                provider_name="API-Football",
            )
        except SafeReadError as exc:
            raise SportsDataError(str(exc)) from None
        try:
            payload = response.json()
        except ValueError:
            raise SportsDataError("API-Football returned an unreadable response.") from None
        if not isinstance(payload, dict):
            raise SportsDataError("API-Football response did not match the documented format.")
        if payload.get("errors"):
            raise SportsDataError("API-Football reported a request error. Check provider configuration.")
        records = payload.get("response")
        if not isinstance(records, list):
            raise SportsDataError("API-Football response did not contain a result list.")
        return records

    def get_live_fixtures(self) -> tuple[LiveFixture, ...]:
        records = self._get("fixtures", {"live": "all"})
        received_at = datetime.now(UTC)
        fixtures: list[LiveFixture] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            fixture = record.get("fixture") if isinstance(record.get("fixture"), dict) else {}
            teams = record.get("teams") if isinstance(record.get("teams"), dict) else {}
            goals = record.get("goals") if isinstance(record.get("goals"), dict) else {}
            league = record.get("league") if isinstance(record.get("league"), dict) else {}
            home = teams.get("home") if isinstance(teams.get("home"), dict) else {}
            away = teams.get("away") if isinstance(teams.get("away"), dict) else {}
            status = fixture.get("status") if isinstance(fixture.get("status"), dict) else {}
            try:
                fixture_id = int(fixture["id"])
            except (KeyError, TypeError, ValueError):
                continue
            fixtures.append(
                LiveFixture(
                    fixture_id=fixture_id,
                    league=str(league.get("name") or "Unknown competition"),
                    home_team=str(home.get("name") or "Unknown home team"),
                    away_team=str(away.get("name") or "Unknown away team"),
                    scheduled_start_at=_optional_datetime(fixture.get("date")),
                    status=str(status.get("short") or "UNKNOWN"),
                    elapsed_minute=_optional_int(status.get("elapsed")),
                    home_score=_optional_int(goals.get("home")),
                    away_score=_optional_int(goals.get("away")),
                    received_at=received_at,
                )
            )
        return tuple(fixtures)

    def get_fixture_statistics(self, fixture_id: int) -> FixtureStatistics:
        if fixture_id <= 0:
            raise ValueError("fixture_id must be positive")
        records = self._get("fixtures/statistics", {"fixture": fixture_id})
        if not records:
            raise SportsDataError("No statistics were returned for this fixture.")
        teams: list[TeamStatistics] = []
        for team_record in records:
            if not isinstance(team_record, dict):
                continue
            team = team_record.get("team") if isinstance(team_record.get("team"), dict) else {}
            values = team_record.get("statistics") if isinstance(team_record.get("statistics"), list) else []
            by_name = {
                value.get("type"): value.get("value")
                for value in values
                if isinstance(value, dict) and isinstance(value.get("type"), str)
            }
            team_id = _optional_int(team.get("id"))
            teams.append(
                TeamStatistics(
                    team_id=team_id,
                    team_name=str(team.get("name") or "Unknown team"),
                    shots_total=_optional_int(by_name.get("Total Shots")),
                    possession_percent=_optional_percent(by_name.get("Ball Possession")),
                    corners=_optional_int(by_name.get("Corner Kicks")),
                )
            )
        return FixtureStatistics(fixture_id=fixture_id, teams=tuple(teams), received_at=datetime.now(UTC))


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_percent(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.strip().removesuffix("%")
        return float(value)
    except (TypeError, ValueError):
        return None
