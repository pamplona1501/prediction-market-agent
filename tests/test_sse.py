import json
import asyncio

from live_app.main import _sse_message
from live_app.main import create_app
from monitoring.service import LiveMonitor
from fastapi.testclient import TestClient


def test_sse_message_uses_eventsource_data_frame_and_compact_json():
    message = _sse_message({"service": {"status": "running"}, "events": []})

    assert message.startswith("data: ")
    assert message.endswith("\n\n")
    assert json.loads(message[6:].strip()) == {"service": {"status": "running"}, "events": []}


def test_subscriber_receives_initial_snapshot_and_only_latest_queued_state():
    async def scenario():
        monitor = LiveMonitor()
        queue = await monitor.subscribe()
        initial = await queue.get()
        assert initial["execution"] == "disabled"

        monitor.state = {**monitor.state, "sequence": 1}
        await monitor._publish()
        monitor.state = {**monitor.state, "sequence": 2}
        await monitor._publish()

        assert queue.qsize() == 1
        assert (await queue.get())["sequence"] == 2
        monitor.unsubscribe(queue)

    asyncio.run(scenario())


def test_sse_endpoint_streams_initial_snapshot_and_unregisters_client():
    class FakeMonitor:
        state = {"service": {"status": "running"}}
        unregistered = False

        async def start(self):
            pass

        async def stop(self):
            pass

        def snapshot(self):
            return self.state

        async def subscribe(self):
            queue = asyncio.Queue(maxsize=1)
            queue.put_nowait({"service": {"status": "running"}, "marker": "initial"})
            return queue

        def unsubscribe(self, queue):
            self.unregistered = True

    monitor = FakeMonitor()
    with TestClient(create_app(monitor)) as client:
        with client.stream("GET", "/api/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            line = next(response.iter_lines())
            assert json.loads(line[6:]) == {"service": {"status": "running"}, "marker": "initial"}
    assert monitor.unregistered


def test_watchlist_routes_pin_and_remove_without_starting_monitoring():
    class FakeMonitor:
        state = {"events": [], "watchlist": []}
        monitored = False

        async def start(self): pass
        async def stop(self): pass
        def snapshot(self): return self.state
        async def watch_event(self, event_id):
            self.state = {**self.state, "watchlist": [{"event_id": event_id}]}
        async def unwatch_event(self, event_id):
            self.state = {**self.state, "watchlist": []}

    monitor = FakeMonitor()
    with TestClient(create_app(monitor)) as client:
        response = client.post("/api/watchlist/jupiter%3Aevent-1")
        assert response.status_code == 200
        assert response.json()["watchlist"] == [{"event_id": "jupiter:event-1"}]
        assert monitor.monitored is False
        response = client.delete("/api/watchlist/jupiter%3Aevent-1")
        assert response.status_code == 200
        assert response.json()["watchlist"] == []
