"""On-demand, read-only LiveScore MCP client for one selected football match."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
import json
import asyncio
import os
import re
from typing import Any
import unicodedata

import requests
import httpx


DEFAULT_ENDPOINT = "https://livescoremcp.com/mcp"
PROTOCOL_VERSION = "2025-11-25"


class LiveScoreMCPError(RuntimeError):
    """Safe provider error without response bodies or request details."""


@dataclass(frozen=True)
class MatchStatistics:
    match_id: str
    home_team: str
    away_team: str
    score: str | None
    score_consistent: bool
    status: str | None
    minute: int | None
    home_shots: int | None
    away_shots: int | None
    home_shots_on_target: int | None
    away_shots_on_target: int | None
    home_possession: float | None
    away_possession: float | None
    home_passes: int | None
    away_passes: int | None
    home_pass_accuracy: float | None
    away_pass_accuracy: float | None
    home_fouls: int | None
    away_fouls: int | None
    home_yellow_cards: int | None
    away_yellow_cards: int | None
    home_red_cards: int | None
    away_red_cards: int | None
    home_offsides: int | None
    away_offsides: int | None
    home_corners: int | None
    away_corners: int | None
    received_at: datetime

    @property
    def has_statistics(self) -> bool:
        return any(
            value is not None
            for value in (
                self.home_shots, self.away_shots,
                self.home_shots_on_target, self.away_shots_on_target,
                self.home_possession, self.away_possession,
                self.home_passes, self.away_passes,
                self.home_pass_accuracy, self.away_pass_accuracy,
                self.home_fouls, self.away_fouls,
                self.home_yellow_cards, self.away_yellow_cards,
                self.home_red_cards, self.away_red_cards,
                self.home_offsides, self.away_offsides,
                self.home_corners, self.away_corners,
            )
        )


def _score(value: Any) -> str | None:
    if isinstance(value, dict):
        home = value.get("localteam") or value.get("home")
        away = value.get("visitorteam") or value.get("away")
        if home is not None and away is not None:
            home = home.get("goals") if isinstance(home, dict) else home
            away = away.get("goals") if isinstance(away, dict) else away
            return f"{home}-{away}"
    if not isinstance(value, (str, int, float)):
        return None
    text = str(value).strip()
    match = re.fullmatch(r"(\d+)\s*[-:]\s*(\d+)", text)
    return f"{match.group(1)}-{match.group(2)}" if match else None


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).strip().removesuffix("%"))
    except (TypeError, ValueError):
        return None


def _team_name(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("name") or value.get("team") or value.get("title")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _team_key(value: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    tokens = re.sub(r"[^a-z0-9]+", " ", ascii_name.casefold()).split()
    while tokens and tokens[0] in {"fc", "afc"}:
        tokens.pop(0)
    while tokens and tokens[-1] in {"fc", "cf", "sc", "afc", "cfc", "club"}:
        tokens.pop()
    normalized = " ".join(tokens)
    aliases = {
        "man utd": "manchester united", "man united": "manchester united",
        "manchester utd": "manchester united", "manchester united": "manchester united",
        "man city": "manchester city", "manchester city": "manchester city",
        "spurs": "tottenham hotspur", "tottenham": "tottenham hotspur",
        "nottm forest": "nottingham forest", "nottingham forest": "nottingham forest",
        "wolves": "wolverhampton wanderers", "wolverhampton": "wolverhampton wanderers",
        "west ham": "west ham united", "newcastle": "newcastle united",
        "brighton": "brighton and hove albion", "brighton hove albion": "brighton and hove albion",
        "leicester": "leicester city",
        "newcastle utd": "newcastle united",
        "bvb": "borussia dortmund", "bvb dortmund": "borussia dortmund",
        "borussia dortmund": "borussia dortmund",
        "psg": "paris saint germain", "paris sg": "paris saint germain",
        "paris saint germain": "paris saint germain", "inter": "inter milan",
        "internazionale": "inter milan", "inter milan": "inter milan",
        "bayern munchen": "bayern munich", "bayern munich": "bayern munich",
        "atletico madrid": "atletico madrid", "athletic bilbao": "athletic bilbao",
    }
    return aliases.get(normalized, normalized)


def same_team_name(left: str, right: str) -> bool:
    return _team_key(left) == _team_key(right)


def _pass_accuracy(accurate: int | None, total: int | None) -> float | None:
    if accurate is None or total is None or total <= 0 or accurate < 0 or accurate > total:
        return None
    return round(accurate * 100 / total, 1)


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _live_match_rows(value: Any) -> list[dict[str, Any]]:
    rows = []
    seen: set[tuple[str, str, str]] = set()
    for item in _walk_dicts(value):
        home = _team_name(item.get("localteam") or item.get("homeTeam") or item.get("home"))
        away = _team_name(item.get("visitorteam") or item.get("awayTeam") or item.get("away"))
        match_id = item.get("id") or item.get("match_id") or item.get("matchId")
        score = _score(item.get("scoretime") or item.get("score") or item.get("result"))
        if home and away and match_id is not None:
            key = (str(match_id), home.casefold(), away.casefold())
            if key not in seen:
                seen.add(key)
                rows.append({"id": str(match_id), "home": home, "away": away, "score": score, "raw": item})
    return rows


def _match_detail_from_text(value: str) -> dict[str, Any] | None:
    """Normalize LiveScore's compact match report into the raw-detail shape."""
    lines = value.splitlines()
    if not lines:
        return None
    header = re.match(
        r"^(.+?)\s+((?:\d+)\s*[-:]\s*(?:\d+)|vs)\s+(.+?)\s+·\s+(.+)$",
        lines[0].strip(),
        re.IGNORECASE,
    )
    if not header:
        return None
    home_name, score_text, away_name, status = (part.strip() for part in header.groups())
    home_stats: dict[str, str] = {}
    away_stats: dict[str, str] = {}
    statistic_fields = {
        "possession": "possestiontime",
        "shots": "shotstotal",
        "shots on target": "shotsgoal",
        "corners": "corners",
        "fouls": "fouls",
        "offsides": "offsides",
        "yellow cards": "yellowcards",
        "red cards": "redcards",
        "passes": "passestotal",
        "accurate passes": "passesaccurate",
    }
    for line in lines:
        match = re.match(r"^\s*-\s*([^:]+):\s*(.*?)\s+-\s+(.*?)\s*$", line)
        if not match:
            continue
        label, home_value, away_value = match.groups()
        field = statistic_fields.get(label.strip().casefold())
        if field:
            home_stats[field] = home_value.strip()
            away_stats[field] = away_value.strip()
    return {
        "localteam": home_name,
        "visitorteam": away_name,
        "scoretime": _score(score_text),
        "status": status,
        "commentaries": {"stats": {"localteam": home_stats, "visitorteam": away_stats}},
    }


