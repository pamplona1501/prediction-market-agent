"""Near-live provider polling with bounded async subscriber fan-out."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
import re
import time
import unicodedata
from typing import Any

from integrations.market_data.capture import (
    persist_event_snapshot,
    persist_execution_intents,
    persist_prematch_event,
    persist_strategy_audit,
)
from integrations.market_data.jupiter import (
    JUPITER_PRIORITY_LIVE,
    JUPITER_PRIORITY_RADAR,
    JupiterDataError,
    JupiterEvent,
    JupiterLiveScore,
    JupiterMarket,
    JupiterOrderBook,
    JupiterPredictionClient,
)
from database.connection import get_engine
from database.provider_mapping import (
    record_livescore_mcp_statistics,
    livescore_mcp_mapping_status,
)
from database.snapshots import read_prematch_yes_prices
from database.watchlist import add_event as add_watchlist_event
from database.watchlist import read_watchlist as read_saved_watchlist
from database.watchlist import remove_event as remove_watchlist_event
from sqlalchemy.orm import Session
from integrations.sports_data.livescore_mcp import LiveScoreMCPClient, LiveScoreMCPError, MatchStatistics
from strategies.live import AskLevel, CandidateConfig, MarketQuote, MatchInputs, evaluate_live_match
from engine.execution.jupiter_broker import (
    MAXIMUM_SLIPPAGE_BPS,
    MINIMUM_ORDER_USD,
    ExecutionTicket,
    JupiterBrokerEngine,
)

UPCOMING_MIN_VOLUME_USD = Decimal("100000")


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _decimal(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _minute(value: str | None) -> int | None:
    match = re.search(r"\d+", value or "")
    return int(match.group()) if match else None


def _is_suspended(value: str | None) -> bool:
    return isinstance(value, str) and value.strip().casefold() == "suspended"


def _exclude_suspended_events(
    events: tuple[JupiterEvent, ...], scores: tuple[JupiterLiveScore, ...],
) -> tuple[tuple[JupiterEvent, ...], set[str]]:
    scores_by_id = {score.event_id: score for score in scores}
    suspended_ids = {
        event_id for event_id, score in scores_by_id.items()
        if _is_suspended(score.status) or _is_suspended(score.period)
    }
    return tuple(event for event in events if event.event_id not in suspended_ids), suspended_ids


def _normalize_team_label(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.casefold()).strip()


def _classify_upcoming_moneyline(event: JupiterEvent) -> tuple[dict[str, JupiterMarket], list[str], str | None, str | None]:
    """Map a future event's three moneyline quotes from its title and market labels."""
    teams = re.split(r"\s+(?:vs?\.?|@)\s+", event.title, maxsplit=1, flags=re.IGNORECASE)
    if len(teams) != 2:
        return {}, ["Could not identify home and away teams from the Jupiter event title."], None, None
    home_team, away_team = (part.strip() for part in teams)
    home_key, away_key = _normalize_team_label(home_team), _normalize_team_label(away_team)
    if not home_key or not away_key or home_key == away_key:
        return {}, ["Jupiter event title does not identify two distinct teams."], home_team, away_team

    assigned: dict[str, JupiterMarket] = {}
    for market in event.markets:
        if market.sports_market_type != "moneyline":
            continue
        title_key = _normalize_team_label(market.title)
        team_key = _normalize_team_label(market.team_name or "")
        if title_key in {"draw", "tie", "x"} or team_key in {"draw", "tie", "x"}:
            outcome = "DRAW"
        elif team_key == home_key or (not team_key and title_key == home_key):
            outcome = "HOME"
        elif team_key == away_key or (not team_key and title_key == away_key):
            outcome = "AWAY"
        else:
            continue
        if outcome in assigned:
            return {}, [f"Multiple upcoming moneyline contracts matched {outcome}; mapping is ambiguous."], home_team, away_team
        assigned[outcome] = market

    missing = sorted({"HOME", "DRAW", "AWAY"} - assigned.keys())
    reasons = [f"Missing upcoming moneyline outcome: {outcome}." for outcome in missing]
    return assigned, reasons, home_team, away_team


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _levels(levels: tuple[Any, ...]) -> list[dict[str, str]]:
    return [
        {"price_usd": _decimal(level.price_usd) or "0", "quantity": _decimal(level.quantity) or "0"}
        for level in levels
    ]


def orderbook_view(book: JupiterOrderBook) -> dict[str, Any]:
    yes_bid = max(book.yes_bids, key=lambda level: level.price_usd, default=None)
    no_bid = max(book.no_bids, key=lambda level: level.price_usd, default=None)
    yes_asks, no_asks = book.yes_asks, book.no_asks
    yes_ask = yes_asks[0] if yes_asks else None
    no_ask = no_asks[0] if no_asks else None
    yes_depth = sum((level.price_usd * level.quantity for level in yes_asks), Decimal("0"))
    no_depth = sum((level.price_usd * level.quantity for level in no_asks), Decimal("0"))
    return {
        "fetched_at": _iso(book.fetched_at),
        "yes_bid": _decimal(yes_bid.price_usd) if yes_bid else None,
        "yes_ask": _decimal(yes_ask.price_usd) if yes_ask else None,
        "yes_ask_depth_usd": _decimal(yes_depth) if yes_asks else None,
        "no_bid": _decimal(no_bid.price_usd) if no_bid else None,
        "no_ask": _decimal(no_ask.price_usd) if no_ask else None,
        "no_ask_depth_usd": _decimal(no_depth) if no_asks else None,
        "yes_bids": _levels(book.yes_bids),
        "yes_asks": _levels(yes_asks),
        "no_bids": _levels(book.no_bids),
        "no_asks": _levels(no_asks),
    }


