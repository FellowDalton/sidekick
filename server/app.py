"""The host HTTP API: a thin wrapper over sidekick.py. The engine stays the SOLE writer
of the ledger; this layer only routes requests, enforces bearer auth and idempotency,
and publishes each change to git. Mutations are serialized by an inter-process vault lock
(shared with the periodic sync job — see server/sync_pull.py); still run with a single
worker (the idempotency store is per-process). Tokens map to identities (name + role);
role `shared` sees and touches ONLY shared tasks — enforced HERE (the PWA's hiding is
convenience, not security)."""
import os
import sys

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

# ensure the repo root (where sidekick.py lives) is importable, even under uvicorn
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sidekick                       # noqa: E402
from server.config import load_config  # noqa: E402
from server import git_sync            # noqa: E402
from server.idempotency import IdempotencyStore  # noqa: E402
from server.vault_lock import vault_lock  # noqa: E402

VALID_CATEGORIES = {"phone", "admin", "errand", "chore"}


def create_app(config=None):
    config = config or load_config()
    sidekick.configure(config.vault)
    idem = IdempotencyStore(os.path.join(config.vault, ".sidekick-idempotency.json"))

    app = FastAPI(title="Sidekick host API")
    app.state.config = config
    app.state.idem = idem

    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    @app.exception_handler(git_sync.GitSyncError)
    async def _git_exc(request: Request, exc: git_sync.GitSyncError):
        return JSONResponse(status_code=409, content={"error": str(exc)})

    def require_auth(authorization):
        """Return the calling token's identity {"name", "role"}; 401 on anything else."""
        if authorization.startswith("Bearer "):
            ident = config.tokens.get(authorization[len("Bearer "):])
            if ident is not None:
                return ident
        raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/me")
    def get_me(authorization: str = Header(default="")):
        ident = require_auth(authorization)
        return {"name": ident["name"], "role": ident["role"]}

    @app.get("/feed")
    def get_feed(authorization: str = Header(default="")):
        ident = require_auth(authorization)
        if ident["role"] == "shared":
            # her page doesn't need the game feed; personal data never leaves the host
            return {"events": [],
                    "active": [a for a in sidekick.read_active() if a["shared"]]}
        return {"events": sidekick.read_ledger(), "active": sidekick.read_active()}

    def _read_json(request_body):
        return request_body if isinstance(request_body, dict) else {}

    def _idem_replay_or_run(idem_key, fn):
        if idem_key:
            prior = idem.get(idem_key)
            if prior is not None:
                return JSONResponse(status_code=prior["status_code"], content=prior["body"])
        status_code, body = fn()   # fn() may raise HTTPException (e.g. 404); let it propagate — errors must never be cached
        if idem_key:
            idem.put(idem_key, status_code, body)
        return JSONResponse(status_code=status_code, content=body)

    @app.post("/tasks")
    async def post_task(request: Request,
                        authorization: str = Header(default=""),
                        idempotency_key: str = Header(default="")):
        identity = require_auth(authorization)
        try:
            data = _read_json(await request.json())
        except Exception:
            data = {}
        title = data.get("title")
        category = data.get("category")
        if not title or not isinstance(title, str):
            raise HTTPException(status_code=400, detail="title is required")
        if category not in VALID_CATEGORIES:
            raise HTTPException(status_code=400,
                                detail=f"category must be one of {sorted(VALID_CATEGORIES)}")
        # role `shared` is forced onto the shared list; role `full` may opt in.
        # `from` is ALWAYS the token identity — never client-supplied (spec SP2).
        shared = True if identity["role"] == "shared" else bool(data.get("shared"))

        def run():
            with vault_lock(config.vault):
                tid = sidekick.create_task(title, category,
                                           from_=identity["name"], shared=shared)
                sidekick.regenerate()
                git_sync.commit_and_push(config.vault, f"api: new {tid}",
                                         push=config.push, remote=config.remote)
                entry = next((a for a in sidekick.read_active() if a["id"] == tid), None)
            return 201, entry

        return _idem_replay_or_run(idempotency_key, run)

    @app.post("/tasks/{task_id}/complete")
    async def post_complete(task_id: str, request: Request,
                            authorization: str = Header(default=""),
                            idempotency_key: str = Header(default="")):
        identity = require_auth(authorization)
        try:
            data = _read_json(await request.json())
        except Exception:
            data = {}
        completed_at = data.get("completed_at")

        def run():
            with vault_lock(config.vault):
                if identity["role"] == "shared":
                    # a personal task must be indistinguishable from a missing one
                    try:
                        fm, _ = sidekick.read_note(sidekick.task_path(task_id))
                    except FileNotFoundError:
                        raise HTTPException(status_code=404, detail=f"no such task: {task_id}")
                    if not fm.get("shared"):
                        raise HTTPException(status_code=404, detail=f"no such task: {task_id}")
                try:
                    result = sidekick.complete(task_id, completed_at=completed_at)
                except FileNotFoundError:
                    raise HTTPException(status_code=404, detail=f"no such task: {task_id}")
                sidekick.regenerate()
                git_sync.commit_and_push(config.vault, f"api: complete {task_id}",
                                         push=config.push, remote=config.remote)
            return 200, result

        return _idem_replay_or_run(idempotency_key, run)

    return app
