from contextlib import asynccontextmanager
import os
import shutil
import tempfile
from uuid import uuid4
import zipfile

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

import uvicorn


root_folder = os.path.abspath(os.getenv("BESACE_ROOT_FOLDER"))


def startup_check():
    print(f"Using {root_folder!r} as root folder")
    # Test that root is writable.
    os.makedirs(root_folder, exist_ok=True)
    testfile = tempfile.TemporaryFile(dir=root_folder)
    testfile.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_check()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/")
def read_root(request: Request):
    return {
        "Hello": "World",
        "root_path": request.scope.get("root_path"),
    }


@app.get("/folder/{folder_id}")
def get_folder(folder_id: str):
    folder_dir = os.path.join(root_folder, folder_id)
    if not os.path.exists(folder_dir):
        raise HTTPException(status_code=404, detail=f"Unknown folder {folder_id!r}")
    filenames = [
        f for f in os.listdir(folder_dir) if os.path.isfile(os.path.join(folder_dir, f))
    ]
    return {
        "folder": folder_id,
        "files": filenames,
    }


@app.get("/folder/{folder_id}.zip")
def get_folder_archive(folder_id: str):
    folder_dir = os.path.join(root_folder, folder_id)
    if not os.path.exists(folder_dir):
        raise HTTPException(status_code=404, detail=f"Unknown folder {folder_id!r}")

    filenames = [
        f for f in os.listdir(folder_dir) if os.path.isfile(os.path.join(folder_dir, f))
    ]
    folder_archive = os.path.join(root_folder, f"{folder_id}.zip")
    print(f"Updating archive {folder_archive!r}")
    with zipfile.ZipFile(folder_archive, "a") as archive:
        existing = archive.namelist()
        for filename in filenames:
            if filename not in existing:
                archive.write(filename)

    headers = {"Content-Disposition": f'attachment; filename="{folder_id}.zip"'}
    return FileResponse(folder_archive, headers=headers)


@app.post("/folder")
def create_folder(request: Request):
    folder_id = uuid4()
    folder_dir = os.path.join(root_folder, str(folder_id))
    os.makedirs(folder_dir, exist_ok=True)
    print(f"Created new folder {folder_dir!r}")
    redirect_url = request.url_for("get_folder", **{"folder_id": str(folder_id)})
    return RedirectResponse(redirect_url, status_code=303)


@app.delete("/folder/{folder_id}")
def delete_folder(folder_id: str):
    folder_dir = os.path.join(root_folder, folder_id)
    if not os.path.exists(folder_dir):
        raise HTTPException(status_code=404, detail=f"Unknown folder {folder_id!r}")
    shutil.rmtree(folder_dir)
    try:
        os.remove(os.path.join(root_folder, f"{folder_id}.zip"))
    except FileNotFoundError:
        pass
    print(f"Deleted folder {folder_dir!r}")
    return {}
