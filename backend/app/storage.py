import uuid
from pathlib import Path

from app.config import settings


def save_blob(upload_id: uuid.UUID, filename: str, content: bytes) -> str:
    """Placeholder local-filesystem-backed implementation — swap for the real
    S3/R2 client when object storage is wired up (see master doc §1). Named
    by upload_id, not the client-supplied filename, to avoid collisions and
    path-traversal from untrusted input. Returns the path to store as
    uploads.file_path.
    """
    directory = Path(settings.upload_storage_dir)
    directory.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix or ".pdf"
    path = directory / f"{upload_id}{suffix}"
    path.write_bytes(content)
    return str(path)


def delete_blob(file_path: str) -> None:
    """Placeholder local-filesystem-backed implementation — swap for the real
    S3/R2 client when object storage is wired up. Callers depend only on:
    raises on real failure, returns normally on success. "Already gone" is
    treated as success (idempotent), since a retry after a prior run deleted
    the file but crashed before marking file_purged=true must not error.
    """
    path = Path(file_path)
    if not path.exists():
        return
    path.unlink()
