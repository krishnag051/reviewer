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

    # Previous TP round: separate, small ceiling for the previous-TP
    # comparison call site (app.agent_client.review_previous_tp). Real
    # calls only happen for QA-ACF-04 (narrative-score fallback, only when
    # the boxed/structured score isn't found on one or both documents) and
    # QA-PROB-04 (near-identical semantic check) -- at most 2-3 real calls
    # per upload that actually has a previous TP attached, never per every
    # upload (review_previous_tp returns immediately with zero calls when
    # previous_tp_path is None). Same discipline as session_notes_max_calls
    # above: a real, enforced number, never uncapped.
    previous_tp_max_calls: int = 6

    # Next Round, Part 2: the real LLM humanize pass, one real call per
    # finding a real upload produces (~170ish rules today). This is a
    # DIFFERENT real-call surface than either cap above -- not a per-rule
    # judgment batch, not a per-file extraction, but a per-FINDING rewrite
    # pass that runs after everything else. Same standing discipline: a
    # real, enforced number, never uncapped. 200 gives headroom above the
    # current real rule count without being effectively unbounded.
    humanize_max_calls: int = 200

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

    # --- outbound email (Escalate to BCBA real send, 2026-08-12) -------
    # Plain smtplib over stdlib `email.mime` -- nothing else in this
    # codebase sends mail, so there's no existing infra to reuse. `None`
    # host (the default, every environment until someone configures a
    # real mail server) means app/services/mailer.py raises a clear,
    # typed error instead of silently pretending to send -- see that
    # module's own docstring. A real deploy sets these five in its own
    # .env; nothing here is a secret with a real default value baked in.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    # STARTTLS on a standard submission port (587) by default -- the
    # common case for real providers (SendGrid, SES SMTP, Gmail relay,
    # etc). Set False only for a plaintext-local/dev SMTP debug server
    # that doesn't speak TLS at all (e.g. `python -m smtpd`/`aiosmtp`
    # on localhost) -- never for a real external host.
    smtp_use_tls: bool = True

    # --- CORS (2026-08-13, deploy prep) ---------------------------------
    # Comma-separated, not a real list field -- pydantic-settings expects
    # JSON-array syntax for a List[str] env var ("[\"a\",\"b\"]"), which is
    # an awkward thing to hand-type into a docker-compose.yml/.env file.
    # Plain comma-split (see app/main.py) is the simpler contract for an
    # operator setting this. Default matches every pre-2026-08-13 value
    # (the frontend's own dev server ports) so nothing changes for local
    # dev unless this is explicitly overridden. A real deploy sets this to
    # the real frontend origin(s) once DNS/tunnel routing is finalized --
    # deliberately NOT guessed at here.
    cors_allow_origins: str = "http://localhost:3000,http://localhost:5173,http://127.0.0.1:5173"


settings = Settings()
