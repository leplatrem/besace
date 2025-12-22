# tests/test_thumbnailer.py
import importlib
import io
import os
from pathlib import Path
import sys
import types
import time
import numpy as np

import pytest
from PIL import Image

# Ensure project root is importable when tests run from inside tests/
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class DummyEvent:
    def __init__(self, src_path: str, is_directory: bool):
        self.src_path = src_path
        self.is_directory = is_directory


class DummyVideoFileClip:
    def __init__(self, path):
        # Simulate a short clip
        self.path = path
        self.duration = 3.7

    def get_frame(self, t):
        # Return a tiny RGB **NumPy array** as a frame (what Image.fromarray expects)
        return np.asarray(Image.new("RGB", (16, 9), color=(10, 20, 30)))


class DummyPix:
    def __init__(self, w=20, h=30):
        self.width = w
        self.height = h
        # simple gray buffer
        self.samples = bytes([180] * (w * h * 3))


class DummyPage:
    def get_pixmap(self):
        return DummyPix()


class DummyDoc:
    def __init__(self, path):
        self.path = path

    def load_page(self, _index):
        return DummyPage()


@pytest.fixture()
def stub_deps(monkeypatch):
    """
    Provide lightweight stubs for optional/expensive third-party modules so the module
    can import cleanly and we can assert behavior without the real dependencies.
    """
    # pillow_heif.register_heif_opener
    ph = types.ModuleType("pillow_heif")
    ph.register_heif_opener = lambda: None
    sys.modules["pillow_heif"] = ph

    # moviepy.editor.VideoFileClip
    moviepy = types.ModuleType("moviepy")
    moviepy.VideoFileClip = DummyVideoFileClip
    sys.modules["moviepy"] = moviepy

    # fitz (PyMuPDF)
    fitz = types.ModuleType("fitz")
    fitz.open = lambda path: DummyDoc(path)
    sys.modules["fitz"] = fitz


@pytest.fixture()
def module(tmp_path, monkeypatch, stub_deps):
    """
    Import the target module with test-friendly tweaks:
    - point assets (default thumbnail & font) to temp files
    - make file-complete polling instant
    - ensure HERE resolves to tmp so DEFAULT_THUMBNAIL path exists
    """
    # Create a tiny default thumbnail and a dummy "font" file.
    assets = tmp_path / "assets"
    assets.mkdir()
    default_img = assets / "default.jpg"
    Image.new("RGB", (64, 64), color=(200, 200, 200)).save(default_img)
    dummy_font = assets / "DejaVuSansCondensed-Bold.ttf"
    dummy_font.write_bytes(b"\0")  # we will monkeypatch truetype to ignore this

    # Ensure Python finds the module under test next to the tests
    # Replace 'thumbnailer' with your actual module filename (no .py)
    import thumbnailer  # noqa: F401

    importlib.reload(thumbnailer)

    # Point asset constants to temp ones
    monkeypatch.setattr(
        thumbnailer, "DEFAULT_THUMBNAIL", str(default_img), raising=True
    )
    monkeypatch.setattr(thumbnailer, "FONT_FILE", str(dummy_font), raising=True)

    # Make file-complete wait loops instant
    monkeypatch.setattr(thumbnailer, "FILE_COMPLETE_WAIT_SECONDS", 0, raising=True)

    # Avoid truetype dependency on a real font file
    import PIL.ImageFont as IF

    # Always use a safe bitmap font in tests
    monkeypatch.setattr(
        thumbnailer.ImageFont,
        "truetype",
        lambda *_a, **_k: IF.load_default(),
        raising=True,
    )

    # No-op the text overlay to avoid platform font/freetype recursion issues
    class _NoopDraw:
        def __init__(self, _img):
            pass

        def text(self, *args, **kwargs):
            pass

    monkeypatch.setattr(
        thumbnailer.ImageDraw, "Draw", lambda img: _NoopDraw(img), raising=True
    )

    return thumbnailer


@pytest.fixture()
def io_dirs(tmp_path):
    src = tmp_path / "in"
    dst = tmp_path / "thumbs"
    src.mkdir()
    dst.mkdir()
    return src, dst


def test_besace_folder_pattern_accepts_common_ids(module):
    ok = [
        "oak-lime-pine",
        "Alpha-Beta-charlie",
        "a-b-ccc",
    ]
    for s in ok:
        assert module.BESACE_FOLDER_PATTERN.match(s), s


def test_besace_folder_pattern_rejects_invalid(module):
    bad = [
        "single-dash",
        "11-numeric-start",
        "foo_",  # trailing underscore
        "UPPER-",  # trailing dash
    ]
    for s in bad:
        assert not module.BESACE_FOLDER_PATTERN.match(s), s


def test_fail_safe_decorator_catches_and_prints(module, capsys):
    calls = {"ok": 0, "boom": 0}

    @module.fail_safe
    def ok(x):
        calls["ok"] += x

    @module.fail_safe
    def boom():
        calls["boom"] += 1
        raise RuntimeError("explode")

    ok(3)
    boom()
    out = capsys.readouterr().out
    assert "boom()" in out or "boom(" in out  # prints function & args
    assert calls["ok"] == 3
    assert calls["boom"] == 1  # increment happened even though error was caught


def _read_image(path):
    with Image.open(path) as im:
        im.load()
        return im.size, im.mode


def test_create_thumbnail_from_image(module, tmp_path):
    src = tmp_path / "img.jpg"
    Image.new("RGB", (800, 600), color=(10, 10, 10)).save(src)
    out = tmp_path / "out" / "thumb.jpg"

    module.create_thumbnail(str(src), str(out), (128, 128), frame_time=1.0)

    assert out.is_file()
    size, mode = _read_image(out)
    assert max(size) <= 128
    assert mode == "RGB"