def _decode_tool_result(result: dict[str, Any]) -> Any:
    if result.get("isError"):
        raise LiveScoreMCPError("LiveScore MCP could not complete the requested read-only tool call.")
    structured = result.get("structuredContent")
    if isinstance(structured, (dict, list)):
        return structured
    for block in result.get("content", []):
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text", "")
        if isinstance(text, str) and text:
            # Some deployed MCP tools JSON-encode their payload, then return
            # that JSON document as a JSON string in the text content. Decode
            # the outer string as well as the document, with a small bound so
            # malformed or adversarial content cannot cause unbounded work.
            decoded: Any = text
            for _ in range(3):
                if not isinstance(decoded, str):
                    return decoded
                try:
                    decoded = json.loads(decoded)
                except json.JSONDecodeError:
                    # LiveScore's raw feed can contain literal control
                    # characters (usually line breaks) inside string values.
                    # Repair only those characters, then retry strict JSON
                    # parsing; don't attempt to infer or rebuild missing data.
                    repaired: list[str] = []
                    in_string = False
                    escaped = False
                    for char in decoded:
                        codepoint = ord(char)
                        if in_string and codepoint < 0x20:
                            repaired.append(f"\\u{codepoint:04x}")
                            continue
                        repaired.append(char)
                        if escaped:
                            escaped = False
                        elif char == "\\" and in_string:
                            escaped = True
                        elif char == '"':
                            in_string = not in_string
                    try:
                        decoded = json.loads("".join(repaired))
                    except (TypeError, ValueError):
                        return decoded
                except (TypeError, ValueError):
                    return decoded
            return decoded
    raise LiveScoreMCPError("LiveScore MCP returned an unsupported tool response format.")


