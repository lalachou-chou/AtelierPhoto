"""Restrict distributed assets to runtime data; never publish training records."""
import json
import math
from pathlib import Path

from atelier.config import MODEL_NAME
from atelier.model_assets import MODEL_FILES, read_manifest

PUBLIC_DESCRIPTION = "Profil appris sur des photos de mariages."
PUBLIC_SOURCE = "profil par défaut"
ASSET_NAMES = frozenset((*MODEL_FILES, "model.json", "default_profile.json", "gnu-licenses.json",
                         "app-icon.svg", "app-icon.png", "app-icon.ico", "app-icon.icns",
                         "DINOv3-LICENSE.txt", "GPL-3.0.txt", "LGPL-3.0.txt", "OpenSSL-LICENSE.txt"))


def encoder_version(assets):
    manifest = read_manifest(Path(assets) / "model.json")
    hashes = "/".join(manifest["sha256"][name] for name in MODEL_FILES)
    return f"{MODEL_NAME}/rgb-bilinear-imagenet-cls-l2-v1/{hashes}"


def _numbers(value):
    if isinstance(value, list):
        return [_numbers(item) for item in value]
    if type(value) in (int, float) and math.isfinite(value):
        return value
    # Do not repeat a rejected value: it could be a private path or name.
    raise ValueError("Le profil distribuable doit contenir uniquement les paramètres numériques attendus.")


def public_profile(profile, expected_encoder):
    """Keep inference parameters, replace free text, drop training metadata."""
    result = {"description": PUBLIC_DESCRIPTION}
    if profile.get("selector"):
        selector = profile["selector"]
        if selector["encoder"] != expected_encoder:
            raise ValueError("Encodeur du profil distribuable incompatible.")
        result["selector"] = {key: _numbers(selector[key]) for key in
                              ("mu", "sd", "w", "b", "feature_version", "dimension", "rate")}
        result["selector"].update(encoder=expected_encoder, source=PUBLIC_SOURCE)
    if profile.get("look"):
        look = profile["look"]
        result["look"] = {key: _numbers(look[key]) for key in ("version", "lut_size", "lut")}
        result["look"]["tone"] = {key: _numbers(look["tone"][key]) for key in ("mu", "sd", "coef")}
    return result


def verify_distribution_assets(assets):
    """Fail packaging if an unapproved file or private profile metadata is present."""
    assets = Path(assets)
    for path in assets.rglob("*"):
        if path.is_symlink() or path.is_dir() or path.name not in ASSET_NAMES:
            raise ValueError("Ressource non autorisée dans les assets : packaging bloqué pour protéger les données privées.")
    profile = json.loads((assets / "default_profile.json").read_text(encoding="utf-8"))
    if profile != public_profile(profile, encoder_version(assets)):
        raise ValueError("Le profil fourni contient des métadonnées non publiables : nettoyer le profil avant le packaging.")
