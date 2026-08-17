from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
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
# origins are explicit (never a wildcard), so this doesn't accidentally
# become "any site can call this API".
#
# 2026-08-13 (deploy prep): sourced from settings.cors_allow_origins
# (comma-separated) instead of a hardcoded list -- the real frontend
# origin is a placeholder (CORS_ALLOW_ORIGINS env var) until DNS/tunnel
# routing is finalized; the default below keeps local dev's exact
# pre-existing behavior unchanged.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_allow_origins.split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2026-08-14 (deploy fix): Cloudflare Tunnel forwards everything under
# /api on tp.masterfaster.org to this backend container, but the routes
# below were registered with no /api prefix at all -- every real request
# 404'd. Cloudflare intentionally does NOT strip /api at the tunnel level
# (the frontend also has its own page route at /rules, which would become
# indistinguishable from this API's /rules endpoint if stripped there), so
# the prefix has to live here instead. One APIRouter wraps every existing
# sub-router (each sub-router keeps its own prefix/tags/dependencies
# unchanged) plus /health, so every path below becomes /api/<unchanged
# path> -- e.g. /auth/login -> /api/auth/login -- with no other path
# renamed.
api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(admin.config_router)
api_router.include_router(rules.router)
api_router.include_router(rule_sync.router)
api_router.include_router(patients.router)
api_router.include_router(versions.router)
api_router.include_router(uploads.router)
api_router.include_router(rule_results.router)
api_router.include_router(reports.router)


@api_router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_router)
