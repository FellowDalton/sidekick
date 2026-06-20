"""The host HTTP API: a thin wrapper over sidekick.py. The engine stays the SOLE writer
of the ledger; this layer only routes requests, enforces bearer auth and idempotency,
and publishes each change to git. Mutations are serialized by a write lock — run with a
single worker. Phase 1: GET /feed here; the write endpoints are added in Task 5."""
import os
import sys
import threading

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

# ensure the repo root (where sidekick.py lives) is importable, even under uvicorn
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sidekick                       # noqa: E402
from server.config import load_config  # noqa: E402
from server import git_sync            # noqa: E402
from server.idempotency import IdempotencyStore  # noqa: E402

VALID_CATEGORIES = {"phone", "admin", "errand", "chore"}


def create_app(config=None):
    config = config or load_config()
    sidekick.configure(config.vault)
    idem = IdempotencyStore(os.path.join(config.vault, ".sidekick-idempotency.json"))
    write_lock = threading.Lock()

    app = FastAPI(title="Sidekick host API")
    app.state.config = config
    app.state.idem = idem
    app.state.write_lock = write_lock

    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    def require_auth(authorization):
        if authorization != f"Bearer {config.token}":
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/feed")
    def get_feed(authorization: str = Header(default="")):
        require_auth(authorization)
        return {"events": sidekick.read_ledger(), "active": sidekick.read_active()}

    return app