def _classify_moneyline(
    event: JupiterEvent, score: JupiterLiveScore | None
) -> tuple[dict[str, JupiterMarket], list[str]]:
    if not score:
        return {}, ["No Jupiter score row is available to identify home and away outcomes."]
    home, away = score.home_team.strip().casefold(), score.away_team.strip().casefold()
    assignments: dict[str, JupiterMarket] = {}
    for market in event.markets:
        if market.sports_market_type != "moneyline":
            continue
        team = (market.team_name or "").strip().casefold()
        title = market.title.strip().casefold()
        if title in {"draw", "tie", "x"}:
            outcome = "DRAW"
        elif team == home or title == home:
            outcome = "HOME"
        elif team == away or title == away:
            outcome = "AWAY"
        else:
            continue
        if outcome in assignments:
            return {}, [f"Multiple moneyline contracts matched {outcome}; mapping is ambiguous."]
        assignments[outcome] = market
    missing = sorted({"HOME", "DRAW", "AWAY"} - assignments.keys())
    reasons = [f"Missing moneyline outcome: {outcome}." for outcome in missing]
    return assignments, reasons


class LiveMonitor:
    """Polls verified REST interfaces and streams compact state updates to clients."""

    def __init__(
        self,
        *,
        jupiter: JupiterPredictionClient | None = None,
        livescore_mcp: LiveScoreMCPClient | None = None,
        poll_seconds: float | None = None,
        prematch_refresh_seconds: float = 300.0,
        persist=persist_event_snapshot,
        broker: JupiterBrokerEngine | None = None,
    ) -> None:
        self.jupiter = jupiter or JupiterPredictionClient.from_environment()
        self.livescore_mcp = livescore_mcp or LiveScoreMCPClient()
        self.poll_seconds = poll_seconds or float(os.getenv("LIVE_POLL_SECONDS", "30"))
        self.poll_seconds = min(max(self.poll_seconds, 15.0), 300.0)
        self.prematch_refresh_seconds = prematch_refresh_seconds
        self.persist = persist
        self.broker = broker or JupiterBrokerEngine()
        self.selected_event_id: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._upcoming_task: asyncio.Task[None] | None = None
        self._upcoming_initial_scan = asyncio.Event()
        self._stats_autofetch_task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._stopping = asyncio.Event()
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._logs: deque[dict[str, str]] = deque(maxlen=100)
        self._last_fixture_poll = 0.0
        self._previous_upcoming_volumes: dict[str, Decimal] = {}
        self._last_score_by_id: dict[str, JupiterLiveScore] = {}
        self._upcoming_event_cache: dict[str, JupiterEvent] = {}
        self._last_manual_stats_refresh: float | None = None
        self._refresh_lock = asyncio.Lock()
        self.state: dict[str, Any] = {
            "service": {"status": "starting", "poll_seconds": self.poll_seconds},
            "jupiter": {
                "status": "unconfigured",
                "auth": "API key loaded" if (os.getenv("JUPITER_API_KEY") or "").strip() else "keyless access",
                "last_success_at": None,
                "last_error": None,
            },
            "livescore_mcp": {
                "status": "on_demand",
                "last_success_at": None,
                "last_error": None,
            },
            "events": [],
            "prematch_baselines": {"status": "waiting", "last_capture_at": None},
            "upcoming_matches": [],
            "selected_upcoming_event": None,
            "upcoming_radar": {
                "status": "starting",
                "last_success_at": None,
                "last_error": None,
                "refresh_seconds": self.prematch_refresh_seconds,
            },
            "watchlist": [],
            "watchlist_status": "starting",
            "selected_event_id": None,
            "selected_event": None,
            "logs": [],
            "execution": "disabled",
        }

    async def start(self) -> None:
        if self._task is None or self._task.done():
            await self.jupiter.open()
            await self.livescore_mcp.open()
            self._stopping.clear()
            self._upcoming_initial_scan.clear()
            self._task = asyncio.create_task(self._run(), name="live-match-monitor")
            self._upcoming_task = asyncio.create_task(
                self._run_upcoming_radar(), name="upcoming-match-radar",
            )
            await self._refresh_watchlist()
            self._apply_watchlist_flags()
            self._wake.set()
            try:
                await asyncio.wait_for(self._upcoming_initial_scan.wait(), timeout=20.0)
            except TimeoutError:
                self._log("warning", "Upcoming radar has not completed its initial scan yet; it will continue in the background.")
                await self._publish()

    async def stop(self) -> None:
        self._stopping.set()
        self._wake.set()
        if self._stats_autofetch_task:
            self._stats_autofetch_task.cancel()
            await asyncio.gather(self._stats_autofetch_task, return_exceptions=True)
            self._stats_autofetch_task = None
        if self._task:
            await self._task
            self._task = None
        if self._upcoming_task:
            await self._upcoming_task
            self._upcoming_task = None
        await self.jupiter.close()
        await self.livescore_mcp.close()

    def snapshot(self) -> dict[str, Any]:
        # State is replaced rather than mutated after publish, so shallow nested copies
        # are safe for this JSON-facing boundary.
        return {**self.state, "logs": list(self._logs)}

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        self._subscribers.add(queue)
        queue.put_nowait(self.snapshot())
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    async def watch_event(self, event_id: str) -> None:
        if not any(row.get("event_id") == event_id for row in self.state.get("upcoming_matches", [])):
            raise ValueError("Select an upcoming match from the current radar list.")
        try:
            await asyncio.to_thread(add_watchlist_event, event_id)
        except (RuntimeError, ValueError):
            raise
        await self._refresh_watchlist()
        self._apply_watchlist_flags()
        await self._publish()

    async def unwatch_event(self, event_id: str) -> None:
        try:
            await asyncio.to_thread(remove_watchlist_event, event_id)
        except RuntimeError:
            raise
        await self._refresh_watchlist()
        self._apply_watchlist_flags()
        await self._publish()

    async def select_upcoming_event(self, event_id: str) -> None:
        """Show a future event's cached Jupiter markets without starting live monitoring."""
        if not any(row.get("event_id") == event_id for row in self.state.get("upcoming_matches", [])):
            raise ValueError("Select an upcoming match from the current radar list.")
        event = self._upcoming_event_cache.get(event_id)
        if event is None:
            raise ValueError("Upcoming market details are refreshing. Select the match again shortly.")
        self.state = {
            **self.state,
            "selected_upcoming_event": self._upcoming_detail_view(event),
        }
        self._apply_watchlist_flags()
        self._log("info", f"Opened upcoming market details for {event.title}; live monitoring was not started.")
        await self._publish()

    def _upcoming_detail_view(self, event: JupiterEvent) -> dict[str, Any]:
        assigned, reasons, home_team, away_team = _classify_upcoming_moneyline(event)
        market_rows = []
        for outcome in ("HOME", "DRAW", "AWAY"):
            market = assigned.get(outcome)
            if market is None:
                continue
            market_rows.append({
                "outcome": outcome,
                "market_id": market.market_id,
                "title": market.title,
                "team": market.team_name,
                "status": market.status,
                "market_volume_usd": _decimal(market.volume_usd),
                "buy_yes_usd": _decimal(market.buy_yes_usd),
                "sell_yes_usd": _decimal(market.sell_yes_usd),
                "buy_no_usd": _decimal(market.buy_no_usd),
                "sell_no_usd": _decimal(market.sell_no_usd),
            })
        return {
            "event_id": event.event_id,
            "title": event.title,
            "home_team": home_team,
            "away_team": away_team,
            "scheduled_start_at": _iso(event.scheduled_start_at),
            "event_volume_usd": _decimal(event.reported_volume_usd),
            "fetched_at": self.state.get("upcoming_radar", {}).get("last_success_at"),
            "moneyline_complete": not reasons,
            "moneyline_gate_reasons": reasons,
            "moneyline": market_rows,
            "market_detail_count": len(event.markets),
            "market_source": "Jupiter upcoming event feed · refreshes every five minutes",
            "status": "healthy" if not reasons and len(market_rows) == 3 else "partial",
        }

    async def _refresh_watchlist(self) -> None:
        try:
            rows = await asyncio.to_thread(read_saved_watchlist)
        except RuntimeError:
            self.state = {**self.state, "watchlist_status": "unavailable"}
            return
        self.state = {
            **self.state,
            "watchlist": rows,
            "watchlist_status": "healthy",
        }

    def _apply_watchlist_flags(self) -> None:
        watched = {row.get("event_id") for row in self.state.get("watchlist", [])}
        selected_upcoming_id = (self.state.get("selected_upcoming_event") or {}).get("event_id")
        events = [
            {**row, "watched": row.get("event_id") in watched}
            for row in self.state.get("events", [])
        ]
        upcoming = [
            {**row, "watched": row.get("event_id") in watched,
             "selected": row.get("event_id") == selected_upcoming_id}
            for row in self.state.get("upcoming_matches", [])
        ]
        self.state = {**self.state, "events": events, "upcoming_matches": upcoming}

    def _log(self, level: str, message: str) -> None:
        self._logs.appendleft({"at": datetime.now(UTC).isoformat(), "level": level, "message": message})

    async def _publish(self) -> None:
        payload = self.snapshot()
        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                continue

    async def monitor_event(self, event_id: str | None) -> None:
        if event_id is not None and not any(row["event_id"] == event_id for row in self.state["events"]):
            raise ValueError("Select a live Jupiter event from the current list.")
        if self._stats_autofetch_task and not self._stats_autofetch_task.done():
            self._stats_autofetch_task.cancel()
            self._stats_autofetch_task = None
        self.selected_event_id = event_id
        self.state = {
            **self.state,
            "selected_event_id": event_id,
            "selected_event": None,
        }
        self._log("info", "Match monitoring stopped." if event_id is None else f"Monitoring selected event {event_id}.")
        await self._publish()
        self._wake.set()
        if event_id is not None:
            self._stats_autofetch_task = asyncio.create_task(
                self._fetch_initial_statistics(event_id),
                name=f"initial-match-stats-{event_id}",
            )

    async def _fetch_initial_statistics(self, event_id: str) -> None:
        """Fetch stats once after this user-selected event's Jupiter detail is ready."""
        deadline = time.monotonic() + 45.0
        while self.selected_event_id == event_id:
            selected = self.state.get("selected_event")
            if selected and selected.get("event_id") == event_id:
                if selected.get("status") == "not_in_live_feed":
                    self._log("warning", f"Skipped initial statistics fetch; Jupiter has no current score for {event_id}.")
                    return
                selected = {**selected, "statistics": {"status": "loading", "provider": "livescore_mcp"}}
                self.state = {**self.state, "selected_event": selected}
                self._log("info", f"Fetching initial LiveScore MCP statistics for selected event {event_id}.")
                await self._publish()
                break
            if time.monotonic() >= deadline:
                self._log("warning", f"Initial statistics fetch timed out waiting for Jupiter details for {event_id}.")
                await self._publish()
                return
            await asyncio.sleep(0.2)
        else:
            return

        # Respect the same provider cooldown as manual refreshes, even when
        # the user selects another match soon after a previous stats request.
        remaining = (
            15.0 - (time.monotonic() - self._last_manual_stats_refresh)
            if self._last_manual_stats_refresh is not None else 0.0
        )
        if remaining > 0:
            await asyncio.sleep(remaining)
        if self.selected_event_id == event_id:
            try:
                await self.refresh_match_statistics(event_id)
            except ValueError as exc:
                selected = self.state.get("selected_event")
                if selected and selected.get("event_id") == event_id:
                    selected = {**selected, "statistics": {"status": "error", "error": str(exc)}}
                    self.state = {**self.state, "selected_event": selected}
                self._log("warning", f"Initial LiveScore MCP statistics fetch failed: {exc}")
                await self._publish()

    async def refresh_match_statistics(self, event_id: str) -> dict[str, Any]:
        """Fetch one user-selected match; never called from the recurring poll loop."""
        if event_id != self.selected_event_id:
            raise ValueError("Select and monitor this Jupiter event before fetching match statistics.")
        score = self._last_score_by_id.get(event_id)
        if score is None:
            raise ValueError("Jupiter has not supplied a current score for this selected event.")
        if (
            self._last_manual_stats_refresh is not None
            and time.monotonic() - self._last_manual_stats_refresh < 15.0
        ):
            raise ValueError("Please wait 15 seconds between LiveScore MCP requests.")
        self._last_manual_stats_refresh = time.monotonic()
        try:
            statistics = await self.livescore_mcp.aget_match_statistics(
                home_team=score.home_team,
                away_team=score.away_team,
                score=score.score or "",
            )
            if not statistics.has_statistics:
                raise LiveScoreMCPError("The selected live match has no match statistics yet.")
            stored = await asyncio.to_thread(self._save_livescore_statistics, event_id, score, statistics)
            self.state = {
                **self.state,
                "livescore_mcp": {
                    "status": "healthy",
                    "last_success_at": _iso(statistics.received_at),
                    "last_error": None,
                },
            }
            selected = self.state.get("selected_event")
            if selected and selected.get("event_id") == event_id:
                selected = {**selected, "statistics": self._statistics_view(statistics, stored)}
                mapping = {
                    "status": "verified",
                    "fixture_id": statistics.match_id,
                    "name": f"{statistics.home_team} vs {statistics.away_team}",
                    "verified_at": _iso(statistics.received_at),
                }
                selected["fixture_mapping"] = mapping
                evaluations, audit_input = self._evaluate_selected(score, selected, mapping)
                await self._process_candidate_intents(event_id, selected, evaluations)
                selected["strategy_evaluations"] = evaluations
                selected["data_gates"] = evaluations[0]["gate_results"] if evaluations else {}
                selected["statistics"]["persistence"] = "saved" if stored else "unavailable"
                selected["statistics"]["persistence_note"] = None if stored else "Database snapshot could not be saved."
                self.state = {**self.state, "selected_event": selected}
                audit_saved, audit_rows = await asyncio.to_thread(
                    persist_strategy_audit, event_id, evaluations, audit_input,
                )
                selected["strategy_audit"] = "saved" if audit_saved else "unavailable"
                selected["strategy_audit_rows"] = audit_rows
                self.state = {**self.state, "selected_event": selected}
            self._log("info", f"Fetched selected-match statistics from LiveScore MCP for event {event_id}.")
        except LiveScoreMCPError as exc:
            current = dict(self.state.get("livescore_mcp", {}))
            current.update(status="error", last_error=str(exc))
            self.state = {**self.state, "livescore_mcp": current}
            selected = self.state.get("selected_event")
            if selected and selected.get("event_id") == event_id:
                selected = {**selected}
                previous = selected.get("statistics")
                if previous and previous.get("status") == "healthy":
                    selected["statistics"] = {**previous, "last_refresh_error": str(exc)}
                else:
                    selected["statistics"] = {"status": "error", "error": str(exc)}
                self.state = {**self.state, "selected_event": selected}
            self._log("warning", f"LiveScore MCP match-statistics refresh failed: {exc}")
        await self._publish()
        return self.snapshot()

    @staticmethod
    def _statistics_view(statistics: MatchStatistics, stored: bool) -> dict[str, Any]:
        return {
            "status": "healthy",
            "provider": "livescore_mcp",
            "match_id": statistics.match_id,
            "score": statistics.score,
            "match_verified": True,
            "score_consistent": statistics.score_consistent,
            "received_at": _iso(statistics.received_at),
            "home_shots": statistics.home_shots,
            "away_shots": statistics.away_shots,
            "home_shots_on_target": statistics.home_shots_on_target,
            "away_shots_on_target": statistics.away_shots_on_target,
            "home_possession": statistics.home_possession,
            "away_possession": statistics.away_possession,
            "home_passes": statistics.home_passes,
            "away_passes": statistics.away_passes,
            "home_pass_accuracy": statistics.home_pass_accuracy,
            "away_pass_accuracy": statistics.away_pass_accuracy,
            "home_fouls": statistics.home_fouls,
            "away_fouls": statistics.away_fouls,
            "home_yellow_cards": statistics.home_yellow_cards,
            "away_yellow_cards": statistics.away_yellow_cards,
            "home_red_cards": statistics.home_red_cards,
            "away_red_cards": statistics.away_red_cards,
            "home_offsides": statistics.home_offsides,
            "away_offsides": statistics.away_offsides,
            "home_corners": statistics.home_corners,
            "away_corners": statistics.away_corners,
            "persistence": "saved" if stored else "unavailable",
        }

    @staticmethod
    def _save_livescore_statistics(event_id: str, score: JupiterLiveScore, statistics: MatchStatistics) -> bool:
        try:
            with Session(get_engine()) as session, session.begin():
                return record_livescore_mcp_statistics(
                    session, jupiter_event_id=event_id, score=score, statistics=statistics,
                )
        except Exception:
            return False

    async def _run(self) -> None:
        while not self._stopping.is_set():
            # Clear before work so a selection wake-up arriving during a poll
            # is not discarded just before the following wait.
            self._wake.clear()
            cycle_started = time.monotonic()
            try:
                await self.refresh_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.state = {
                    **self.state,
                    "service": {"status": "degraded", "poll_seconds": self.poll_seconds},
                }
                self._log("error", "Unexpected monitor error; retrying after the next poll interval.")
                await self._publish()
            timeout = max(0.1, self.poll_seconds - (time.monotonic() - cycle_started))
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=timeout)
            except TimeoutError:
                pass
        self.state = {**self.state, "service": {"status": "stopped", "poll_seconds": self.poll_seconds}}
        await self._publish()

    async def refresh_once(self) -> None:
        async with self._refresh_lock:
            try:
                page = await self.jupiter.alist_sports_events(
                    filter_name="live",
                    limit=50,
                    tag="soccer",
                )
                scores = (
                    await self.jupiter.aget_live_scores(
                        tuple(event.event_id for event in page.events),
                    )
                    if page.events
                    else ()
                )
            except JupiterDataError as exc:
                current = dict(self.state["jupiter"])
                current.update(status="error", last_error=str(exc))
                self.state = {
                    **self.state,
                    "service": {"status": "degraded", "poll_seconds": self.poll_seconds},
                    "jupiter": current,
                }
                self._log("error", f"Jupiter feed failed: {exc}")
                await self._publish()
                return

            fetched_at = datetime.now(UTC).isoformat()
            score_by_id = {score.event_id: score for score in scores}
            visible_events, suspended_ids = _exclude_suspended_events(page.events, scores)
            visible_event_ids = {event.event_id for event in visible_events}
            visible_score_by_id = {
                event_id: score for event_id, score in score_by_id.items()
                if event_id in visible_event_ids
            }
            self._last_score_by_id = visible_score_by_id
            if self.selected_event_id in suspended_ids:
                self._log("info", f"Stopped monitoring suspended match {self.selected_event_id}.")
                self.selected_event_id = None
                self.state = {**self.state, "selected_event": None}
            event_rows = [
                {
                    "event_id": event.event_id,
                    "title": event.title,
                    "category": event.category,
                    "subcategory": event.subcategory,
                    "scheduled_start_at": _iso(event.scheduled_start_at),
                    "volume_usd": _decimal(event.reported_volume_usd),
                    "score": visible_score_by_id.get(event.event_id).score if event.event_id in visible_score_by_id else None,
                    "home_team": visible_score_by_id.get(event.event_id).home_team if event.event_id in visible_score_by_id else None,
                    "away_team": visible_score_by_id.get(event.event_id).away_team if event.event_id in visible_score_by_id else None,
                    "period": visible_score_by_id.get(event.event_id).period if event.event_id in visible_score_by_id else None,
                    "minute": _minute(visible_score_by_id.get(event.event_id).elapsed) if event.event_id in visible_score_by_id else None,
                    "status": visible_score_by_id.get(event.event_id).status if event.event_id in visible_score_by_id else None,
                    "score_updated_at": visible_score_by_id.get(event.event_id).updated_at if event.event_id in visible_score_by_id else None,
                    "fetched_at": fetched_at,
                }
                for event in visible_events
            ]
            current_jupiter = dict(self.state["jupiter"])
            current_jupiter.update(status="healthy", last_success_at=fetched_at, last_error=None)
            self.state = {
                **self.state,
                "service": {"status": "running", "poll_seconds": self.poll_seconds},
                "jupiter": current_jupiter,
                "events": event_rows,
                "selected_event_id": self.selected_event_id,
            }
            self._log("info", f"Jupiter refresh: {len(event_rows)} live soccer events; suspended matches hidden.")
            self._apply_watchlist_flags()

            if self.selected_event_id and self.selected_event_id in visible_score_by_id:
                await self._refresh_selected(visible_events, visible_score_by_id[self.selected_event_id])
            elif self.selected_event_id:
                self.state = {
                    **self.state,
                    "selected_event": {
                        "event_id": self.selected_event_id,
                        "status": "not_in_live_feed",
                        "error": "Selected event is no longer in Jupiter's live soccer feed.",
                    },
                }
            await self._publish()

    async def _refresh_selected(self, live_events: tuple[JupiterEvent, ...], score: JupiterLiveScore) -> None:
        event_id = self.selected_event_id
        if not event_id:
            return
        try:
            event = await self.jupiter.aget_sports_event_details(event_id)
        except JupiterDataError as exc:
            self._log("error", f"Selected Jupiter event detail failed: {exc}")
            self.state = {
                **self.state,
                "selected_event": {"event_id": event_id, "status": "stale", "error": str(exc)},
            }
            return
        assigned, mapping_reasons = _classify_moneyline(event, score)
        books: dict[str, JupiterOrderBook] = {}
        errors: list[str] = []
        for outcome in ("HOME", "DRAW", "AWAY"):
            market = assigned.get(outcome)
            if not market:
                continue
            try:
                books[market.market_id] = await self.jupiter.aget_orderbook(market.market_id)
            except JupiterDataError as exc:
                errors.append(f"{outcome} orderbook unavailable: {exc}")

        book_views = {market_id: orderbook_view(book) for market_id, book in books.items()}
        try:
            baseline_prices = await asyncio.to_thread(
                self._read_baselines,
                event.event_id,
                [assigned[key].market_id for key in ("HOME", "AWAY") if key in assigned],
                event.scheduled_start_at,
            )
        except Exception:
            baseline_prices = {}
        favorite_baseline = self._choose_prematch_favorite(assigned, baseline_prices)
        market_rows: list[dict[str, Any]] = []
        for outcome in ("HOME", "DRAW", "AWAY"):
            market = assigned.get(outcome)
            if not market:
                continue
            book = book_views.get(market.market_id)
            market_rows.append(
                {
                    "outcome": outcome,
                    "market_id": market.market_id,
                    "title": market.title,
                    "team": market.team_name,
                    "status": market.status,
                    "market_volume_usd": _decimal(market.volume_usd),
                    "api_buy_yes_usd": _decimal(market.buy_yes_usd),
                    "api_sell_yes_usd": _decimal(market.sell_yes_usd),
                    "api_buy_no_usd": _decimal(market.buy_no_usd),
                    "orderbook": book,
                }
            )
        data_status = "healthy" if not errors and not mapping_reasons and len(books) == 3 else "partial"
        volume = event.reported_volume_usd
        volume_gate = {
            "passed": volume is not None and volume >= Decimal("1000000"),
            "value_usd": _decimal(volume),
            "reason": "Jupiter event volume is unavailable or below $1,000,000." if volume is None or volume < Decimal("1000000") else None,
        }
        previous_selected = self.state.get("selected_event") or {}
        cached_statistics = previous_selected.get("statistics")
        selected_view = {
            "event_id": event.event_id,
            "title": event.title,
            "home_team": score.home_team,
            "away_team": score.away_team,
            "score": score.score,
            "status": score.status,
            "period": score.period,
            "minute": _minute(score.elapsed),
            "score_updated_at": score.updated_at,
            "fetched_at": datetime.now(UTC).isoformat(),
            "event_volume_usd": _decimal(volume),
            "volume_gate": volume_gate,
            "moneyline_complete": not mapping_reasons,
            "moneyline_gate_reasons": mapping_reasons,
            "moneyline": market_rows,
            "market_detail_count": len(event.markets),
            "orderbook_status": data_status,
            "orderbook_errors": errors,
            "persistence": "pending",
            "statistics": dict(cached_statistics)
            if previous_selected.get("event_id") == event_id and isinstance(cached_statistics, dict)
            else None,
            "prematch_favorite": favorite_baseline,
        }
        relevant_markets = tuple(assigned.values())
        persist_event = replace(event, markets=relevant_markets)
        orderbook_persistence = {
            market_id: {
                key: (Decimal(value) if value is not None else None)
                for key, value in view.items()
                if key in {
                    "yes_bid", "yes_ask", "yes_ask_depth_usd",
                    "no_bid", "no_ask", "no_ask_depth_usd",
                }
            }
            for market_id, view in book_views.items()
        }
        result = await asyncio.to_thread(
            self.persist,
            persist_event,
            score=score,
            orderbooks=orderbook_persistence,
        )
        selected_view["persistence"] = "saved" if result.persisted else "unavailable"
        selected_view["snapshots_written"] = result.snapshots_written
        if result.persisted:
            selected_view["snapshots_written"] = result.snapshots_written
        else:
            errors.append("Database write failed or migration is not applied.")
            selected_view["orderbook_errors"] = errors
        try:
            mapping = await asyncio.to_thread(self._read_livescore_mapping, event_id)
        except Exception:
            mapping = {"status": "unavailable", "fixture_id": None, "name": None, "verified_at": None}
        cached_statistics = selected_view.get("statistics") or {}
        if cached_statistics.get("status") == "healthy" and cached_statistics.get("match_verified"):
            mapping = {
                "status": "verified",
                "fixture_id": cached_statistics.get("match_id"),
                "name": f"{score.home_team} vs {score.away_team}",
                "verified_at": cached_statistics.get("received_at"),
            }
        selected_view["fixture_mapping"] = mapping
        evaluations, audit_input = self._evaluate_selected(score, selected_view, mapping)
        await self._process_candidate_intents(event_id, selected_view, evaluations)
        selected_view["strategy_evaluations"] = evaluations
        audit_saved, audit_rows = await asyncio.to_thread(
            persist_strategy_audit,
            event_id,
            evaluations,
            audit_input,
        )
        selected_view["strategy_audit"] = "saved" if audit_saved else "unavailable"
        selected_view["strategy_audit_rows"] = audit_rows
        self.state = {**self.state, "selected_event": selected_view}
        self._log(
            "info" if result.persisted else "warning",
            f"Monitored {event.title}: {len(market_rows)} moneyline outcomes; snapshot storage {selected_view['persistence']}.",
        )

    async def _process_candidate_intents(
        self,
        event_id: str,
        selected: dict[str, Any],
        evaluations: list[dict[str, object]],
    ) -> None:
        """Create audit-only tickets for candidates with an exact market mapping."""
        rows = selected.get("moneyline") or []
        tickets: list[ExecutionTicket] = []
        candidate_evaluations = [row for row in evaluations if row.get("status") == "candidate"]
        for evaluation in candidate_evaluations:
            outcome = str(evaluation.get("outcome") or "")
            market_id = evaluation.get("market_id")
            mapped_rows = [
                row for row in rows
                if row.get("outcome") == outcome and row.get("market_id") == market_id
            ]
            if len(mapped_rows) != 1:
                evaluation["execution_intent"] = {
                    "status": "rejected",
                    "reason": "Candidate does not map to exactly one selected Jupiter moneyline market.",
                }
                continue
            row = mapped_rows[0]
            orderbook = row.get("orderbook") or {}
            ask_value = orderbook.get("yes_ask")
            if ask_value is None:
                evaluation["execution_intent"] = {
                    "status": "rejected",
                    "reason": "Selected Jupiter market has no verified YES ask.",
                }
                continue
            try:
                if evaluation.get("ask") is None or Decimal(str(evaluation["ask"])) != Decimal(str(ask_value)):
                    raise ValueError("Candidate ask does not match the selected market's current YES ask.")
                ticket = ExecutionTicket(
                    event_id=event_id,
                    market_id=str(market_id),
                    strategy_name=str(evaluation["strategy_name"]),
                    outcome=outcome,
                    contract_side="YES",
                    ask_price=Decimal(str(ask_value)),
                    size_usd=MINIMUM_ORDER_USD,
                    max_slippage_bps=MAXIMUM_SLIPPAGE_BPS,
                    observed_at=_parse_time(orderbook.get("fetched_at")) or datetime.now(UTC),
                )
                result = await self.broker.process_candidate(ticket)
            except (KeyError, TypeError, ValueError) as exc:
                evaluation["execution_intent"] = {
                    "status": "rejected",
                    "reason": str(exc),
                }
                continue
            evaluation["execution_intent"] = {
                "status": result.status,
                "reason": result.reason,
                "audit_status": "pending",
            }
            tickets.append(ticket)

        if tickets:
            saved, count = await asyncio.to_thread(persist_execution_intents, event_id, tickets)
            audit_status = "saved" if saved else "unavailable"
            for evaluation in candidate_evaluations:
                intent = evaluation.get("execution_intent")
                if isinstance(intent, dict) and intent.get("status") == "disabled":
                    intent["audit_status"] = audit_status
                    intent["audit_rows_written"] = count if saved else 0
        selected["execution_intents"] = [
            {
                "strategy_name": str(evaluation.get("strategy_name")),
                "outcome": str(evaluation.get("outcome")),
                **(evaluation.get("execution_intent") or {}),
            }
            for evaluation in candidate_evaluations
        ]

    def _evaluate_selected(
        self,
        score: JupiterLiveScore,
        selected: dict[str, Any],
        mapping: dict[str, object],
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        markets: dict[str, MarketQuote] = {}
        for row in selected["moneyline"]:
            book = row.get("orderbook") or {}
            asks = tuple(
                AskLevel(price=Decimal(level["price_usd"]), quantity=Decimal(level["quantity"]))
                for level in book.get("yes_asks", [])
            )
            markets[row["outcome"]] = MarketQuote(
                market_id=row["market_id"],
                bid=Decimal(book["yes_bid"]) if book.get("yes_bid") is not None else None,
                ask=Decimal(book["yes_ask"]) if book.get("yes_ask") is not None else None,
                ask_depth_usd=(
                    Decimal(book["yes_ask_depth_usd"])
                    if book.get("yes_ask_depth_usd") is not None else None
                ),
                asks=asks,
                observed_at=_parse_time(book.get("fetched_at")),
            )
        score_pair = re.fullmatch(r"\s*(\d+)\s*[-:]\s*(\d+)\s*", score.score or "")
        home_score = int(score_pair.group(1)) if score_pair else None
        away_score = int(score_pair.group(2)) if score_pair else None
        stats = selected.get("statistics") or {}
        mapping_verified = mapping.get("status") == "verified" and stats.get("match_verified") is True
        stats_score = re.fullmatch(r"\s*(\d+)\s*[-:]\s*(\d+)\s*", stats.get("score") or "")
        score_consistent = bool(
            mapping_verified and stats_score and home_score is not None and away_score is not None
            and int(stats_score.group(1)) == home_score and int(stats_score.group(2)) == away_score
        )
        stats["score_consistent"] = score_consistent
        selected["score_consistent"] = score_consistent
        context = MatchInputs(
            event_id=selected["event_id"],
            status=score.period or score.status or "UNKNOWN",
            minute=selected.get("minute"),
            home_score=home_score,
            away_score=away_score,
            event_volume_usd=Decimal(selected["event_volume_usd"]) if selected.get("event_volume_usd") else None,
            event_volume_verified=selected.get("event_volume_usd") is not None,
            event_observed_at=_parse_time(self.state.get("jupiter", {}).get("last_success_at")),
            score_observed_at=_parse_time(self.state.get("jupiter", {}).get("last_success_at")),
            score_updated_at=_parse_time(score.updated_at),
            stats_mapped_and_verified=mapping_verified and stats.get("status") == "healthy",
            stats_observed_at=_parse_time(stats.get("received_at")),
            home_shots=stats.get("home_shots"),
            away_shots=stats.get("away_shots"),
            home_possession=Decimal(str(stats["home_possession"])) if stats.get("home_possession") is not None else None,
            away_possession=Decimal(str(stats["away_possession"])) if stats.get("away_possession") is not None else None,
            home_corners=stats.get("home_corners"),
            away_corners=stats.get("away_corners"),
            score_consistent=score_consistent,
            markets=markets,
            prematch_favorite=(
                selected.get("prematch_favorite", {}).get("outcome")
                if selected.get("prematch_favorite") else None
            ),
            prematch_favorite_probability=(
                Decimal(selected["prematch_favorite"]["probability"])
                if selected.get("prematch_favorite") else None
            ),
            prematch_source=(
                selected.get("prematch_favorite", {}).get("source")
                if selected.get("prematch_favorite") else None
            ),
            prematch_observed_at=_parse_time(
                selected.get("prematch_favorite", {}).get("observed_at")
                if selected.get("prematch_favorite") else None
            ),
        )
        config = CandidateConfig()
        results = evaluate_live_match(context, config=config)
        selected["data_gates"] = results[0]["gate_results"] if results else {}
        audit = {
            "jupiter_event_id": selected["event_id"],
            "livescore_mcp_match_id": str(mapping.get("fixture_id")) if mapping_verified else None,
            "mapping_status": mapping.get("status"),
            "prematch_favorite": selected.get("prematch_favorite"),
            "observed_at": datetime.now(UTC).isoformat(),
            "source_timestamps": {
                "event_list_received_at": self.state.get("jupiter", {}).get("last_success_at"),
                "score_updated_at": score.updated_at,
                "livescore_mcp_statistics_received_at": stats.get("received_at"),
                "prematch_favorite_observed_at": (
                    selected.get("prematch_favorite", {}).get("observed_at")
                    if selected.get("prematch_favorite") else None
                ),
                "orderbooks": {
                    key: value.observed_at.isoformat() if value.observed_at else None
                    for key, value in markets.items()
                },
            },
            "score": {"home": home_score, "away": away_score, "period": context.status, "minute": context.minute},
            "event_volume_usd": str(context.event_volume_usd) if context.event_volume_usd is not None else None,
            "market_quotes": {
                key: {
                    "market_id": value.market_id,
                    "bid": str(value.bid) if value.bid is not None else None,
                    "ask": str(value.ask) if value.ask is not None else None,
                    "ask_depth_usd": str(value.ask_depth_usd) if value.ask_depth_usd is not None else None,
                }
                for key, value in markets.items()
            },
            "stats": {
                "home_shots": context.home_shots,
                "away_shots": context.away_shots,
                "home_possession": str(context.home_possession) if context.home_possession is not None else None,
                "away_possession": str(context.away_possession) if context.away_possession is not None else None,
                "home_corners": context.home_corners,
                "away_corners": context.away_corners,
            },
            "configuration": {
                "version": "provisional-v1",
                "max_data_age_seconds": config.max_data_age_seconds,
                "prematch_max_age_seconds": config.prematch_max_age_seconds,
                "max_slippage_bps": str(config.max_slippage_bps),
                "minimum_order_value_usd_provisional": str(config.min_order_value_usd),
                "corner_threshold_provisional": config.corner_threshold,
            },
        }
        return results, audit

    @staticmethod
    def _read_livescore_mapping(event_id: str) -> dict[str, object]:
        with Session(get_engine()) as session:
            return livescore_mcp_mapping_status(session, event_id)

    @staticmethod
    def _read_baselines(
        event_id: str,
        market_ids: list[str],
        scheduled_start_at: datetime | None,
    ) -> dict[str, tuple[Decimal, datetime]]:
        with Session(get_engine()) as session:
            return read_prematch_yes_prices(
                session,
                event_provider_id=event_id,
                market_provider_ids=market_ids,
                scheduled_start_at=scheduled_start_at,
            )

    @staticmethod
    def _choose_prematch_favorite(
        assigned: dict[str, JupiterMarket],
        baselines: dict[str, tuple[Decimal, datetime]],
    ) -> dict[str, Any] | None:
        choices = [
            (outcome, baselines[market.market_id])
            for outcome in ("HOME", "AWAY")
            if (market := assigned.get(outcome)) is not None and market.market_id in baselines
        ]
        if not choices:
            return None
        outcome, (probability, observed_at) = max(choices, key=lambda row: row[1][0])
        return {
            "outcome": outcome,
            "probability": _decimal(probability),
            "source": "Jupiter Prediction API prematch YES ask",
            "observed_at": _iso(observed_at),
        }

    async def _run_upcoming_radar(self) -> None:
        """Refresh the lower-priority upcoming feed independently from live monitoring."""
        while not self._stopping.is_set():
            cycle_started = time.monotonic()
            try:
                await self._refresh_upcoming_radar_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                radar = dict(self.state.get("upcoming_radar", {}))
                radar.update(
                    status="stale" if radar.get("last_success_at") else "error",
                    last_error="Unexpected error while refreshing upcoming matches.",
                )
                self.state = {**self.state, "upcoming_radar": radar}
                self._log("warning", "Upcoming radar refresh failed unexpectedly; the last good data is retained.")
                await self._publish()
            finally:
                self._upcoming_initial_scan.set()
            delay = max(0.1, self.prematch_refresh_seconds - (time.monotonic() - cycle_started))
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=delay)
            except TimeoutError:
                pass

    async def _refresh_upcoming_radar_once(self) -> None:
        now = datetime.now(UTC)
        events: dict[str, JupiterEvent] = {}
        try:
            # At most 100 events per scan, keeping the radar within a fixed request budget.
            for start in (0, 50):
                page = await self.jupiter.alist_sports_events(
                    filter_name="upcoming", limit=50, start=start, tag="soccer",
                    include_markets=True, sort_by="volume", sort_direction="desc",
                    priority=JUPITER_PRIORITY_RADAR,
                )
                for event in page.events:
                    events[event.event_id] = event
                if not page.has_next or len(page.events) < 50:
                    break
        except JupiterDataError as exc:
            radar = dict(self.state.get("upcoming_radar", {}))
            radar.update(status="stale" if radar.get("last_success_at") else "error", last_error=str(exc))
            self.state = {**self.state, "upcoming_radar": radar}
            self._log("warning", f"Upcoming radar refresh failed: {exc}")
            await self._publish()
            return

        previous = self._previous_upcoming_volumes
        rows: list[dict[str, Any]] = []
        next_volumes: dict[str, Decimal] = {}
        stored = unavailable = 0
        baseline_cutoff = now + timedelta(hours=48)
        for event in events.values():
            start_at = event.scheduled_start_at
            if start_at is None or not now < start_at <= baseline_cutoff:
                continue
            if not any(market.sports_market_type == "moneyline" for market in event.markets):
                continue
            result = await asyncio.to_thread(persist_prematch_event, event)
            if result.persisted:
                stored += result.snapshots_written
            else:
                unavailable += 1
        for event in events.values():
            start_at = event.scheduled_start_at
            if start_at is None or start_at <= now:
                continue
            volume = event.reported_volume_usd
            if volume is not None:
                next_volumes[event.event_id] = volume
            if volume is None or volume < UPCOMING_MIN_VOLUME_USD:
                continue
            team_markets = [
                market for market in event.markets
                if market.sports_market_type == "moneyline" and market.team_name
                and market.title.strip().casefold() not in {"draw", "tie", "x"}
            ]
            draw_markets = [
                market for market in event.markets
                if market.sports_market_type == "moneyline"
                and (market.title.strip().casefold() in {"draw", "tie", "x"}
                     or (market.team_name or "").strip().casefold() in {"draw", "tie", "x"})
            ]
            priced_teams = [m for m in team_markets if m.buy_yes_usd is not None]
            favorite = max(priced_teams, key=lambda market: market.buy_yes_usd) if priced_teams else None
            draw = max((m for m in draw_markets if m.buy_yes_usd is not None),
                       key=lambda market: market.buy_yes_usd, default=None)
            assignments, _, home_team, away_team = _classify_upcoming_moneyline(event)
            home_market, away_market = assignments.get("HOME"), assignments.get("AWAY")
            delta = volume - previous[event.event_id] if volume is not None and event.event_id in previous else None
            rows.append({
                "event_id": event.event_id, "title": event.title,
                "scheduled_start_at": _iso(start_at), "volume_usd": _decimal(volume),
                "volume_delta_usd": _decimal(delta),
                "home_team": home_team, "home_price": _decimal(home_market.buy_yes_usd) if home_market else None,
                "away_team": away_team, "away_price": _decimal(away_market.buy_yes_usd) if away_market else None,
                "favorite_team": favorite.team_name if favorite else None,
                "favorite_price": _decimal(favorite.buy_yes_usd) if favorite else None,
                "draw_price": _decimal(draw.buy_yes_usd) if draw else None,
                "strategy_1_may_apply": bool(favorite and favorite.buy_yes_usd >= Decimal("0.75")),
                "volume_gate_met_at_observation": bool(volume is not None and volume >= Decimal("1000000")),
            })
        rows.sort(key=lambda row: (-Decimal(row["volume_usd"] or "0"), row["scheduled_start_at"] or ""))
        self._previous_upcoming_volumes = next_volumes
        watched = {item.get("event_id") for item in self.state.get("watchlist", [])}
        rows = [{**row, "watched": row["event_id"] in watched} for row in rows]
        success_at = now.isoformat()
        radar_status = "saved" if stored else "unavailable" if unavailable else "healthy"
        self._upcoming_event_cache = {
            event.event_id: event for event in events.values()
            if event.scheduled_start_at is not None and event.scheduled_start_at > now
        }
        self.state = {
            **self.state,
            "upcoming_matches": rows,
            "upcoming_radar": {
                "status": "healthy", "last_success_at": success_at, "last_error": None,
                "refresh_seconds": self.prematch_refresh_seconds,
                "events_seen": len(events), "page_cap": 100,
            },
            "prematch_baselines": {
                "status": radar_status, "last_capture_at": success_at,
                "events_seen": len(events), "snapshot_rows_written": stored,
            },
        }
        selected_upcoming = self.state.get("selected_upcoming_event") or {}
        selected_upcoming_id = selected_upcoming.get("event_id")
        if selected_upcoming_id:
            refreshed_event = self._upcoming_event_cache.get(selected_upcoming_id)
            if refreshed_event is not None:
                self.state = {
                    **self.state,
                    "selected_upcoming_event": self._upcoming_detail_view(refreshed_event),
                }
            else:
                self.state = {
                    **self.state,
                    "selected_upcoming_event": {
                        **selected_upcoming, "status": "stale",
                        "error": "Kickoff passed or Jupiter no longer returns this event as upcoming.",
                    },
                }
        self._apply_watchlist_flags()
        self._log(
            "info",
            f"Upcoming radar refresh: {len(rows)} future matches with event volume at least US$100,000; {len(events)} events scanned.",
        )
        await self._publish()
