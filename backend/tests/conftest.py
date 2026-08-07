"""Test-suite bootstrap. The env-var override at the very top MUST run before
any `app.*` module is imported anywhere in the test session (including by
other test files) — pytest guarantees this file loads first for everything
under tests/, which is why this logic lives here and not in a fixture.

Once DATABASE_URL is pointed at the disposable test database, every app
module that reads `settings.database_url` (app.db.base's engine/SessionLocal,
and therefore every service that does `from app.db.base import SessionLocal`)
resolves against the test database for the rest of the process — including
inside FastAPI route handlers hit via TestClient. There is no code path in
this test session that can reach the dev database.
"""
import os

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://tpuser:tppass@localhost:5432/tpreview_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import sys  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import jwt  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.main import app  # noqa: E402
from app.security import hash_password  # noqa: E402
from scripts.seed import DEV_PASSWORD  # noqa: E402


def _url_with_dbname(url_str: str, dbname: str) -> str:
    return make_url(url_str).set(database=dbname).render_as_string(hide_password=False)


@pytest.fixture(scope="session", autouse=True)
def _recreated_test_database():
    """Drops and recreates the disposable test database, then runs the full
    Alembic migration chain against it. CREATE/DROP DATABASE can't run
    inside a transaction against the target DB itself, so this connects to
    the 'postgres' maintenance database to issue them. Runs once per test
    session, unconditionally — this is what makes repeated runs safe: every
    run starts from a genuinely empty, freshly migrated database, not
    leftover state from the last run.
    """
    assert settings.database_url == TEST_DATABASE_URL, (
        "settings.database_url is not the test URL — refusing to run "
        "destructive DROP/CREATE DATABASE against something that might be dev data"
    )
    test_db_name = make_url(TEST_DATABASE_URL).database
    assert test_db_name and "test" in test_db_name, (
        f"test database name {test_db_name!r} doesn't look like a test DB — refusing to drop it"
    )

    maintenance_url = _url_with_dbname(TEST_DATABASE_URL, "postgres")
    maintenance_engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    with maintenance_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{test_db_name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{test_db_name}"'))
    maintenance_engine.dispose()

    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(alembic_cfg, "head")

    yield


@pytest.fixture(scope="session")
def engine(_recreated_test_database):
    from app.db.base import engine as app_engine  # bound to TEST_DATABASE_URL, see module docstring

    yield app_engine
    app_engine.dispose()


def _blocked_review_treatment_plan(*args, **kwargs):
    raise RuntimeError(
        "BLOCKED by tests/conftest.py::_block_real_api_calls: a test attempted to call "
        "review_treatment_plan (app.rule_engine.client's real seam into agent-making), "
        "which would make a real, billed call to the Anthropic API. This is blocked for "
        "every test in this suite by default (Round 44, closing the hole Round 43 hit: "
        "a shared _ready_upload() fixture in test_rule_result_overrides.py / "
        "test_finalize_void_review.py made ~30 real, unapproved calls that failed only "
        "because of zero account credit -- nothing structurally prevented them). "
        "If a test is deliberately meant to exercise the real API, mark it explicitly "
        "with @pytest.mark.real_api -- and only run that test with the user's explicit, "
        "per-instance approval (exact command + call count + cost estimate), per "
        "CLAUDE.md's hard rule. Never add that marker to a test, or run one that already "
        "has it, without that approval already granted for this specific run."
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_api: this test deliberately calls the real Anthropic API. Requires the "
        "user's explicit, per-instance approval (CLAUDE.md's hard rule) before every run "
        "-- never add or run this marker on your own judgment.",
    )


# --- Round 45: hard spend ceiling for @pytest.mark.real_api tests -------
#
# The guardrail above (Round 44) makes an UNMARKED test's real call
# structurally impossible. But a marked, approved real_api test can still
# make MORE real calls than approved if its own code runs longer than
# expected, retries, or a future real_api test is added carelessly -- there
# was previously nothing capping total spend across a whole pytest session,
# only per-test approval. This is that cap: independent of which real_api
# test(s) run, or how many there are, the session as a whole can never make
# more than MAX_REAL_API_CALLS_PER_SESSION real calls before every further
# attempt is blocked the same way an unmarked test's call already is.
#
# Configurable, but never silently absent: reads the env var once at import
# time with an explicit default (4) rather than "if set" logic that could
# leave the cap undefined -- there is always a real, enforced number.
MAX_REAL_API_CALLS_PER_SESSION = int(os.environ.get("MAX_REAL_API_CALLS_PER_SESSION", "4"))


class _RealApiCallCounter:
    """Plain module-level singleton, not a pytest fixture -- must survive
    across every real_api test in the session, including across each
    test's own monkeypatch teardown (which reverts
    app.rule_engine.client.review_treatment_plan back to the real,
    unwrapped import between tests). Wrapping happens fresh per test in
    `_block_real_api_calls` below; this counter is what actually persists.
    """

    def __init__(self):
        self.count = 0


_real_api_call_counter = _RealApiCallCounter()


def _make_ceiling_enforced_real_call(real_fn):
    """Wraps the REAL review_treatment_plan (only ever called for a test
    marked @pytest.mark.real_api -- see _block_real_api_calls) so every
    call, regardless of which test makes it, counts against one shared
    session-wide ceiling. Raises BEFORE calling `real_fn` once the ceiling
    is hit -- the same "block before the request goes out" discipline as
    the unmarked-test guardrail, not a warning logged after the fact.

    Counts in units of RAW Anthropic API requests, not "one
    review_treatment_plan invocation" -- a single call to
    review_treatment_plan reviews one whole document via agent-making's own
    self-consistency pass, which is itself 2+ real HTTP requests to
    Anthropic (confirmed live, Round 45: one document = 2 raw calls per
    `result["usage"]["api_calls"]`, exactly matching test_live_smoke.py's
    own long-documented "2 real API calls" estimate). Counting invocations
    instead of raw calls would let the ceiling silently mean half of what
    its number says. Falls back to +1 if a result is ever missing `usage`
    (e.g. a `status: "failed"` short-circuit that still made at least the
    one call that failed) -- undercounting by assuming zero is never the
    safe direction here.

    Round 66: `real_fn` (`app.rule_engine.client.review_treatment_plan`,
    now `app.agent_client.review_treatment_plan` under the hood) returns a
    `ReviewResult` Pydantic model, not a raw dict, as of this round's
    refactor -- reads `result.usage.api_calls` (an attribute) accordingly.
    This check was `isinstance(result, dict)` before the refactor; left as
    a dict-shape fallback too so this wrapper still degrades safely (to the
    same "+1" floor, never silently to 0) if some future caller ever hands
    it a raw dict again instead of the typed contract.
    """
    def _wrapper(*args, **kwargs):
        if _real_api_call_counter.count >= MAX_REAL_API_CALLS_PER_SESSION:
            raise RuntimeError(
                f"BLOCKED by tests/conftest.py's real-API spend ceiling: "
                f"{MAX_REAL_API_CALLS_PER_SESSION} real Anthropic API call(s) already made "
                f"this pytest session (MAX_REAL_API_CALLS_PER_SESSION={MAX_REAL_API_CALLS_PER_SESSION}). "
                "Refusing to make another real call in this same session, even though this "
                "test is marked @pytest.mark.real_api -- a marker approves THAT test's own "
                "calls, not an unbounded session total. Raise MAX_REAL_API_CALLS_PER_SESSION "
                "explicitly, with the user's explicit per-instance approval for the higher "
                "count, if more real calls are genuinely needed for this run."
            )
        result = real_fn(*args, **kwargs)
        made = 1
        usage = getattr(result, "usage", None) if not isinstance(result, dict) else result.get("usage")
        api_calls = getattr(usage, "api_calls", None) if not isinstance(usage, dict) else usage.get("api_calls")
        if isinstance(api_calls, int):
            made = max(api_calls, 1)
        _real_api_call_counter.count += made
        print(f"[real-api-ceiling] real API calls this session: {_real_api_call_counter.count}/{MAX_REAL_API_CALLS_PER_SESSION}")
        return result

    return _wrapper


@pytest.fixture(autouse=True)
def _block_real_api_calls(request, monkeypatch):
    """Structural guardrail (Round 44) -- makes it impossible for ANY test in this
    suite to reach the real Anthropic API, regardless of which file runs or whether
    anyone read its fixtures first. Patches the exact seam app/rule_engine/client.py
    imports agent-making's real function into (`app.rule_engine.client.review_treatment_plan`
    -- the same patch target Round 42/43's own tests already used deliberately), so the
    call raises BEFORE any HTTP request is constructed -- not merely one that Anthropic
    would reject (an invalid/missing API key still sends a real request that reaches
    Anthropic's servers and gets a real 401/400 back, which is still a real call to the
    real API, just a failed one -- confirmed exactly this way last round, when zero
    credit produced a real, logged BadRequestError from Anthropic's own infrastructure).
    Patching the Python call site instead means zero bytes ever leave this machine
    toward Anthropic, for any test, by default.

    autouse + function-scoped: applies to every test automatically, re-armed fresh each
    test (monkeypatch reverts after each test regardless). The one escape hatch is
    `@pytest.mark.real_api` -- checked first, and when present this fixture doesn't
    block at all, but (Round 45) it DOES still wrap whatever real function is currently
    bound so every real call counts against the one shared session ceiling above.
    """
    if request.node.get_closest_marker("real_api") is not None:
        import app.rule_engine.client as client_module

        monkeypatch.setattr(
            client_module, "review_treatment_plan", _make_ceiling_enforced_real_call(client_module.review_treatment_plan),
        )
        yield
        return
    monkeypatch.setattr("app.rule_engine.client.review_treatment_plan", _blocked_review_treatment_plan)
    yield


@pytest.fixture()
def db_session(engine):
    """Plain session per test, bound to the shared test engine. Not wrapped
    in a rollback: routes hit via `client` open their own independent
    SessionLocal() connections (see app.db.base.get_db), so a rollback on
    THIS session wouldn't undo what a route handler committed through its
    own. Tests that create rows are expected to use unique natural keys
    (uuid-suffixed emails/rule_codes) so they don't collide with each other
    or with the seeded baseline — see helpers below.
    """
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def client():
    # Not using `with TestClient(app) as c:` deliberately — that would run
    # the app's lifespan, starting the real APScheduler jobs against the test
    # DB on a live timer, which is exactly the kind of background
    # nondeterminism a test suite must not have. Sync tick / retention /
    # stuck-job logic is tested by calling the service functions directly.
    return TestClient(app)


@pytest.fixture(scope="session")
def seeded_baseline(_recreated_test_database, engine):
    """Runs the real seed script functions once per test session (not a
    reimplementation of them) so steps 1-5's tests share one realistic
    baseline: 1 org, 5 users, 24 rules, app_config, Snapshot 0 +
    rule_sync_state. Returns {email: User} for the 5 seeded users.
    """
    from scripts.seed import seed_app_config, seed_organization, seed_rules, seed_snapshot_zero, seed_users

    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        seed_organization(session)
        users_by_email = seed_users(session)
        admin = users_by_email["m.chen@brightpath-aba.com"]
        seed_rules(session, actor_user_id=admin.id)
        seed_app_config(session)
        seed_snapshot_zero(session)
        return {email: user.id for email, user in users_by_email.items()}
    finally:
        session.close()


# Round 56: the default supporting_doc_mode changed from (the only mode
# that ever existed before) to "structured_form" -- POST /versions/:id/
# uploads now requires the 5 QA fields + a session_notes file by default,
# not `supporting_document`. Pre-existing tests across this suite each
# have their own private "_ready_upload"-style helper that only cares that
# SOME valid upload gets created, not which mode produced it -- rather
# than making every one of them mode-aware, they now send both this
# payload AND (where they already did) a supporting_document file in the
# same request; whichever branch the live mode actually reads is
# satisfied, and the other is simply ignored. Tests that specifically
# verify "document" mode's OWN required-file validation instead use the
# `document_mode` fixture below to switch mode for their own duration.
ROUND56_QA_FORM_DATA = {
    "client_insurance": "Aetna",
    "bcba_name_credentials_npi": "Jane Smith, BCBA-D — NPI 1234567890",
    "authorization_dates": "01/15/2026 – 07/15/2026",
    "pos_schedule_vs_97153_hours": "Home, Mon-Fri 5-8pm, 15 hrs/week",
    "hours_requesting": "15 hrs/week",
}


@pytest.fixture
def document_mode(db_session):
    """Switches supporting_doc_mode to "document" for the duration of one
    test, restoring the previous value afterward -- for tests that
    specifically exercise "document" mode's own required-file validation
    (e.g. "missing supporting_document -> 422"), where sending session-notes
    data alongside would default right past the very thing being tested.
    """
    from app.db.models import AppConfig

    config = db_session.execute(select(AppConfig)).scalar_one()
    original = config.supporting_doc_mode
    config.supporting_doc_mode = "document"
    db_session.commit()
    yield
    config = db_session.execute(select(AppConfig)).scalar_one()
    config.supporting_doc_mode = original
    db_session.commit()


def make_token(user_id: uuid.UUID, role: str) -> str:
    """Builds a JWT identical in shape to create_access_token, without going
    through the login endpoint — used where a test needs a token for a role
    combination login can't produce anymore (e.g. a since-demoted user).
    """
    from app.security import JWT_ALGORITHM

    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "role": role, "iat": now, "exp": now + timedelta(minutes=settings.jwt_expires_minutes)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def auth_headers(user_id: uuid.UUID, role: str) -> dict:
    return {"Authorization": f"Bearer {make_token(user_id, role)}"}


def login(client, email: str, password: str = DEV_PASSWORD):
    return client.post("/auth/login", data={"username": email, "password": password})


def login_headers(client, email: str, password: str = DEV_PASSWORD) -> dict:
    resp = login(client, email, password)
    assert resp.status_code == 200, f"login failed for {email}: {resp.status_code} {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def unique_email(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex[:8]}@test.local"


def unique_rule_code(prefix: str = "R-TEST") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def make_user(session, *, role: str, active: bool = True, password: str = DEV_PASSWORD):
    from app.db.models import User

    user = User(
        name=f"Test User {uuid.uuid4().hex[:6]}",
        email=unique_email(role),
        password_hash=hash_password(password),
        role=role,
        credential_title="BCBA",
        active=active,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def make_patient_version_upload(
    session,
    *,
    status: str = "processing",
    is_final: bool = False,
    file_purged: bool = False,
    purge_after=None,
    created_at=None,
    file_path=None,
    supporting_document_path=None,
    uploaded_by=None,
    rules_snapshot_id=None,
):
    """Builds the minimal Patient -> Version -> Upload chain step 5's job
    tests need. Direct model inserts, not a simulation of a real upload flow —
    step 5's job tests (sync tick / retention / stuck-job sweep) need uploads
    in specific, arbitrary states (e.g. stale `purge_after`, forced
    `file_purged`) that a real pipeline run wouldn't produce on demand; step
    6's own tests exercise the real create_upload/run_upload_pipeline path
    directly instead of using this helper.
    """
    from app.db.models import Patient, RuleSyncState, Upload, Version

    patient = Patient(reference_id=f"TP-TEST-{uuid.uuid4().hex[:8]}", name="Test Patient")
    session.add(patient)
    session.flush()

    version = Version(patient_id=patient.id, version_number=1, status="in_progress")
    session.add(version)
    session.flush()

    if rules_snapshot_id is None:
        sync_state = session.execute(select(RuleSyncState)).scalar_one()
        rules_snapshot_id = sync_state.current_snapshot_id

    upload = Upload(
        version_id=version.id,
        upload_number=1,
        is_final=is_final,
        file_purged=file_purged,
        purge_after=purge_after,
        file_path=file_path,
        supporting_document_path=supporting_document_path,
        rules_snapshot_id=rules_snapshot_id,
        status=status,
        uploaded_by=uploaded_by,
    )
    if created_at is not None:
        upload.created_at = created_at
    session.add(upload)
    session.commit()
    session.refresh(upload)
    return upload
