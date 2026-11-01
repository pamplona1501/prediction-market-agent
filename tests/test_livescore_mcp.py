import json
from datetime import UTC, datetime

import pytest

from integrations.sports_data.livescore_mcp import (
    LiveScoreMCPClient,
    LiveScoreMCPError,
    _decode_tool_result,
)


class FakeResponse:
    def __init__(self, message=None, *, status=200, headers=None):
        self.status_code = status
        self.headers = headers or {"content-type": "application/json"}
        self._message = message
        self.content = json.dumps(message).encode() if message is not None else b""
        self.text = json.dumps(message) if message is not None else ""
        self.ok = status < 400

    def json(self):
        return self._message


class FakeMcpSession:
    def __init__(self, matches, details, *, double_encode=False):
        self.matches = matches
        self.details = details
        self.double_encode = double_encode
        self.calls = []

    def post(self, url, *, headers, json, timeout):
        self.calls.append(json)
        method = json["method"]
        if method == "initialize":
            return FakeResponse({"jsonrpc": "2.0", "id": json["id"], "result": {"protocolVersion": "2025-11-25"}})
        if method == "notifications/initialized":
            return FakeResponse(status=202)
        if method == "tools/call":
            name = json["params"]["name"]
            if name == "health":
                return FakeResponse({"jsonrpc": "2.0", "id": json["id"], "result": {
                    "content": [{"type": "text", "text": "ok: test"}],
                }})
            result = self.matches if name == "get_live_scores" else self.details
            text = json_module.dumps(result)
            if self.double_encode:
                text = json_module.dumps(text)
            return FakeResponse({"jsonrpc": "2.0", "id": json["id"], "result": {
                "content": [{"type": "text", "text": text}],
            }})
        raise AssertionError(f"Unexpected MCP method: {method}")


json_module = json


def _client(feed, detail, *, double_encode=False):
    session = FakeMcpSession(
        {"countries": [{"country": "England", "leagues": [{"matches": feed}]}]},
        detail,
        double_encode=double_encode,
    )
    return LiveScoreMCPClient(session=session), session


def test_livescore_mcp_fetches_stats_for_one_exact_live_match():
    client, session = _client(
        [
            {"id": 101, "localteam": "Home FC", "visitorteam": "Away FC", "scoretime": "1-0", "status": "2H"},
            {"id": 202, "localteam": "Other FC", "visitorteam": "Club", "scoretime": "0-0", "status": "1H"},
        ],
        {"id": 101, "localteam": "Home FC", "visitorteam": "Away FC", "scoretime": "1-0",
         "status": "2H", "commentaries": {"stats": {
             "localteam": {"shotstotal": "9", "shotsgoal": "3", "possestiontime": "62%", "passestotal": "410", "passesaccurate": "369", "fouls": "7", "yellowcards": "1", "redcards": "0", "offsides": "2", "corners": "5"},
             "visitorteam": {"shotstotal": "4", "shotsgoal": "1", "possestiontime": "38%", "passestotal": "290", "passesaccurate": "232", "fouls": "12", "yellowcards": "2", "redcards": "0", "offsides": "1", "corners": "2"},
         }}},
    )

    stats = client.get_match_statistics(home_team="Home FC", away_team="Away FC", score="1 - 0")

    assert stats.match_id == "101"
    assert stats.home_shots == 9 and stats.away_shots == 4
    assert stats.home_shots_on_target == 3 and stats.away_shots_on_target == 1
    assert stats.home_possession == 62 and stats.away_possession == 38
    assert stats.home_passes == 410 and stats.away_passes == 290
    assert stats.home_pass_accuracy == 90 and stats.away_pass_accuracy == 80
    assert stats.home_fouls == 7 and stats.away_yellow_cards == 2
    assert stats.home_red_cards == 0 and stats.away_offsides == 1
    assert stats.home_corners == 5 and stats.away_corners == 2
    assert stats.has_statistics
    assert [call.get("params", {}).get("name") for call in session.calls if call["method"] == "tools/call"] == [
        "get_live_scores", "get_match",
    ]
    tool_calls = [call for call in session.calls if call["method"] == "tools/call"]
    assert tool_calls[0]["params"]["arguments"] == {"format": "text"}
    assert tool_calls[1]["params"]["arguments"] == {"id": "101", "h2h": False, "format": "text"}


def test_livescore_mcp_decodes_json_payload_wrapped_in_json_text():
    client, _ = _client(
        [{"id": 101, "localteam": "Home FC", "visitorteam": "Away FC", "scoretime": "1-0"}],
        {"id": 101, "localteam": "Home FC", "visitorteam": "Away FC", "scoretime": "1-0",
         "commentaries": {"stats": {"localteam": {"shotstotal": "9"}}}},
        double_encode=True,
    )

    stats = client.get_match_statistics(home_team="Home FC", away_team="Away FC", score="1-0")

    assert stats.match_id == "101"
    assert stats.home_shots == 9


def test_livescore_mcp_repairs_control_characters_inside_provider_json_strings():
    decoded = _decode_tool_result({
        "content": [{"type": "text", "text": '[{"localteam":"Home\nFC","visitorteam":"Away FC"}]'}],
    })

    assert decoded == [{"localteam": "Home\nFC", "visitorteam": "Away FC"}]


