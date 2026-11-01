"""FastAPI service and same-origin browser UI for read-only match monitoring."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from database.connection import check_database
from monitoring.service import LiveMonitor


WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class MonitorRequest(BaseModel):
    event_id: str | None = Field(default=None, max_length=160)


def create_app(monitor: LiveMonitor | None = None) -> FastAPI:
    service = monitor or LiveMonitor()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await service.start()
        yield
        await service.stop()

    app = FastAPI(
        title="Prediction Market Match Monitor",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.monitor = service

    @app.get("/api/state")
    async def get_state() -> dict[str, Any]:
        return service.snapshot()

    @app.get("/api/health")
    async def get_health() -> dict[str, Any]:
        available, detail = await asyncio.to_thread(check_database)
        return {
            "status": service.state.get("service", {}).get("status", "unknown"),
            "database": "connected" if available else "unavailable",
            "database_detail": detail,
            "execution": "disabled",
        }

    @app.post("/api/monitor")
    async def set_monitor(request: MonitorRequest) -> dict[str, Any]:
        try:
            await service.monitor_event(request.event_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        return service.snapshot()

    @app.post("/api/statistics/refresh")
    async def refresh_statistics(request: MonitorRequest) -> dict[str, Any]:
        if request.event_id is None:
            raise HTTPException(status_code=400, detail="event_id is required.")
        try:
            return await service.refresh_match_statistics(request.event_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.websocket("/ws/events")
    async def stream_events(websocket: WebSocket) -> None:
        await websocket.accept()
        queue = await service.subscribe()
        try:
            while True:
                payload = await queue.get()
                await websocket.send_json(payload)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            service.unsubscribe(queue)

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")
    return app


app = create_app()
