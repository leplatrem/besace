# tests/test_besace.py
import importlib
import io
import json
import os
import re
import sys
import functools
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# Ensure project root is importable when tests run from inside tests/
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture()
def app_env(monkeypatch, tmp_path):
    """
    Configure environment so the app uses an isolated, temp root folder and fast tests.
    IMPORTANT: import your module only AFTER setting env, since it reads env at import time.
    """
    monkeypatch.setenv("BESACE_ROOT_FOLDER", str(tmp_path))
    # Make purging easy to trigger in tests
    monkeypatch.setenv("BESACE_RETENTION_DAYS", "0")
    # Don’t slow down 401 tests
    monkeypatch.setenv("INVALID_SECRET_WAIT_SECONDS", "0")

    # Use small reveal length to assert metadata secret masking
    monkeypatch.setenv("LOG_SECRET_REVEAL_LENGTH", "3")

    # Ensure deterministic dictionary and folder name lengths
    monkeypatch.setenv("BESACE_CREATE_SECRETS", "s2cr2t,s3cr3t")

    # No wait in bad auth
    monkeypatch.setenv("BESACE_INVALID_SECRET_WAIT_SECONDS", "0")

    # Import *after* env is set:
    import main  # noqa: F401

    importlib.reload(main)
    return main


@pytest.fixture()
def client(app_env):
    """
    Create a TestClient that runs lifespan (startup_check) so root dir is writable.
    """
    return TestClient(app_env.app, follow_redirects=False)


@pytest.fixture()
def auth_header():
    # Default secret from env: s2cr2t,s3cr3t — we’ll use s2cr2t.
    return {"Authorization": "Bearer s2cr2t"}


