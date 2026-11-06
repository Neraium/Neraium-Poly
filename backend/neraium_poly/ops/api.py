"""Loopback operational service. No live trade endpoints exist."""

from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from neraium_poly.settings import Settings


def create_app(runtime=None, frontend_path: Path | None = None, local_port: int = 18740) -> FastAPI:
    Settings.from_env()
    if runtime is None:
        from neraium_poly.ops.runtime import ResearchRuntime

        runtime = ResearchRuntime()
        runtime.run_scenario()
    app = FastAPI(title="Neraium-Poly Paper Research", version="0.1.0")
    lock = RLock()

    @app.middleware("http")
    async def local_mutations(request: Request, call_next):
        # Prevent cross-origin browser requests from mutating this loopback service.
        origin = request.headers.get("origin")
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and origin
            and origin
            not in {
                "http://127.0.0.1:18740",
                "http://localhost:18740",
                "http://127.0.0.1:18741",
                "http://localhost:18741",
                f"http://127.0.0.1:{local_port}",
                f"http://127.0.0.1:{getattr(getattr(runtime, 'config', None), 'port', 18740)}",
            }
        ):
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "Cross-origin mutation rejected"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health():
        if hasattr(runtime, "health"):
            return runtime.health()
        return {
            "status": "ok",
            "paper_trading": True,
            "live_trading_enabled": False,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    @app.get("/api/market-frame")
    def public_market_frame():
        if not hasattr(runtime, "market_frame"):
            raise HTTPException(404, "Actual public market frame unavailable in this mode")
        return runtime.market_frame()

    @app.get("/api/state")
    def state():
        with lock:
            return runtime.state()

    @app.get("/api/archive-state")
    def archive_state():
        if not hasattr(runtime, "archive_state"):
            raise HTTPException(404, "Managed archive state unavailable in this mode")
        return runtime.archive_state()

    @app.post("/api/scenario")
    def scenario():
        with lock:
            if runtime.suspended:
                raise HTTPException(409, "Emergency stop active; process restart with review required")
            try:
                runtime.run_scenario()
            except ValueError as error:
                raise HTTPException(409, str(error)) from error
            return {"ok": True}

    @app.post("/api/kill-switch")
    def kill_switch():
        with lock:
            runtime.stop()
            return {"ok": True, "suspended": True}

    if frontend_path and frontend_path.is_dir():
        app.mount("/", StaticFiles(directory=frontend_path, html=True), name="dashboard")
    return app
