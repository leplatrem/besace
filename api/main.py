import asyncio
import datetime
import functools
import json
import os
import random
import shutil
import tempfile
import time
import zipfile
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Security
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import APIKeyHeader
from pydantic import AfterValidator


ROOT_FOLDER = os.path.abspath(os.getenv("BESACE_ROOT_FOLDER", "."))
RETENTION_DAYS = int(os.getenv("BESACE_RETENTION_DAYS", "7"))
CREATE_SECRETS = os.getenv("BESACE_CREATE_SECRETS", "s2cr2t,s3cr3t").split(",")
FOLDER_WORDS_MIN_LENGTH = 3
FOLDER_WORDS_MAX_LENGTH = 6
FOLDER_WORDS_COUNT = 3
BESACE_FOLDER_PATTERN = re.compile(f"^([a-zA-Z]+-){FOLDER_WORDS_COUNT - 1}[a-zA-Z]+$")
LOG_SECRET_REVEAL_LENGTH = int(os.getenv("LOG_SECRET_REVEAL_LENGTH", "3"))
INVALID_SECRET_WAIT_SECONDS = int(os.getenv("INVALID_SECRET_WAIT_SECONDS", "2"))


api_secret_header = APIKeyHeader(name="Authorization")


async def check_api_secret(
    api_key_header: str = Security(api_secret_header),
) -> str:
    try:
        _type, secret = api_key_header.split(" ", 1)
    except ValueError:
        secret = None
    if secret in CREATE_SECRETS:
        print(f"Using secret '{secret[:LOG_SECRET_REVEAL_LENGTH]}..'")
        return secret
    # Let's slow down retries here...
    await asyncio.sleep(INVALID_SECRET_WAIT_SECONDS)
    raise HTTPException(
        status_code=401,
        detail="Invalid or missing API Secret",
    )


def check_folder_id(folder_id: str) -> str:
    assert BESACE_FOLDER_PATTERN.match(folder_id), f"{folder_id} has bad format"
    return folder_id


FolderIdValidator = Path(annotation=Annotated[str, AfterValidator(check_folder_id)])


def check_filename(filename: str) -> str:
    assert re.match(r'^[^<>:;?"*|/]+$', filename), f"{filename} has bad format"
    return filename


FilenameValidator = Path(annotation=Annotated[str, AfterValidator(check_filename)])


def startup_check():
    print(f"Using {ROOT_FOLDER!r} as root folder")
    # Test that root is writable.
    os.makedirs(ROOT_FOLDER, exist_ok=True)
    testfile = tempfile.TemporaryFile(dir=ROOT_FOLDER)
    testfile.close()


def get_folder_metadata(folder_id):
    metadata_file = os.path.join(ROOT_FOLDER, f"{folder_id}.meta")
    if not os.path.exists(metadata_file):
        # Fallback if folder was created with old Besace versions.
        folder = os.path.join(ROOT_FOLDER, folder_id)
        return {
            "created": os.path.getmtime(folder),
        }
    with open(metadata_file) as f:
        metadata = json.load(f)
    return metadata


def purge_old_folders():
    now = datetime.datetime.today()
    folders = [
        (f, get_folder_metadata(f)["created"])
        for f in os.listdir(ROOT_FOLDER)
        if os.path.isdir(os.path.join(ROOT_FOLDER, f))
    ]
    print(f"{len(folders)} folders in {ROOT_FOLDER}")
    for folder, timestamp in folders:
        dt = datetime.datetime.fromtimestamp(timestamp)
        if (age := (now - dt).days) > RETENTION_DAYS:
            print(f"Purging old folder {folder} (age={age})")
            delete_folder(folder_id=folder, _secret="")


@functools.cache
def load_dictionnary():
    here = os.path.dirname(os.path.abspath(__file__))
    dictionary_path = os.path.join(here, "dictionnary.txt")
    with open(dictionary_path) as f:
        words = f.read().splitlines()
    selection = [
        w
        for w in words
        if FOLDER_WORDS_MIN_LENGTH <= len(w) <= FOLDER_WORDS_MAX_LENGTH and "_" not in w
    ]
    size = len(selection)
    print(
        f"Loaded dictionary of {size} words ({size ** FOLDER_WORDS_COUNT} possibilities)."
    )
    return selection


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_check()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/")
def read_root(request: Request):
    root_url = request.url_for("read_root")
    return {
        "Hello": "World",
        "root_path": request.scope.get("root_path"),
        "root_url": str(root_url),
    }


