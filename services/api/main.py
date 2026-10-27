from fastapi import FastAPI, Request

from services.api import auth, corpora, errors, jobs, projects, search, subcorpora

app = FastAPI(title="Corpus API", docs_url="/api/docs", openapi_url="/api/openapi.json")
errors.install(app)


@app.middleware("http")
async def check_origin(request: Request, call_next):
    if request.url.path.startswith("/api/") and auth.origin_rejected(request):
        return errors.error_response(403, "ORIGIN_REJECTED", "请求来源不被允许")
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"ok": True}


for module in (auth, projects, corpora, subcorpora, search, jobs):
    app.include_router(module.router)
app.include_router(auth.users_router)
