"""Build-time only: download pinned DINOv3 graph and external weights."""
import hashlib
import os
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atelier.model_assets import MODEL_FILES, read_manifest, verify_model

ROOT = Path(__file__).resolve().parents[1] / "atelier" / "assets"


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest = read_manifest(ROOT / "model.json")
    for name in MODEL_FILES:
        destination = ROOT / name
        expected = manifest["sha256"][name]
        if destination.exists():
            with destination.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() == expected:
                    print(f"Déjà vérifié : {name}")
                    continue
        url = f"https://huggingface.co/{manifest['repository']}/resolve/{manifest['revision']}/onnx/{name}"
        temporary = destination.with_suffix(destination.suffix + ".part")
        checksum = hashlib.sha256()
        try:
            with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as stream:
                while block := response.read(1024 * 1024):
                    checksum.update(block)
                    stream.write(block)
            if checksum.hexdigest() != expected:
                raise ValueError(f"Empreinte du modèle invalide : {name}")
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    verify_model(ROOT / "model.onnx")
    print("DINOv3 Small 448 × 448 installé et vérifié.")


if __name__ == "__main__":
    main()
