"""Model integrity checks shared by the runtime and offline launchers (stdlib only)."""
import hashlib
import json
from pathlib import Path

MODEL_REPOSITORY = "onnx-community/dinov3-vits16-pretrain-lvd1689m-ONNX"
MODEL_FILES = ("model.onnx", "model.onnx_data")


def read_manifest(path):
    try:
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
        if (manifest["repository"] != MODEL_REPOSITORY
                or manifest["input_size"] != [448, 448]
                or manifest["dimension"] != 384
                or set(manifest["sha256"]) != set(MODEL_FILES)):
            raise ValueError("Contrat DINOv3 incompatible")
        return manifest
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Manifeste DINOv3 absent ou incompatible. Réinstallez le modèle.") from exc


def verify_model(path):
    path = Path(path)
    if not path.is_file():
        raise RuntimeError("Modèle DINOv3 absent. Exécutez scripts/download_model.py avant l’analyse.")
    manifest = read_manifest(path.with_name("model.json"))
    for name in MODEL_FILES:
        asset = path if name == "model.onnx" else path.with_name(name)
        if not asset.is_file():
            raise RuntimeError(f"Fichier DINOv3 absent : {name}. Réinstallez le modèle.")
        with asset.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        if checksum != manifest["sha256"][name]:
            raise RuntimeError(f"Modèle endommagé (DINOv3, {name}). Réinstallez-le.")
    return manifest