def test_livescore_mcp_reads_compact_match_detail_text():
    client, _ = _client(
        [{"id": 101, "localteam": "Home FC", "visitorteam": "Away FC", "scoretime": "1-0"}],
        "Home FC 1-0 Away FC · HT\nPremier League\n"
        "Statistics (home - away):\n"
        "- Possession: 61% - 39%\n- Shots: 8 - 3\n"
        "- Shots on target: 4 - 1\n- Corners: 5 - 2\n"
        "- Fouls: 7 - 9\n- Yellow cards: 1 - 2\n"
        "- Red cards: 0 - 0\n- Offsides: 2 - 1\n"
        "- Passes: 400 - 280\n- Accurate passes: 340 - 210\n",
    )

    stats = client.get_match_statistics(home_team="Home FC", away_team="Away FC", score="1-0")

    assert stats.score_consistent
    assert stats.home_shots == 8 and stats.away_shots == 3
    assert stats.home_possession == 61 and stats.away_possession == 39
    assert stats.home_pass_accuracy == 85 and stats.away_pass_accuracy == 75


def test_livescore_mcp_fails_closed_if_no_team_pair_match():
    client, session = _client(
        [{"id": 101, "localteam": "Different FC", "visitorteam": "Another Club", "scoretime": "0-0"}],
        {},
    )

    with pytest.raises(LiveScoreMCPError, match="same home and away teams"):
        client.get_match_statistics(home_team="Home FC", away_team="Away FC", score="1-0")

    assert not any(call.get("params", {}).get("name") == "get_match" for call in session.calls)


def test_livescore_mcp_rejects_ambiguous_rows_but_allows_a_lagging_score():
    ambiguous, _ = _client(
        [
            {"id": 101, "localteam": "Home FC", "visitorteam": "Away FC", "scoretime": "0-0"},
            {"id": 102, "localteam": "Home FC", "visitorteam": "Away FC", "scoretime": "0-0"},
        ],
        {},
    )
    with pytest.raises(LiveScoreMCPError, match="ambiguous"):
        ambiguous.get_match_statistics(home_team="Home FC", away_team="Away FC", score="0-0")

    lagging, _ = _client(
        [{"id": 101, "localteam": "Man Utd", "visitorteam": "Chelsea FC", "scoretime": "0-0"}],
        {"id": 101, "localteam": "Manchester United", "visitorteam": "Chelsea", "scoretime": "0-0",
         "commentaries": {"stats": {"localteam": {"shotstotal": "9"}, "visitorteam": {"shotstotal": "2"}}}},
    )
    stats = lagging.get_match_statistics(home_team="Manchester United", away_team="Chelsea", score="1-0")
    assert stats.home_shots == 9 and stats.away_shots == 2
    assert not stats.score_consistent


def test_livescore_mcp_matches_common_team_name_aliases():
    client, _ = _client(
        [{"id": 101, "localteam": "FC Bayern München", "visitorteam": "Paris SG", "scoretime": "2-1"}],
        {"id": 101, "localteam": "Bayern Munich", "visitorteam": "Paris Saint-Germain", "scoretime": "2-1",
         "commentaries": {"stats": {"localteam": {"shotstotal": "8"}, "visitorteam": {"shotstotal": "4"}}}},
    )
    stats = client.get_match_statistics(home_team="Bayern Munich", away_team="PSG", score="2-1")
    assert stats.match_id == "101" and stats.score_consistent


def test_livescore_mcp_rejects_details_for_a_different_team_pair():
    client, _ = _client(
        [{"id": 101, "localteam": "Home FC", "visitorteam": "Away FC", "scoretime": "0-0"}],
        {"id": 101, "localteam": "Another Home FC", "visitorteam": "Away FC", "scoretime": "0-0",
         "commentaries": {"stats": {"localteam": {"shotstotal": "9"}, "visitorteam": {"shotstotal": "2"}}}},
    )
    with pytest.raises(LiveScoreMCPError, match="home/away teams"):
        client.get_match_statistics(home_team="Home FC", away_team="Away FC", score="0-0")


def test_livescore_mcp_does_not_invent_missing_statistics():
    client, _ = _client(
        [{"id": 101, "localteam": "Home FC", "visitorteam": "Away FC", "scoretime": "0-0"}],
        {"id": 101, "localteam": "Home FC", "visitorteam": "Away FC", "scoretime": "0-0"},
    )

    stats = client.get_match_statistics(home_team="Home FC", away_team="Away FC", score="0-0")

    assert not stats.has_statistics
    assert stats.home_shots is None and stats.away_possession is None


def test_livescore_mcp_requires_https_endpoint():
    with pytest.raises(ValueError, match="HTTPS"):
        LiveScoreMCPClient("http://example.test/mcp")


def test_livescore_mcp_health_check_uses_read_only_echo_tool():
    client, session = _client([], {})

    assert client.check_connection()
    assert [call.get("params", {}).get("name") for call in session.calls if call["method"] == "tools/call"] == [
        "health",
    ]
