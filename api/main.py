from contextlib import asynccontextmanager
import datetime
import functools
import os
import random
import shutil
import tempfile
import zipfile

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import APIKeyHeader


ROOT_FOLDER = os.path.abspath(os.getenv("BESACE_ROOT_FOLDER", "."))
RETENTION_DAYS = int(os.getenv("BESACE_RETENTION_DAYS", "7"))
CREATE_SECRETS = os.getenv("BESACE_CREATE_SECRETS", "s2cr2t,s3cr3t").split(",")
FOLDER_WORDS_MIN_LENGTH = 3
FOLDER_WORDS_MAX_LENGTH = 6
FOLDER_WORDS_COUNT = 3


api_secret_header = APIKeyHeader(name="Authorization")


def check_api_secret(
    api_key_header: str = Security(api_secret_header),
) -> str:
    try:
        _type, secret = api_key_header.split(" ", 1)
    except ValueError:
        secret = None
    if secret in CREATE_SECRETS:
        return api_key_header
    raise HTTPException(
        status_code=401,
        detail="Invalid or missing API Secret",
    )


def startup_check():
    print(f"Using {ROOT_FOLDER!r} as root folder")
    # Test that root is writable.
    os.makedirs(ROOT_FOLDER, exist_ok=True)
    testfile = tempfile.TemporaryFile(dir=ROOT_FOLDER)
    testfile.close()


def purge_old_folders():
    now = datetime.datetime.today()
    folders = [
        (f, os.path.getmtime(os.path.join(ROOT_FOLDER, f)))
        for f in os.listdir(ROOT_FOLDER)
        if os.path.isdir(f)
    ]
    for folder, timestamp in folders:
        dt = datetime.datetime.fromtimestamp(timestamp)
        if age := (now - dt).days > RETENTION_DAYS:
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
    dictionnary: list[str] = Depends(load_dictionnary),
    _secret: str = Security(check_api_secret),
):
    purge_old_folders()

    while "new folder does not exist":
        words = random.sample(dictionnary, FOLDER_WORDS_COUNT)
        folder_id = "-".join(words)
        folder_dir = os.path.join(ROOT_FOLDER, folder_id)
        if not os.path.exists(folder_dir):
            break

    os.makedirs(folder_dir, exist_ok=True)
    print(f"Created new folder {folder_dir!r}")
    redirect_url = request.url_for("get_folder", **{"folder_id": str(folder_id)})
    return RedirectResponse(redirect_url, status_code=303)


@app.get("/folder/{folder_id}")
def get_folder(folder_id: str):
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
        "folder": folder_id,
        "files": sorted(files, key=lambda v: v["modified"], reverse=True),
    }


@app.get("/folder/{folder_id}/download")
def get_folder_archive(folder_id: str):
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
        # TODO: check modified timestamp
        for filename in filenames:
            if filename not in existing:
                archive.write(os.path.join(folder_dir, filename), filename)

    headers = {"Content-Disposition": f'attachment; filename="{folder_id}.zip"'}
    return FileResponse(folder_archive, headers=headers)


@app.delete("/folder/{folder_id}")
def delete_folder(folder_id: str, _secret: str = Security(check_api_secret)):
    folder_dir = os.path.join(ROOT_FOLDER, folder_id)
    if not os.path.exists(folder_dir):
        raise HTTPException(status_code=404, detail=f"Unknown folder {folder_id!r}")
    shutil.rmtree(folder_dir)
    try:
        os.remove(os.path.join(ROOT_FOLDER, f"{folder_id}.zip"))
    except FileNotFoundError:
        # Archive was never requested.
        pass
    print(f"Deleted folder {folder_dir!r}")
    return {}
