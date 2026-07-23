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