class LiveScoreMCPClient:
    """Small stateless MCP Streamable HTTP client; no authentication or write tools."""

    def __init__(
        self,
        endpoint: str | None = None,
        *,
        session: requests.Session | None = None,
        async_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 12.0,
    ) -> None:
        self.endpoint = (endpoint or os.getenv("LIVESCORE_MCP_URL") or DEFAULT_ENDPOINT).strip()
        if not self.endpoint.startswith("https://"):
            raise ValueError("LiveScore MCP endpoint must use HTTPS.")
        self._session = session or requests.Session()
        self._request_id = 0
        self._async_client = async_client
        self._owns_async_client = async_client is None
        self._async_request_id = 0
        self._request_lock = asyncio.Lock()
        self._timeout_seconds = timeout_seconds

    async def open(self) -> None:
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(timeout=self._timeout_seconds)

    async def close(self) -> None:
        if self._owns_async_client and self._async_client is not None:
            await self._async_client.aclose()
            self._async_client = None

    async def _apost(self, payload: dict[str, Any], session_id: str | None = None) -> tuple[Any, str | None]:
        if self._async_client is None:
            raise LiveScoreMCPError("LiveScore MCP async client is not started.")
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        for attempt in range(3):
            try:
                response = await self._async_client.post(
                    self.endpoint, headers=headers, json=payload,
                )
            except httpx.RequestError:
                if attempt == 2:
                    raise LiveScoreMCPError("LiveScore MCP could not be reached. Check network access and try again.") from None
                await asyncio.sleep(min(2 ** (attempt + 1), 8))
                continue
            if response.status_code == 429:
                raise LiveScoreMCPError("LiveScore MCP rate limit reached. Wait before requesting another refresh.")
            if 500 <= response.status_code < 600 and attempt < 2:
                await asyncio.sleep(min(2 ** (attempt + 1), 8))
                continue
            if not response.is_success and response.status_code != 202:
                raise LiveScoreMCPError(f"LiveScore MCP returned HTTP {response.status_code}.")
            new_session_id = response.headers.get("Mcp-Session-Id") or session_id
            if response.status_code == 202 or not response.content:
                return None, new_session_id
            try:
                if "text/event-stream" in response.headers.get("content-type", ""):
                    data = next((line[5:].strip() for line in response.text.splitlines() if line.startswith("data:")), "")
                    message = json.loads(data) if data else None
                else:
                    message = response.json()
            except (ValueError, AttributeError):
                raise LiveScoreMCPError("LiveScore MCP returned invalid JSON-RPC data.") from None
            if not isinstance(message, dict):
                raise LiveScoreMCPError("LiveScore MCP returned an invalid JSON-RPC envelope.")
            if "error" in message:
                raise LiveScoreMCPError("LiveScore MCP rejected the read-only request.")
            return message.get("result"), new_session_id
        raise LiveScoreMCPError("LiveScore MCP request failed. Try again later.")

    async def _anext_id(self) -> int:
        async with self._request_lock:
            self._async_request_id += 1
            return self._async_request_id

    async def _atool(self, name: str, arguments: dict[str, Any], session_id: str | None) -> tuple[Any, str | None]:
        result, session_id = await self._apost({
            "jsonrpc": "2.0", "id": await self._anext_id(), "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }, session_id)
        if not isinstance(result, dict):
            raise LiveScoreMCPError("LiveScore MCP returned an empty tool result.")
        return _decode_tool_result(result), session_id

    async def _ainitialize(self) -> str | None:
        result, session_id = await self._apost({
            "jsonrpc": "2.0", "id": await self._anext_id(), "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                       "clientInfo": {"name": "prediction-market-agent", "version": "0.1.0"}},
        })
        if not isinstance(result, dict) or not isinstance(result.get("protocolVersion"), str):
            raise LiveScoreMCPError("LiveScore MCP did not complete the MCP initialization handshake.")
        await self._apost({"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id)
        return session_id

    async def aget_match_statistics(self, *, home_team: str, away_team: str, score: str) -> MatchStatistics:
        """Async version for the background monitor; resolves one exact selected match only."""
        expected_score = _score(score)
        if not expected_score or not home_team.strip() or not away_team.strip():
            raise ValueError("Exact Jupiter team names and a parseable score are required.")
        session_id = await self._ainitialize()
        live_feed, session_id = await self._atool("get_live_scores", {"format": "text"}, session_id)
        candidates = [row for row in _live_match_rows(live_feed)
                      if same_team_name(row["home"], home_team) and same_team_name(row["away"], away_team)]
        exact = [row for row in candidates if row["score"] == expected_score]
        if len(exact) == 1:
            match_row = exact[0]
        elif len(exact) > 1:
            raise LiveScoreMCPError("More than one LiveScore match matched Jupiter; match identity is ambiguous.")
        elif len(candidates) == 1:
            match_row = candidates[0]
        elif len(candidates) > 1:
            raise LiveScoreMCPError("More than one LiveScore match matched Jupiter; match identity is ambiguous.")
        else:
            live_rows = _live_match_rows(live_feed)
            query_home, query_away = _team_key(home_team), _team_key(away_team)
            closest = sorted(
                (((SequenceMatcher(None, query_home, _team_key(row["home"])).ratio()
                   + SequenceMatcher(None, query_away, _team_key(row["away"])).ratio()) / 2, row)
                 for row in live_rows),
                key=lambda item: item[0], reverse=True,
            )
            suggestions = [f"{row['home']} vs {row['away']}" for ratio, row in closest[:2] if ratio >= 0.45]
            suffix = (" Closest provider names: " + "; ".join(suggestions) + "."
                      if suggestions else
                      f" MCP returned {len(live_rows)} parseable live match(es); check spelling or provider coverage.")
            raise LiveScoreMCPError("No LiveScore match has the same home and away teams as Jupiter." + suffix)
        details, _ = await self._atool("get_match", {"id": match_row["id"], "h2h": False, "format": "text"}, session_id)
        if isinstance(details, str):
            details = _match_detail_from_text(details)
        match = next((item for item in _walk_dicts(details) if str(item.get("id", "")) == match_row["id"]),
                     details if isinstance(details, dict) else None)
        if not isinstance(match, dict):
            raise LiveScoreMCPError("LiveScore MCP returned no details for the selected match.")
        detail_home, detail_away = _team_name(match.get("localteam")), _team_name(match.get("visitorteam"))
        detail_score = _score(match.get("scoretime") or match.get("score"))
        if (not detail_home or not detail_away or not same_team_name(detail_home, home_team)
                or not same_team_name(detail_away, away_team)):
            raise LiveScoreMCPError("Match details do not agree with Jupiter's home/away teams; statistics were rejected.")
        commentaries = match.get("commentaries") if isinstance(match.get("commentaries"), dict) else {}
        stats = commentaries.get("stats") if isinstance(commentaries.get("stats"), dict) else {}
        home = stats.get("localteam") if isinstance(stats.get("localteam"), dict) else {}
        away = stats.get("visitorteam") if isinstance(stats.get("visitorteam"), dict) else {}
        hp, ap = _int(home.get("passestotal")), _int(away.get("passestotal"))
        return MatchStatistics(
            match_id=match_row["id"], home_team=detail_home, away_team=detail_away,
            score=detail_score, score_consistent=detail_score == expected_score,
            status=str(match.get("status")) if match.get("status") is not None else None,
            minute=_int(match.get("minute") or match.get("elapsed") or match.get("time")),
            home_shots=_int(home.get("shotstotal")), away_shots=_int(away.get("shotstotal")),
            home_shots_on_target=_int(home.get("shotsgoal")), away_shots_on_target=_int(away.get("shotsgoal")),
            home_possession=_float(home.get("possestiontime")), away_possession=_float(away.get("possestiontime")),
            home_passes=hp, away_passes=ap,
            home_pass_accuracy=_pass_accuracy(_int(home.get("passesaccurate")), hp),
            away_pass_accuracy=_pass_accuracy(_int(away.get("passesaccurate")), ap),
            home_fouls=_int(home.get("fouls")), away_fouls=_int(away.get("fouls")),
            home_yellow_cards=_int(home.get("yellowcards")), away_yellow_cards=_int(away.get("yellowcards")),
            home_red_cards=_int(home.get("redcards")), away_red_cards=_int(away.get("redcards")),
            home_offsides=_int(home.get("offsides")), away_offsides=_int(away.get("offsides")),
            home_corners=_int(home.get("corners")), away_corners=_int(away.get("corners")), received_at=datetime.now(UTC),
        )
        self._request_id = 0

    def _post(self, payload: dict[str, Any], session_id: str | None = None) -> tuple[Any, str | None]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        try:
            response = self._session.post(
                self.endpoint,
                headers=headers,
                json=payload,
                timeout=self._timeout_seconds,
            )
        except requests.RequestException:
            raise LiveScoreMCPError("LiveScore MCP could not be reached. Check network access and try again.") from None
        if response.status_code == 429:
            raise LiveScoreMCPError("LiveScore MCP rate limit reached. Wait before requesting another refresh.")
        if not response.ok and response.status_code != 202:
            raise LiveScoreMCPError(f"LiveScore MCP returned HTTP {response.status_code}.")
        new_session_id = response.headers.get("Mcp-Session-Id") or session_id
        if response.status_code == 202 or not response.content:
            return None, new_session_id
        try:
            if "text/event-stream" in response.headers.get("content-type", ""):
                data = next(
                    (line[5:].strip() for line in response.text.splitlines() if line.startswith("data:")),
                    "",
                )
                message = json.loads(data) if data else None
            else:
                message = response.json()
        except (ValueError, AttributeError):
            raise LiveScoreMCPError("LiveScore MCP returned invalid JSON-RPC data.") from None
        if not isinstance(message, dict):
            raise LiveScoreMCPError("LiveScore MCP returned an invalid JSON-RPC envelope.")
        if "error" in message:
            raise LiveScoreMCPError("LiveScore MCP rejected the read-only request.")
        return message.get("result"), new_session_id

    def _tool(self, name: str, arguments: dict[str, Any], session_id: str | None) -> tuple[Any, str | None]:
        self._request_id += 1
        result, session_id = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            session_id,
        )
        if not isinstance(result, dict):
            raise LiveScoreMCPError("LiveScore MCP returned an empty tool result.")
        return _decode_tool_result(result), session_id

    def _initialize(self) -> str | None:
        self._request_id += 1
        result, session_id = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "prediction-market-agent", "version": "0.1.0"},
                },
            }
        )
        if not isinstance(result, dict) or not isinstance(result.get("protocolVersion"), str):
            raise LiveScoreMCPError("LiveScore MCP did not complete the MCP initialization handshake.")
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id)
        return session_id

    def check_connection(self) -> bool:
        """Run the server's harmless echo tool to verify the MCP connection."""
        session_id = self._initialize()
        result, _ = self._tool(
            "health", {"message": "prediction-market-agent connectivity check"}, session_id,
        )
        if not isinstance(result, str) or not result.startswith("ok:"):
            raise LiveScoreMCPError("LiveScore MCP health tool returned an unexpected response.")
        return True

    def get_match_statistics(
        self,
        *,
        home_team: str,
        away_team: str,
        score: str,
    ) -> MatchStatistics:
        """Find one exact live match, fetch only its detail, and normalize available stats."""
        expected_score = _score(score)
        if not expected_score or not home_team.strip() or not away_team.strip():
            raise ValueError("Exact Jupiter team names and a parseable score are required.")
        session_id = self._initialize()
        # Raw JSON is capped at 60,000 characters by the provider and the
        # worldwide feed can exceed that, yielding invalid truncated JSON.
        # The default/"text" response includes structuredContent with the
        # complete bounded match list, which _decode_tool_result prefers.
        live_feed, session_id = self._tool("get_live_scores", {"format": "text"}, session_id)
        team_candidates = [
            row for row in _live_match_rows(live_feed)
            if same_team_name(row["home"], home_team)
            and same_team_name(row["away"], away_team)
        ]
        exact_score_candidates = [row for row in team_candidates if row["score"] == expected_score]
        if len(exact_score_candidates) == 1:
            match_row = exact_score_candidates[0]
        elif len(exact_score_candidates) > 1:
            raise LiveScoreMCPError("More than one LiveScore match matched Jupiter; match identity is ambiguous.")
        elif len(team_candidates) == 1:
            # The score is a consistency gate, not an identity key: score feeds can lag.
            match_row = team_candidates[0]
        elif not team_candidates:
            live_rows = _live_match_rows(live_feed)
            query_home, query_away = _team_key(home_team), _team_key(away_team)
            closest = sorted(
                (
                    (
                        (SequenceMatcher(None, query_home, _team_key(row["home"])).ratio()
                         + SequenceMatcher(None, query_away, _team_key(row["away"])).ratio()) / 2,
                        row,
                    )
                    for row in live_rows
                ),
                key=lambda item: item[0],
                reverse=True,
            )
            suggestions = [
                f"{row['home']} vs {row['away']}"
                for ratio, row in closest[:2]
                if ratio >= 0.45
            ]
            suffix = (
                " Closest provider names: " + "; ".join(suggestions) + "."
                if suggestions else
                f" MCP returned {len(live_rows)} parseable live match(es); check spelling or provider coverage."
            )
            raise LiveScoreMCPError("No LiveScore match has the same home and away teams as Jupiter." + suffix)
        else:
            raise LiveScoreMCPError("More than one LiveScore match matched Jupiter; match identity is ambiguous.")
        details, _ = self._tool(
            "get_match",
            # Match JSON can exceed the same 60k provider cap as the live
            # feed; the compact text response includes identity and stats.
            {"id": match_row["id"], "h2h": False, "format": "text"},
            session_id,
        )
        if isinstance(details, str):
            details = _match_detail_from_text(details)
        match = next(
            (item for item in _walk_dicts(details) if str(item.get("id", "")) == match_row["id"]),
            details if isinstance(details, dict) else None,
        )
        if not isinstance(match, dict):
            raise LiveScoreMCPError("LiveScore MCP returned no details for the selected match.")
        detail_home = _team_name(match.get("localteam"))
        detail_away = _team_name(match.get("visitorteam"))
        detail_score = _score(match.get("scoretime") or match.get("score"))
        if (
            not detail_home or not detail_away
            or not same_team_name(detail_home, home_team)
            or not same_team_name(detail_away, away_team)
        ):
            raise LiveScoreMCPError("Match details do not agree with Jupiter's home/away teams; statistics were rejected.")

        commentaries = match.get("commentaries") if isinstance(match.get("commentaries"), dict) else {}
        stats = commentaries.get("stats") if isinstance(commentaries.get("stats"), dict) else {}
        home = stats.get("localteam") if isinstance(stats.get("localteam"), dict) else {}
        away = stats.get("visitorteam") if isinstance(stats.get("visitorteam"), dict) else {}
        home_passes, away_passes = _int(home.get("passestotal")), _int(away.get("passestotal"))
        home_passes_accurate = _int(home.get("passesaccurate"))
        away_passes_accurate = _int(away.get("passesaccurate"))
        return MatchStatistics(
            match_id=match_row["id"],
            home_team=detail_home,
            away_team=detail_away,
            score=detail_score,
            score_consistent=detail_score == expected_score,
            status=str(match.get("status") or "LIVE"),
            minute=_int(match.get("minute") or match.get("elapsed")),
            home_shots=_int(home.get("shotstotal")),
            away_shots=_int(away.get("shotstotal")),
            home_shots_on_target=_int(home.get("shotsgoal")),
            away_shots_on_target=_int(away.get("shotsgoal")),
            home_possession=_float(home.get("possestiontime")),
            away_possession=_float(away.get("possestiontime")),
            home_passes=home_passes,
            away_passes=away_passes,
            home_pass_accuracy=_pass_accuracy(home_passes_accurate, home_passes),
            away_pass_accuracy=_pass_accuracy(away_passes_accurate, away_passes),
            home_fouls=_int(home.get("fouls")),
            away_fouls=_int(away.get("fouls")),
            home_yellow_cards=_int(home.get("yellowcards")),
            away_yellow_cards=_int(away.get("yellowcards")),
            home_red_cards=_int(home.get("redcards")),
            away_red_cards=_int(away.get("redcards")),
            home_offsides=_int(home.get("offsides")),
            away_offsides=_int(away.get("offsides")),
            home_corners=_int(home.get("corners")),
            away_corners=_int(away.get("corners")),
            received_at=datetime.now(UTC),
        )