@app.post("/folder")
def create_folder(
    request: Request,
    user_agent: Annotated[str | None, Header()],
    dictionnary: list[str] = Depends(load_dictionnary),
    secret: str = Security(check_api_secret),
):
    purge_old_folders()

    while "new folder does not exist":
        words = random.sample(dictionnary, FOLDER_WORDS_COUNT)
        folder_id = "-".join(words)
        folder_dir = os.path.join(ROOT_FOLDER, folder_id)
        if not os.path.exists(folder_dir):
            break

    os.makedirs(folder_dir, exist_ok=True)
    metadata = {
        "created": int(time.time()),
        "host": request.client.host,
        "user-agent": user_agent,
        "secret": f"{secret[:LOG_SECRET_REVEAL_LENGTH]}...",
    }
    with open(os.path.join(ROOT_FOLDER, f"{folder_id}.meta"), "w") as f:
        json.dump(metadata, f)

    print(f"Created new folder {folder_dir!r}")
    redirect_url = request.url_for("get_folder", **{"folder_id": str(folder_id)})
    return RedirectResponse(redirect_url, status_code=303)


@app.get("/folder/{folder_id}")
def get_folder(folder_id: str = FolderIdValidator):
    folder_dir = os.path.join(ROOT_FOLDER, folder_id)
    if not os.path.exists(folder_dir):
        raise HTTPException(status_code=404, detail=f"Unknown folder {folder_id!r}")

    filepaths = [(os.path.join(folder_dir, f), f) for f in os.listdir(folder_dir)]
    files = [
        {"filename": f, "size": os.path.getsize(fp), "modified": os.path.getmtime(fp)}
        for fp, f in filepaths
        if os.path.isfile(fp)
    ]
    return {
        **get_folder_metadata(folder_id),
        "folder": folder_id,
        "files": sorted(files, key=lambda v: v["modified"], reverse=True),
        "settings": {
            "retention_days": RETENTION_DAYS,
        },
    }


@app.get("/folder/{folder_id}/download")
def get_folder_archive(folder_id: str = FolderIdValidator):
    folder_dir = os.path.join(ROOT_FOLDER, folder_id)
    if not os.path.exists(folder_dir):
        raise HTTPException(status_code=404, detail=f"Unknown folder {folder_id!r}")

    filenames = [
        f for f in os.listdir(folder_dir) if os.path.isfile(os.path.join(folder_dir, f))
    ]
    folder_archive = os.path.join(ROOT_FOLDER, f"{folder_id}.zip")
    print(f"Updating archive {folder_archive!r}")
    with zipfile.ZipFile(folder_archive, "a") as archive:
        existing = archive.namelist()
        for filename in filenames:
            if filename not in existing:
                archive.write(os.path.join(folder_dir, filename), filename)

    headers = {"Content-Disposition": f'attachment; filename="{folder_id}.zip"'}
    return FileResponse(folder_archive, headers=headers)


@app.delete("/folder/{folder_id}")
def delete_folder(folder_id: str = FolderIdValidator, _secret: str = Security(check_api_secret)):
    folder_dir = os.path.join(ROOT_FOLDER, folder_id)
    if not os.path.exists(folder_dir):
        raise HTTPException(status_code=404, detail=f"Unknown folder {folder_id!r}")
    shutil.rmtree(folder_dir)
    try:
        os.remove(os.path.join(ROOT_FOLDER, f"{folder_id}.zip"))
    except FileNotFoundError:
        # Archive was never requested.
        pass
    try:
        os.remove(os.path.join(ROOT_FOLDER, f"{folder_id}.md5"))
    except FileNotFoundError:
        # No file added to the folder (md5 happens in hook).
        pass
    try:
        os.remove(os.path.join(ROOT_FOLDER, f"{folder_id}.meta"))
    except FileNotFoundError:
        # Folder was created with older version.
        pass
    print(f"Deleted folder {folder_dir!r}")
    return {}


@app.get("/file/{folder_id}/{file_name}")
def fetch_file(folder_id: str = FolderIdValidator, file_name: str = FilenameValidator):
    folder_dir = os.path.join(ROOT_FOLDER, folder_id)
    file = os.path.join(folder_dir, file_name)
    headers = {"Content-Disposition": f'attachment; filename="{file_name}"'}
    return FileResponse(file, headers=headers)
