"""Round 58, Bug 2: a genuinely present, unpurged file was reported "file no
longer available" purely because the server process's cwd at request time
didn't match the process that originally saved it -- every save_* function
built its path off `Path(settings.upload_storage_dir)` (default
"./data/uploads", a RELATIVE string), and every read site did
`Path(stored_path).exists()` directly, both trusting whatever the CURRENT
process's cwd happened to be. Confirmed live: the DB row had file_purged=False
and the file was genuinely on disk, yet GET /uploads/:id/file 404'd.

None of the existing tests (test_upload_file_and_wiring.py,
test_supporting_document.py) ever caught this, because they all build their
fixture paths from pytest's `tmp_path`, which is always ABSOLUTE -- never
exercising the relative-path case production's own save_blob() actually
produces by default. This file specifically uses a RELATIVE path (relative
to the backend/ directory, matching what save_blob has always produced) to
close that gap.

Zero real Anthropic API calls anywhere in this file.
"""
import os

from app.storage import resolve_stored_path
from tests.conftest import login_headers, make_patient_version_upload


def test_resolve_stored_path_is_independent_of_process_cwd(tmp_path, monkeypatch):
    """The exact scenario that caused the live bug: a relative stored path
    must resolve to the same real file regardless of what directory the
    CURRENT process happens to be running from."""
    from app.storage import _BACKEND_DIR

    real_dir = _BACKEND_DIR / "data" / "uploads"
    real_dir.mkdir(parents=True, exist_ok=True)
    test_file = real_dir / "test-round58-resolve.pdf"
    test_file.write_bytes(b"%PDF-1.4\n(round 58 test)\n%%EOF")
    try:
        relative = os.path.join("data", "uploads", "test-round58-resolve.pdf")

        # From backend/ itself (the "correct" original cwd).
        monkeypatch.chdir(_BACKEND_DIR)
        assert resolve_stored_path(relative) == test_file.resolve()
        assert resolve_stored_path(relative).exists()

        # From somewhere else entirely -- simulates a server process
        # launched from a different working directory. Must resolve
        # identically, not silently "not found".
        monkeypatch.chdir(tmp_path)
        assert resolve_stored_path(relative) == test_file.resolve()
        assert resolve_stored_path(relative).exists()
    finally:
        test_file.unlink(missing_ok=True)


def test_resolve_stored_path_passes_through_an_already_absolute_path(tmp_path):
    """Every row saved after this fix stores an absolute path -- must pass
    through unchanged, not get re-anchored onto backend/."""
    real_file = tmp_path / "already-absolute.pdf"
    real_file.write_bytes(b"content")
    assert resolve_stored_path(str(real_file)) == real_file


def test_get_upload_file_serves_a_relative_legacy_style_path(client, db_session, seeded_baseline, monkeypatch):
    """End-to-end through the real route -- an upload row with a RELATIVE
    file_path (matching what every upload saved before this round's fix
    actually has stored) must still serve successfully, regardless of the
    running server process's own cwd at request time."""
    from app.storage import _BACKEND_DIR

    real_dir = _BACKEND_DIR / "data" / "uploads"
    real_dir.mkdir(parents=True, exist_ok=True)
    content = b"%PDF-1.4\n(round 58 legacy path test)\n%%EOF"
    test_file = real_dir / "test-round58-legacy.pdf"
    test_file.write_bytes(content)
    try:
        relative = os.path.join("data", "uploads", "test-round58-legacy.pdf")
        upload = make_patient_version_upload(db_session, status="ready", file_path=relative)
        headers = login_headers(client, "m.chen@brightpath-aba.com")

        resp = client.get(f"/uploads/{upload.id}/file", headers=headers)
        assert resp.status_code == 200
        assert resp.content == content
    finally:
        test_file.unlink(missing_ok=True)


def test_get_upload_file_still_404s_when_genuinely_purged(client, db_session, seeded_baseline):
    """Regression guard the other direction -- the fix must not paper over
    a REAL purge; file_purged=True must still 404 even if the file
    happens to still physically exist on disk."""
    from app.storage import _BACKEND_DIR

    real_dir = _BACKEND_DIR / "data" / "uploads"
    real_dir.mkdir(parents=True, exist_ok=True)
    test_file = real_dir / "test-round58-purged.pdf"
    test_file.write_bytes(b"content")
    try:
        relative = os.path.join("data", "uploads", "test-round58-purged.pdf")
        upload = make_patient_version_upload(db_session, status="ready", file_path=relative, file_purged=True)
        headers = login_headers(client, "m.chen@brightpath-aba.com")

        resp = client.get(f"/uploads/{upload.id}/file", headers=headers)
        assert resp.status_code == 404
    finally:
        test_file.unlink(missing_ok=True)
