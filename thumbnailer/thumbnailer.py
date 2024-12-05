import argparse
import re
import os
import shutil
import time

from PIL import Image, ImageFont, ImageDraw
from moviepy.editor import VideoFileClip
from pillow_heif import register_heif_opener
import fitz  # PyMuPDF
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


BESACE_FOLDER_PATTERN = re.compile(r"^([a-zA-Z]+-)+\w[a-zA-Z]+$")
FILE_COMPLETE_WAIT_SECONDS = 1
HERE = os.path.dirname(__file__)
DEFAULT_THUMBNAIL = os.path.join(HERE, "default.jpg")
FONT_FILE = os.path.join(HERE, "DejaVuSansCondensed-Bold.ttf")
SYNC_ON_START = os.getenv("SYNC_ON_START", "f") in "1yY"


def fail_safe(func):
    def inner_function(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except Exception as exc:
            print(
                f"{func.__name__}("
                + ", ".join(
                    list(str(a) for a in args)
                    + list(f"{k}={v}" for k, v in kwargs.items())
                )
                + ")",
                exc,
            )

    return inner_function


@fail_safe
def create_thumbnail(
    input_path: str, output_path: str, size: tuple[int], frame_time=float
):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    thumbnail_args = dict(resample=Image.Resampling.NEAREST)
    if input_path.lower().endswith((".heic", ".png", ".jpg", ".jpeg", ".bmp", ".gif")):
        # Handle image input
        with Image.open(input_path) as img:
            img_rgb = img.convert("RGB")
            img_rgb.thumbnail(size, **thumbnail_args)
            img_rgb.save(output_path)
    elif input_path.lower().endswith((".mp4", ".avi", ".mov", ".mkv")):
        # Handle video input
        clip = VideoFileClip(input_path)
        frame = clip.get_frame(frame_time)
        img = Image.fromarray(frame)
        img.thumbnail(size, **thumbnail_args)
        # Show duration in thumbnail
        hours, remainder = divmod(clip.duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        draw = ImageDraw.Draw(img)
        for position, color in [((6, 4), (0, 0, 0)), ((5, 3), (255, 255, 255))]:
            draw.text(
                position,
                f"▶ {int(hours):02}:{int(minutes):02}:{int(seconds):02}",
                color,
                font=ImageFont.truetype(FONT_FILE, 16),
            )
        img.save(output_path)
    elif input_path.lower().endswith(".pdf"):
        # Handle PDF input
        doc = fitz.open(input_path)
        page = doc.load_page(0)  # Load the first page
        pix = page.get_pixmap()
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img.thumbnail(size, **thumbnail_args)
        img.save(output_path)
    else:
        print(f"Unsupported file format: {input_path}")
        # Show extension in thumbnail
        _, ext = os.path.splitext(input_path)
        with Image.open(DEFAULT_THUMBNAIL) as img:
            draw = ImageDraw.Draw(img)
            font = ImageFont.truetype(FONT_FILE, 22)
            draw.text((33, 33), ext, (105, 115, 125), font=font)
            img.save(output_path)

    print(f"Thumbnail saved as {output_path}")


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Create thumbnails of image, video, or PDF files."
    )
    parser.add_argument("input", type=str, help="Path to the input folder")
    parser.add_argument("output", type=str, help="Path to the thumbnails folder")
    parser.add_argument(
        "--width", type=int, default=128, help="Width of the thumbnails"
    )
    parser.add_argument(
        "--height", type=int, default=128, help="Height of the thumbnails"
    )
    parser.add_argument(
        "--frame-time",
        type=float,
        default=1.0,
        help="Time position in seconds to extract the frame from the video (default 1sec)",
    )
    parser.add_argument(
        "--extension",
        default=".jpg",
        help="Thumbnail file extension (default is '.jpg')",
    )
    return parser.parse_args()


class WatchHandler(FileSystemEventHandler):
    def __init__(
        self, output_path: str, size: tuple[int], frame_time: float, extension: str
    ):
        super().__init__()
        self.output_path = output_path
        self.size = size
        self.frame_time = frame_time
        self.extension = extension

    def on_created(self, event):
        """
        Create thumbnails folders and images.
        """
        if event.is_directory:
            folder_name = os.path.basename(event.src_path)
            if not BESACE_FOLDER_PATTERN.match(folder_name):
                print(f"Ignore {event.src_path}")
                return
            print(f"New besace folder created: {event.src_path}")
            os.makedirs(os.path.join(self.output_path, folder_name))
        else:
            parent_folder = os.path.dirname(event.src_path)
            folder_name = os.path.basename(parent_folder)
            file_name = os.path.basename(event.src_path)
            if not BESACE_FOLDER_PATTERN.match(folder_name):
                print(f"Ignore {event.src_path}")
                return
            # Wait for file to be fully written.
            while True:
                size_before = os.path.getsize(event.src_path)
                time.sleep(FILE_COMPLETE_WAIT_SECONDS)
                size_now = os.path.getsize(event.src_path)
                if size_now == size_before:
                    break
            # Now create the thumbnail.
            print(f"New file created: {event.src_path}")
            output_path = os.path.join(self.output_path, folder_name, file_name)
            create_thumbnail(
                event.src_path,
                f"{output_path}{self.extension}",
                self.size,
                self.frame_time,
            )

    def on_deleted(self, event):
        """
        Delete thumbnails folders when source besace folder is deleted.
        """
        if event.is_directory:
            folder_name = os.path.basename(event.src_path)
            if not BESACE_FOLDER_PATTERN.match(folder_name):
                print(f"Ignore {event.src_path}")
                return
            print(f"Directory deleted: {event.src_path}")
            thumbnail_folder = os.path.join(self.output_path, folder_name)
            try:
                shutil.rmtree(thumbnail_folder)
            except FileNotFoundError:
                # Already deleted or never created.
                pass


def main():
    register_heif_opener()

    args = parse_arguments()
    size = (args.width, args.height)

    if SYNC_ON_START:
        print("Sync on startup...")
        for root, dirs, files in os.walk(args.input):
            for file_name in files:
                folder_name = os.path.basename(root)  # Get the folder name
                if not BESACE_FOLDER_PATTERN.match(folder_name):
                    continue
                input_path = os.path.join(root, file_name)
                output_path = os.path.join(args.output, folder_name, file_name) + args.extension
                if os.path.exists(output_path):
                    continue
                create_thumbnail(input_path, output_path, size, args.frame_time)

    print(f"Watching {args.input}, thumbnails in {args.output}")
    observer = Observer()

    event_handler = WatchHandler(args.output, size, args.frame_time, args.extension)
    observer.schedule(event_handler, args.input, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
