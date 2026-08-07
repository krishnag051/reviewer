from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://tpuser:tppass@localhost:5432/tpreview"
    jwt_secret: str = "change-me-in-real-deploys"
    jwt_expires_minutes: int = 720
    retention_days_default: int = 30
    upload_storage_dir: str = "./data/uploads"

    # --- rule-checking agent wiring (2026-07-30) ------------------------
    # app/rule_engine/client.py imports agent-making/agent/pipeline/api.py
    # directly (it's not an installed package) by inserting this path onto
    # sys.path at call time. Defaults to the standard sibling-directory
    # repo layout (../../agent-making/agent relative to this backend/
    # directory); override if agent-making ever lives somewhere else
    # (e.g. a slimmed deploy that vendors it differently).
    agent_making_agent_path: str = "../agent-making/agent"
    # agent-making's own judge.py already loads agent-making/.env via a
    # relative-to-itself path the moment it's imported, so this is
    # belt-and-suspenders, not strictly load-bearing on its own — but it
    # makes the dependency visible from the backend's own config instead
    # of only existing in a second .env file elsewhere, and it's what a
    # deploy that ships agent-making's code without its own .env would
    # need. If set, client.py exports it into the process environment
    # (via os.environ.setdefault, so agent-making's own .env still wins if
    # both are present) before importing pipeline.api.
    anthropic_api_key: str | None = None
    # Hard cap on real API calls per review (forwarded to
    # review_treatment_plan's own ApiCallTracker) — a backend process
    # calling this on every upload should never be able to runaway-retry
    # into an unbounded bill. A real document costs ~2 calls in practice
    # (see agent-making/agent/tests/test_api.py); this leaves generous
    # headroom for escalation/integrity retries.
    rule_engine_max_calls: int = 50

    # Round 67: separate, smaller ceiling for the session-notes extraction
    # call site (app.agent_client.review_session_notes) -- distinct cap
    # from rule_engine_max_calls above since this is a different, much
    # smaller real-call surface (one real call per uploaded session-note
    # file, typically 1-3 files, not a ~120-rule judgment batch). Still a
    # real, enforced number, never uncapped, same discipline as the TP
    # pipeline's own cap.
    session_notes_max_calls: int = 10

    # Dev-only simulated-completion path (Round 49) -- lets a `developer`-role
    # user test the U1/U2/V1/V2/finalize lifecycle mechanics without waiting
    # on or paying for the real agent. Off by default; the route itself is
    # ALSO gated on the `developer` role (see app/deps.py::require_developer)
    # so both conditions must hold, and neither is reachable from the normal
    # login flow a real BCBA/reviewer uses (they're never given the developer
    # role, and this defaults to False in every environment unless someone
    # deliberately opts in). See app/services/simulated_pipeline.py -- that
    # module has no import path to app.rule_engine.client / review_treatment_
    # plan at all, so this flag can never route to a real Anthropic API call
    # even if misconfigured.
    allow_simulated_completion: bool = False


settings = Settings()