def read_zip_names(zip_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        return set(zf.namelist())


def test_root_endpoint(client):
    res = client.get("/")
    assert res.status_code == 200
    body = res.json()
    # Minimal sanity checks
    assert body["Hello"] == "World"
    # root_url should be the GET "/" url
    assert body["root_url"].endswith("/")


def test_auth_missing_is_403(client):
    # Missing header is handled by APIKeyHeader itself
    res = client.post("/folder")
    assert res.status_code == 401
    assert res.json()["detail"] in ("Not authenticated", "Forbidden")


def test_auth_bad_secret_is_401(client):
    # Header present, but with a wrong secret → handled by check_api_secret
    res = client.post("/folder", headers={"Authorization": "Bearer WRONG"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid or missing API Secret"


def test_create_folder_redirects_and_writes_metadata(client, app_env, auth_header):
    # Force deterministic folder id by patching random.sample
    # The app uses 3 words; these short words also satisfy default min/max lengths.
    words = ["oak", "lime", "pine"]

    def _fake_sample(seq, k):  # pragma: no cover - trivial stub
        assert k == 3
        return words

    app_env.random_sample_original = app_env.random.sample
    try:
        app_env.random.sample = _fake_sample  # monkeypatch at module level

        # Also patch the loaded dictionary to something containing our words.
        def _fake_dict():
            return ["oak", "lime", "pine", "birch", "spruce"]

        app_env.load_dictionnary.cache_clear()
        app_env.load_dictionnary.__wrapped__ = _fake_dict  # bypass cache decorator
        app_env.load_dictionnary = functools.cache(_fake_dict)  # type: ignore

        headers = {"User-Agent": "pytest-agent", **auth_header}
        res = client.post("/folder", headers=headers)
        assert res.status_code == 303
        assert res.headers["location"].endswith("/folder/oak-lime-pine")

        # Check folder and .meta
        root = Path(app_env.ROOT_FOLDER)
        folder = root / "oak-lime-pine"
        meta = root / "oak-lime-pine.meta"
        assert folder.is_dir(), "Folder should be created"
        assert meta.is_file(), "Metadata should be created"
        meta_data = json.loads(meta.read_text())
        assert meta_data["user-agent"] == "pytest-agent"
        # Secret is masked with reveal length (3) + '...'
        assert re.fullmatch(r"s2c\.\.\.", meta_data["secret"])
    finally:
        # Restore random.sample if we changed it
        app_env.random.sample = app_env.random_sample_original


def test_get_folder_lists_files_and_settings(client, app_env, auth_header):
    # Create one folder via API (also exercises purge_old_folders with retention=0)
    res = client.post("/folder", headers=auth_header)
    assert res.status_code == 303
    folder_url = res.headers["location"]
    folder_id = folder_url.rsplit("/", 1)[-1]

    # Place two files into the folder, with different mtimes
    folder = Path(app_env.ROOT_FOLDER) / folder_id
    f1 = folder / "a.txt"
    f2 = folder / "b.txt"
    f1.write_text("A")
    time.sleep(0.01)
    f2.write_text("BB")

    res = client.get(f"/folder/{folder_id}")
    assert res.status_code == 200
    body = res.json()

    assert body["folder"] == folder_id
    assert isinstance(body["created"], int)
    assert body["settings"]["retention_days"] == int(
        os.getenv("BESACE_RETENTION_DAYS", "7")
    )
    # Files sorted by modified desc
    assert [f["filename"] for f in body["files"]] == ["b.txt", "a.txt"]


def test_download_archive_is_idempotent_and_has_disposition(
    client, app_env, auth_header
):
    # Create folder
    res = client.post("/folder", headers=auth_header)
    assert res.status_code == 303
    folder_id = res.headers["location"].rsplit("/", 1)[-1]
    folder = Path(app_env.ROOT_FOLDER) / folder_id

    # Create files
    (folder / "x.bin").write_bytes(b"xxx")
    (folder / "y.bin").write_bytes(b"yyyy")

    # First archive build
    res1 = client.get(f"/folder/{folder_id}/download")
    assert res1.status_code == 200
    assert res1.headers["content-disposition"].endswith(f'{folder_id}.zip"')
    names1 = read_zip_names(res1.content)
    assert names1 == {"x.bin", "y.bin"}

    # Second archive build (should not duplicate)
    res2 = client.get(f"/folder/{folder_id}/download")
    assert res2.status_code == 200
    names2 = read_zip_names(res2.content)
    assert names2 == {"x.bin", "y.bin"}


def test_fetch_file_returns_attachment(client, app_env, auth_header):
    res = client.post("/folder", headers=auth_header)
    assert res.status_code == 303
    folder_id = res.headers["location"].rsplit("/", 1)[-1]
    folder = Path(app_env.ROOT_FOLDER) / folder_id
    (folder / "note.md").write_text("# hello")

    res = client.get(f"/file/{folder_id}/note.md")
    assert res.status_code == 200
    assert res.headers["content-disposition"].endswith('note.md"')
    assert res.text == "# hello"


def test_delete_folder_removes_dir_and_artifacts(client, app_env, auth_header):
    # Create folder and trigger archive creation so .zip exists
    res = client.post("/folder", headers=auth_header)
    assert res.status_code == 303
    folder_id = res.headers["location"].rsplit("/", 1)[-1]

    # Touch a file then request archive
    folder = Path(app_env.ROOT_FOLDER) / folder_id
    (folder / "t.txt").write_text("t")
    res_zip = client.get(f"/folder/{folder_id}/download")
    assert res_zip.status_code == 200

    # Delete
    res_del = client.delete(f"/folder/{folder_id}", headers=auth_header)
    assert res_del.status_code == 200
    # Folder and sidecars gone
    assert not folder.exists()
    assert not (Path(app_env.ROOT_FOLDER) / f"{folder_id}.zip").exists()
    assert not (Path(app_env.ROOT_FOLDER) / f"{folder_id}.meta").exists()
    # .md5 may or may not exist; delete path is covered by API


def test_validation_bad_folder_id_yields_422(client):
    # Fails FolderIdValidator (non-matching pattern)
    res = client.get("/folder/NOPE_not-valid")
    assert res.status_code == 422  # Pydantic validation error


def test_validation_bad_filename_yields_422(client, auth_header):
    # Make one folder
    res = client.post("/folder", headers=auth_header)
    assert res.status_code == 303
    folder_id = res.headers["location"].rsplit("/", 1)[-1]

    # Forbidden characters include /, ?, *, etc.
    res = client.get(f"/file/{folder_id}/bad:name?.txt")
    assert res.status_code == 422


def test_unauthorized_delete_is_401(client):
    # Even if the folder existed, passing no/bad secret yields 401
    res = client.delete(
        "/folder/oak-lime-pine", headers={"Authorization": "Bearer WRONG"}
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid or missing API Secret"
