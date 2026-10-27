from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from services.api import (
    agent_auth,
    annotations,
    auth,
    corpora,
    errors,
    evidence,
    jobs,
    label_sets,
    projects,
    search,
    stats,
    subcorpora,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    from services.api.db import transaction

    with transaction() as db:
        label_sets.seed_builtin(db)
    yield


app = FastAPI(
    title="Corpus API",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
errors.install(app)


@app.middleware("http")
async def check_origin(request: Request, call_next):
    if request.url.path.startswith("/api/") and auth.origin_rejected(request):
        return errors.error_response(403, "ORIGIN_REJECTED", "请求来源不被允许")
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"ok": True}


for module in (
    auth,
    agent_auth,
    projects,
    corpora,
    subcorpora,
    search,
    stats,
    evidence,
    jobs,
    label_sets,
    annotations,
):
    app.include_router(module.router)
app.include_router(auth.users_router)
