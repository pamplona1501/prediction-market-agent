import asyncio

import httpx

from integrations.market_data.jupiter import (
    JUPITER_PRIORITY_LIVE, JUPITER_PRIORITY_RADAR, JupiterPredictionClient,
)
from integrations.sports_data.livescore_mcp import LiveScoreMCPClient


def test_jupiter_async_http_client_parses_event_page():
    seen = []

    async def scenario():
        def handler(request):
            seen.append((request.url.path, dict(request.url.params)))
            return httpx.Response(200, json={"data": [{
                "eventId": "event-1", "metadata": {"title": "Home vs Away"},
                "volumeUsd": 1_250_000_000_000, "markets": [],
            }], "pagination": {"total": 51, "hasNext": True}})

        client = JupiterPredictionClient(async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        page = await asyncio.wait_for(client.alist_sports_events(
            filter_name="upcoming", tag="soccer", include_markets=True, limit=50,
            start=50, sort_by="beginAt", sort_direction="asc", priority=JUPITER_PRIORITY_RADAR,
        ), timeout=5)
        await client._async_client.aclose()
        assert page.events[0].event_id == "event-1"
        assert str(page.events[0].reported_volume_usd) == "1250000"
        assert page.has_next is True and page.total == 51

    asyncio.run(scenario())
    assert seen == [("/prediction/v1/events", {
        "category": "sports", "filter": "upcoming", "includeMarkets": "true",
        "start": "50", "end": "100", "tags": "soccer", "sortBy": "beginAt",
        "sortDirection": "asc",
    })]


def test_jupiter_async_request_waits_are_prioritized_without_blocking_loop(monkeypatch):
    import integrations.market_data.jupiter as module
    monkeypatch.setattr(module, "_KEYLESS_INTERVAL_SECONDS", 0.02)
    seen = []

    async def scenario():
        def handler(request):
            seen.append(request.url.path)
            return httpx.Response(200, json={"ok": True})

        client = JupiterPredictionClient(async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        client._async_last_request = __import__("time").monotonic()
        low = asyncio.create_task(client._aget_json("radar", {}, priority=JUPITER_PRIORITY_RADAR))
        await asyncio.sleep(0)
        live = asyncio.create_task(client._aget_json("live", {}, priority=JUPITER_PRIORITY_LIVE))
        heartbeats = 0
        async def heartbeat():
            nonlocal heartbeats
            for _ in range(5):
                await asyncio.sleep(0.002)
                heartbeats += 1
        pulse = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.003)
        async with client._async_rate_condition:
            client._async_last_request = 0
            client._async_rate_condition.notify_all()
        await asyncio.gather(low, live, pulse)
        await client._async_client.aclose()
        assert heartbeats == 5

    asyncio.run(scenario())
    assert seen[0] == "/prediction/v1/live"


def test_livescore_async_http_path_resolves_one_verified_match():
    requests_seen = []

    async def scenario():
        def handler(request):
            body = request.read()
            import json
            payload = json.loads(body)
            requests_seen.append(payload["method"])
            if payload["method"] == "initialize":
                result = {"protocolVersion": "2025-11-25"}
            elif payload["method"] == "notifications/initialized":
                return httpx.Response(202)
            else:
                name = payload["params"]["name"]
                result = {"structuredContent": ([{
                    "id": 42, "localteam": "Home FC", "visitorteam": "Away FC", "scoretime": "1-0",
                }] if name == "get_live_scores" else {
                    "id": 42, "localteam": "Home FC", "visitorteam": "Away FC", "scoretime": "1-0",
                    "commentaries": {"stats": {"localteam": {"shotstotal": 8}, "visitorteam": {"shotstotal": 3}}},
                })}
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload.get("id"), "result": result})

        client = LiveScoreMCPClient(async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        stats = await client.aget_match_statistics(home_team="Home FC", away_team="Away FC", score="1-0")
        await client._async_client.aclose()
        assert stats.match_id == "42"
        assert stats.home_shots == 8 and stats.away_shots == 3

    asyncio.run(scenario())
    assert requests_seen == ["initialize", "notifications/initialized", "tools/call", "tools/call"]
