import os
import sys
from pathlib import Path

APP_NAME = "Atelier Photo"
RAW_EXTENSIONS = {".arw", ".cr2", ".cr3", ".nef", ".nrw", ".dng", ".raf", ".orf", ".rw2", ".pef", ".srw", ".3fr", ".iiq", ".rwl", ".x3f"}
EXTENSIONS = RAW_EXTENSIONS | {".jpg", ".jpeg", ".png"}
MODEL_NAME = "DINOv3 Small ViT-S/16 · 448×448 · ONNX float32"
MODEL_SIZE = 448
MODEL_DIMENSION = 384


def resource_directory() -> Path:
    """Return bundled data without placing resources in Contents/MacOS."""
    package_assets = Path(__file__).parent / "assets"
    if sys.platform == "darwin":
        # Apple treats Contents/MacOS as a code-only directory.  The Mac
        # packager moves package data to Contents/Resources before signing.
        bundle_assets = (Path(sys.executable).resolve().parent.parent
                         / "Resources" / "atelier" / "assets")
        if bundle_assets.is_dir():
            return bundle_assets
    return package_assets


MODEL_FILE = resource_directory() / "model.onnx"


def data_directory() -> Path:
    if os.environ.get("ATELIER_DATA_DIR"):
        return Path(os.environ["ATELIER_DATA_DIR"]).expanduser().resolve()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AtelierPhoto"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "AtelierPhoto"
    return Path.home() / ".local" / "share" / "atelier-photo"


def discover(paths):
    """Folders select supported images; explicitly dropped unknown files report errors."""
    result = {}
    for value in paths:
        path = Path(value).expanduser().resolve()
        is_folder = path.is_dir()
        candidates = sorted(path.rglob("*")) if is_folder else [path]
        for candidate in candidates:
            # "._DSC0001.jpeg" files are macOS metadata copied to non-Apple disks.
            hidden = is_folder and candidate.name.startswith(".")
            if not hidden and (not is_folder or candidate.suffix.lower() in EXTENSIONS) and candidate.is_file():
                result[str(candidate)] = None
    return list(result)

