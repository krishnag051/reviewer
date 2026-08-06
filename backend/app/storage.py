import uuid
from pathlib import Path

from app.config import settings

# Round 58: settings.upload_storage_dir defaults to a RELATIVE path
# ("./data/uploads"), and every save_* function below used to do
# `Path(settings.upload_storage_dir)` directly -- resolved against
# whatever the SERVER PROCESS's OS-level working directory happened to be
# at the moment it ran, not anchored to this backend package. That's fine
# as long as every process is always launched with cwd=backend/, but a
# restart via a different launcher (a new terminal, a different working
# directory, a deploy script) can silently resolve it somewhere else --
# producing exactly Round 58's bug 2: a file that's genuinely on disk,
# genuinely not purged (file_purged=False in the DB), reported "no longer
# available" purely because the READING process's cwd drifted from the
# WRITING process's cwd. Anchoring to this file's own location (which
# never depends on cwd) closes that permanently, the same pattern
# app/rule_engine/client.py already uses for agent_making_agent_path.
_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _upload_storage_dir() -> Path:
    directory = Path(settings.upload_storage_dir)
    if not directory.is_absolute():
        directory = (_BACKEND_DIR / directory).resolve()
    return directory


def resolve_stored_path(stored_path: str) -> Path:
    """Every read site (GET .../file, .../supporting-file, .../session-
    notes/:file_id, and retention.py's delete_blob) must go through this,
    not a bare `Path(stored_path)` -- a row saved before this round's fix
    still has a RELATIVE string in it (e.g. "data\\uploads\\<id>.pdf"),
    which was always relative to the backend/ directory (every save_*
    call has only ever run with that as its intended base) regardless of
    what the reading process's own cwd happens to be. An already-absolute
    stored path (every row saved after this fix) passes through unchanged.
    """
    path = Path(stored_path)
    if not path.is_absolute():
        path = (_BACKEND_DIR / path).resolve()
    return path


def save_blob(upload_id: uuid.UUID, filename: str, content: bytes) -> str:
    """Placeholder local-filesystem-backed implementation — swap for the real
    S3/R2 client when object storage is wired up (see master doc §1). Named
    by upload_id, not the client-supplied filename, to avoid collisions and
    path-traversal from untrusted input. Returns the path to store as
    uploads.file_path -- always absolute now (see _upload_storage_dir above).
    """
    directory = _upload_storage_dir()
    directory.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix or ".pdf"
    path = directory / f"{upload_id}{suffix}"
    path.write_bytes(content)
    return str(path)


def save_supporting_blob(upload_id: uuid.UUID, filename: str, content: bytes) -> str:
    """Round 51 — the mandatory second ("supporting document") file every
    upload now requires. Deliberately a separate function rather than a
    parameter on save_blob: same directory/placeholder-implementation
    convention, but a `-supporting` suffix on the key keeps it from ever
    colliding with the TP's own blob (save_blob(upload_id, ...) alone,
    unchanged, still writes the TP's file at f"{upload_id}{suffix}").
    Returns the path to store as uploads.supporting_document_path.
    """
    directory = _upload_storage_dir()
    directory.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix or ".pdf"
    path = directory / f"{upload_id}-supporting{suffix}"
    path.write_bytes(content)
    return str(path)


def save_session_note_blob(upload_id: uuid.UUID, filename: str, content: bytes) -> str:
    """Round 56 — one call per uploaded session-note file (multi-file,
    unlike save_supporting_blob's single fixed slot). Named by upload_id +
    a random suffix rather than upload_id alone, since there can be more
    than one of these per upload and they must never collide with each
    other, the TP's own blob, or an old-mode supporting document blob.
    """
    directory = _upload_storage_dir()
    directory.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix or ".pdf"
    path = directory / f"{upload_id}-session-note-{uuid.uuid4().hex[:8]}{suffix}"
    path.write_bytes(content)
    return str(path)


def delete_blob(file_path: str) -> None:
    """Placeholder local-filesystem-backed implementation — swap for the real
    S3/R2 client when object storage is wired up. Callers depend only on:
    raises on real failure, returns normally on success. "Already gone" is
    treated as success (idempotent), since a retry after a prior run deleted
    the file but crashed before marking file_purged=true must not error.
    """
    path = resolve_stored_path(file_path)
    if not path.exists():
        return
    path.unlink()
