from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import admin, auth, patients, reports, rule_results, rule_sync, rules, uploads, versions
from app.scheduler import build_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = build_scheduler()
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="TP Review System API", lifespan=lifespan)

# Round 41: the frontend now makes real cross-origin fetch calls from its
# own Vite dev server (a different origin/port) -- without this, the
# browser blocks every request before it even reaches a route. Auth is
# Bearer-token-in-header (never cookies), so allow_credentials stays False;
# origins are the frontend dev server's usual ports, not a wildcard, so
# this doesn't accidentally become "any site can call this API".
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(admin.config_router)
app.include_router(rules.router)
app.include_router(rule_sync.router)
app.include_router(patients.router)
app.include_router(versions.router)
app.include_router(uploads.router)
app.include_router(rule_results.router)
app.include_router(reports.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
