from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routers import auth, patients, reports, rule_results, rule_sync, rules, uploads, versions
from app.scheduler import build_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = build_scheduler()
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="TP Review System API", lifespan=lifespan)

app.include_router(auth.router)
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
