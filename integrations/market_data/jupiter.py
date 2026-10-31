"""Read-only client for Jupiter's documented Prediction Market API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import os
import threading
import time
from typing import Any
from urllib.parse import quote

import requests

from integrations.http import SafeReadError, read_only_get


BASE_URL = "https://api.jup.ag/prediction/v1"
MICRO_USD = Decimal("1000000")
_KEYLESS_INTERVAL_SECONDS = 2.0
_request_rate_lock = threading.Lock()
_last_request = 0.0


class JupiterDataError(RuntimeError):
    """Safe provider error that never includes request headers or response bodies."""


@dataclass(frozen=True)
class JupiterMarket:
    market_id: str
    title: str
    status: str | None
    provider: str | None
    buy_yes_usd: Decimal | None
    sell_yes_usd: Decimal | None
    buy_no_usd: Decimal | None
    sell_no_usd: Decimal | None
    volume_usd: Decimal | None
    sports_market_type: str | None
    period_type: str | None
    sports_line: str | None
    team_name: str | None
    team_abbreviation: str | None
    team_color: str | None
    team_image_url: str | None
    market_options: tuple[str, ...]


@dataclass(frozen=True)
class JupiterEvent:
    event_id: str
    title: str
    category: str | None
    subcategory: str | None
    is_live: bool | None
    reported_volume_usd: Decimal | None
    markets: tuple[JupiterMarket, ...]


@dataclass(frozen=True)
class JupiterEventPage:
    events: tuple[JupiterEvent, ...]
    fetched_at: datetime
    filter_name: str


@dataclass(frozen=True)
class JupiterMarketPage:
    event_id: str
    markets: tuple[JupiterMarket, ...]
    start: int
    end: int
    total: int | None
    has_next: bool
    fetched_at: datetime


@dataclass(frozen=True)
class JupiterLiveScore:
    event_id: str
    league_abbreviation: str | None
    home_team: str
    away_team: str
    score: str | None
    period: str | None
    elapsed: str | None
    status: str | None
    updated_at: str | None


def _micro_usd(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value)) / MICRO_USD
    except (InvalidOperation, ValueError, TypeError):
        return None


def _reported_usd(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _parse_market(item: Any) -> JupiterMarket | None:
    if not isinstance(item, dict) or not item.get("marketId"):
        return None
    pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
    team = item.get("team") if isinstance(item.get("team"), dict) else {}
    options = item.get("marketOptions") if isinstance(item.get("marketOptions"), list) else []
    return JupiterMarket(
        market_id=str(item["marketId"]),
        title=str(item.get("title") or "Untitled market"),
        status=str(item["status"]) if item.get("status") is not None else None,
        provider=str(item["provider"]) if item.get("provider") is not None else None,
        buy_yes_usd=_micro_usd(pricing.get("buyYesPriceUsd")),
        sell_yes_usd=_micro_usd(pricing.get("sellYesPriceUsd")),
        buy_no_usd=_micro_usd(pricing.get("buyNoPriceUsd")),
        sell_no_usd=_micro_usd(pricing.get("sellNoPriceUsd")),
        volume_usd=_reported_usd(pricing.get("volume")),
        sports_market_type=str(item["sportsMarketType"]) if item.get("sportsMarketType") is not None else None,
        period_type=str(item["periodType"]) if item.get("periodType") is not None else None,
        sports_line=str(item["sportsLine"]) if item.get("sportsLine") is not None else None,
        team_name=str(team["name"]) if team.get("name") is not None else None,
        team_abbreviation=str(team["abbreviation"]) if team.get("abbreviation") is not None else None,
        team_color=str(team["color"]) if team.get("color") is not None else None,
        team_image_url=str(team["imageUrl"]) if team.get("imageUrl") is not None else None,
        market_options=tuple(
            str(option["label"])
            for option in options
            if isinstance(option, dict) and option.get("label") is not None
        ),
    )


def _parse_event(item: Any) -> JupiterEvent | None:
    if not isinstance(item, dict) or not item.get("eventId"):
        return None
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    raw_markets = item.get("markets") if isinstance(item.get("markets"), list) else []
    markets = tuple(market for raw in raw_markets if (market := _parse_market(raw)) is not None)
    is_live = item.get("isLive")
    if not isinstance(is_live, bool):
        is_live = metadata.get("isLive") if isinstance(metadata.get("isLive"), bool) else None
    return JupiterEvent(
        event_id=str(item["eventId"]),
        title=str(metadata.get("title") or item.get("title") or "Untitled event"),
        category=str(item["category"]) if item.get("category") is not None else None,
        subcategory=str(item["subcategory"]) if item.get("subcategory") is not None else None,
        is_live=is_live,
        reported_volume_usd=_reported_usd(item.get("volumeUsd")),
        markets=markets,
    )


class JupiterPredictionClient:
    """Fetch event and market details only; no write or transaction methods exist here."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = BASE_URL,
        session: requests.Session | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(cls) -> "JupiterPredictionClient":
        return cls(api_key=(os.getenv("JUPITER_API_KEY") or "").strip() or None)

    def _get_json(self, path: str, params: dict[str, object]) -> Any:
        global _last_request
        # A publishable Jupiter key has the same request rate as keyless use.
        # Use the conservative 0.5 RPS cadence for either kind of key.
        with _request_rate_lock:
            now = time.monotonic()
            wait = _KEYLESS_INTERVAL_SECONDS - (now - _last_request)
            if _last_request and wait > 0:
                time.sleep(wait)
            _last_request = time.monotonic()
        headers = {"x-api-key": self._api_key} if self._api_key else {}
        try:
            response = read_only_get(
                self._session,
                f"{self._base_url}/{path.lstrip('/')}",
                params=params,
                headers=headers,
                timeout_seconds=self._timeout_seconds,
                provider_name="Jupiter",
            )
        except SafeReadError as exc:
            raise JupiterDataError(str(exc)) from None
        try:
            return response.json()
        except ValueError:
            raise JupiterDataError("Jupiter returned an unreadable response.") from None

    def list_sports_events(
        self, *, filter_name: str = "live", limit: int = 20, tag: str | None = None
    ) -> JupiterEventPage:
        if filter_name not in {"live", "upcoming", "trending"}:
            raise ValueError("Unsupported Jupiter event filter")
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")

        params = {
            "category": "sports",
            "filter": filter_name,
            "includeMarkets": "false",
            "start": 0,
            "end": limit,
        }
        if tag:
            if not 1 <= len(tag) <= 48 or not tag.replace("-", "").isalnum():
                raise ValueError("tag must be a short alphanumeric tag")
            params["tags"] = tag
        payload = self._get_json("events", params)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise JupiterDataError("Jupiter response did not match the documented event format.")

        events = tuple(event for raw in payload["data"] if (event := _parse_event(raw)) is not None)
        return JupiterEventPage(events=events, fetched_at=datetime.now(UTC), filter_name=filter_name)

    def get_live_scores(self, event_ids: list[str] | tuple[str, ...]) -> tuple[JupiterLiveScore, ...]:
        """Fetch documented live-score rows for up to 100 event IDs."""
        if not event_ids or len(event_ids) > 100 or any(not event_id or len(event_id) > 160 for event_id in event_ids):
            raise ValueError("event_ids must contain between 1 and 100 valid provider IDs")
        payload = self._get_json("events/scores", {"eventIds": ",".join(event_ids)})
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise JupiterDataError("Jupiter response did not match the documented live-scores format.")
        scores: list[JupiterLiveScore] = []
        for item in payload["data"]:
            if not isinstance(item, dict) or not item.get("eventId"):
                continue
            scores.append(
                JupiterLiveScore(
                    event_id=str(item["eventId"]),
                    league_abbreviation=(
                        str(item["leagueAbbreviation"]) if item.get("leagueAbbreviation") is not None else None
                    ),
                    home_team=str(item.get("homeTeam") or "Unknown home team"),
                    away_team=str(item.get("awayTeam") or "Unknown away team"),
                    score=str(item["score"]) if item.get("score") is not None else None,
                    period=str(item["period"]) if item.get("period") is not None else None,
                    elapsed=str(item["elapsed"]) if item.get("elapsed") is not None else None,
                    status=str(item["status"]) if item.get("status") is not None else None,
                    updated_at=str(item["updatedAt"]) if item.get("updatedAt") is not None else None,
                )
            )
        return tuple(scores)

    def get_sports_event_details(self, event_id: str) -> JupiterEvent:
        """Fetch documented selected-event details, then callers can select relevant market types."""
        if not event_id or len(event_id) > 160:
            raise ValueError("event_id must be a non-empty provider ID")
        payload = self._get_json(f"events/{quote(event_id, safe='')}", {})
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            payload = payload["data"]
        event = _parse_event(payload)
        if event is None or event.event_id != event_id:
            raise JupiterDataError("Jupiter event response did not match the requested event ID.")
        return event

    def get_sports_event_markets(self, event_id: str, *, start: int = 0, page_size: int = 20) -> JupiterMarketPage:
        """Read a bounded page of markets for one event; never fetch an unbounded event detail."""
        if not event_id or len(event_id) > 160:
            raise ValueError("event_id must be a non-empty provider ID")
        if start < 0 or not 1 <= page_size <= 20:
            raise ValueError("start must be non-negative and page_size must be between 1 and 20")
        payload = self._get_json(
            f"events/{quote(event_id, safe='')}/markets",
            {"start": start, "end": start + page_size},
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise JupiterDataError("Jupiter response did not match the documented event-markets format.")
        pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
        markets = tuple(market for raw in payload["data"] if (market := _parse_market(raw)) is not None)
        return JupiterMarketPage(
            event_id=event_id,
            markets=markets,
            start=start,
            end=start + page_size,
            total=int(pagination["total"]) if isinstance(pagination.get("total"), int) else None,
            has_next=bool(pagination.get("hasNext", len(markets) == page_size)),
            fetched_at=datetime.now(UTC),
        )