# def test_create_thumbnail_from_video_stub(module, tmp_path):
#     src = tmp_path / "clip.mp4"
#     src.write_bytes(b"fake-video")
#     out = tmp_path / "out" / "thumb.jpg"

#     module.create_thumbnail(str(src), str(out), (128, 128), frame_time=1.0)

#     assert out.is_file()
#     size, _ = _read_image(out)
#     assert max(size) <= 128  # was thumbnailed
#     # We also drew a duration overlay; no easy pixel assertion, file existence suffices.


def test_create_thumbnail_from_pdf_stub(module, tmp_path):
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    out = tmp_path / "out" / "thumb.jpg"

    module.create_thumbnail(str(src), str(out), (64, 64), frame_time=0.0)

    assert out.is_file()
    size, _ = _read_image(out)
    assert max(size) <= 64


# def test_create_thumbnail_unknown_ext_uses_default_background(module, tmp_path):
#     src = tmp_path / "file.xyz"
#     src.write_bytes(b"blob")
#     out = tmp_path / "out" / "thumb.jpg"

#     module.create_thumbnail(str(src), str(out), (64, 64), frame_time=0.0)
#     assert out.is_file()
#     # It drew text with extension; we won't OCR it—existence is enough.


def test_watch_handler_on_created_directory_makes_thumb_folder(module, io_dirs):
    src, dst = io_dirs
    # create a "besace" folder
    folder = src / "oak-lime-pine"
    evt = DummyEvent(str(folder), is_directory=True)

    h = module.WatchHandler(str(dst), (64, 64), 1.0, ".jpg")
    h.on_created(evt)

    assert (dst / "oak-lime-pine").is_dir()


def test_watch_handler_on_created_file_creates_thumbnail(module, io_dirs):
    src, dst = io_dirs
    folder = src / "oak-lime-pine"
    folder.mkdir()
    (dst / "oak-lime-pine").mkdir()  # as if the dir event happened already

    # Write a real image file, then simulate the event
    img_path = folder / "pic.png"
    Image.new("RGB", (200, 100), color=(90, 90, 90)).save(img_path)

    evt = DummyEvent(str(img_path), is_directory=False)
    h = module.WatchHandler(str(dst), (40, 40), 0.0, ".jpg")
    # FILE_COMPLETE_WAIT_SECONDS is patched to 0 in fixture, so loop is instant
    h.on_created(evt)

    out = dst / "oak-lime-pine" / "pic.png.jpg"
    assert out.is_file()
    size, _ = _read_image(out)
    assert max(size) <= 40


def test_watch_handler_ignores_non_besace_paths(module, io_dirs, capsys):
    src, dst = io_dirs
    bad_folder = src / "not-valid"
    evt_dir = DummyEvent(str(bad_folder), is_directory=True)

    h = module.WatchHandler(str(dst), (64, 64), 1.0, ".jpg")
    h.on_created(evt_dir)
    out = capsys.readouterr().out
    assert "Ignore" in out
    assert not (dst / "not-valid").exists()


def test_watch_handler_on_deleted_removes_thumbnail_folder(module, io_dirs):
    src, dst = io_dirs
    folder = src / "oak-lime-pine"
    thumb_folder = dst / "oak-lime-pine"
    folder.mkdir()
    thumb_folder.mkdir()

    evt = DummyEvent(str(folder), is_directory=True)
    h = module.WatchHandler(str(dst), (64, 64), 1.0, ".jpg")
    h.on_deleted(evt)

    assert not thumb_folder.exists()


def test_main_runs_sync_on_start_and_exits_cleanly(
    module, tmp_path, monkeypatch, capsys
):
    # Prepare input tree with a matching folder and a file
    src = tmp_path / "in"
    out = tmp_path / "thumbs"
    (src / "oak-lime-pine").mkdir(parents=True)
    out.mkdir()
    img_in = src / "oak-lime-pine" / "seed.jpg"
    Image.new("RGB", (120, 80), color=(50, 60, 70)).save(img_in)

    # Force SYNC_ON_START True for this run
    monkeypatch.setattr(module, "SYNC_ON_START", True, raising=True)

    # Provide args via parse_arguments() stub
    Args = type(
        "Args",
        (),
        dict(
            input=str(src),
            output=str(out),
            width=64,
            height=64,
            frame_time=0.0,
            extension=".jpg",
        ),
    )
    monkeypatch.setattr(module, "parse_arguments", lambda: Args, raising=True)

    # Stub Observer with a controllable dummy that records calls
    calls = {"schedule": 0, "start": 0, "stop": 0, "join": 0}

    class DummyObserver:
        def schedule(self, handler, path, recursive):
            calls["schedule"] += 1

        def start(self):
            calls["start"] += 1

        def stop(self):
            calls["stop"] += 1

        def join(self):
            calls["join"] += 1

    monkeypatch.setattr(module, "Observer", DummyObserver, raising=True)

    # Make the loop exit immediately by raising KeyboardInterrupt on first sleep
    slept = {"n": 0}

    def _sleep(_s):
        if slept["n"] == 0:
            slept["n"] += 1
            raise KeyboardInterrupt()
        time.sleep(0)  # pragma: no cover

    monkeypatch.setattr(module, "time", types.SimpleNamespace(sleep=_sleep))

    # Run main()
    module.main()

    # Sync created the thumbnail before the watcher loop started
    thumb = out / "oak-lime-pine" / "seed.jpg.jpg"
    assert thumb.is_file(), "sync-on-start should have created this thumbnail"
    # Observer lifecycle methods called
    assert calls == {"schedule": 1, "start": 1, "stop": 1, "join": 1}
