import copy
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from atelier import look
from atelier.selection import score
from scripts.distribution_assets import (
    PUBLIC_DESCRIPTION,
    encoder_version,
    public_profile,
    verify_distribution_assets,
)

ASSETS = Path(__file__).resolve().parents[1] / "atelier" / "assets"


def profile():
    return json.loads((ASSETS / "default_profile.json").read_text(encoding="utf-8"))


def test_public_profile_strips_training_details_and_preserves_predictions():
    expected = profile()
    private = copy.deepcopy(expected)
    private.update(description="private corpus", paths=["private/photo.jpg"],
                   references=[{"embedding": [1., 0.], "name": "private-photo.jpg"}],
                   reportages=[{"name": "private event"}], exif={"GPS": "private location"})
    private["selector"].update(source="private folder", photos=123, kept=45, samples=["private sample"])
    private["look"].update(pairs=34, paths=["private/edit.jpg"])
    private["look"]["tone"]["examples"] = ["private tone example"]
    public = public_profile(private, encoder_version(ASSETS))
    assert public == expected
    assert public["description"] == PUBLIC_DESCRIPTION
    assert "private" not in json.dumps(public)
    x = np.random.default_rng(0).normal(size=(3, len(public["selector"]["mu"])))
    np.testing.assert_array_equal(score(private["selector"], x), score(public["selector"], x))
    pixels = np.random.default_rng(1).uniform(size=(10, 10, 3)).astype(np.float32)
    knots = look.knots_for(public["look"], pixels)
    np.testing.assert_array_equal(look.apply(private["look"], pixels, knots), look.apply(public["look"], pixels, knots))


@pytest.mark.parametrize("field", ["numeric", "encoder"])
def test_public_profile_refuses_private_strings_in_inference_fields(field):
    private = profile()
    if field == "numeric":
        private["look"]["lut"][0][0] = "private/photo.jpg"
    else:
        private["selector"]["encoder"] = "private/model.onnx"
    with pytest.raises(ValueError) as error:
        public_profile(private, encoder_version(ASSETS))
    assert "private" not in str(error.value)


def assets_copy(tmp_path):
    for name in ("model.json", "default_profile.json"):
        shutil.copy2(ASSETS / name, tmp_path / name)
    return tmp_path


@pytest.mark.parametrize("name", ["private.jpg", "private.json", "private.npz", "private.xmp", "private.txt"])
def test_packaging_refuses_unapproved_assets_without_logging_their_name(tmp_path, name):
    assets = assets_copy(tmp_path)
    (assets / name).write_bytes(b"private contents")
    with pytest.raises(ValueError, match="packaging bloqué") as error:
        verify_distribution_assets(assets)
    assert name not in str(error.value)


def test_packaging_refuses_unsanitized_profile(tmp_path):
    assets = assets_copy(tmp_path)
    private = profile()
    private["selector"]["photos"] = 123
    (assets / "default_profile.json").write_text(json.dumps(private), encoding="utf-8")
    with pytest.raises(ValueError, match="métadonnées non publiables"):
        verify_distribution_assets(assets)


def test_shipped_profile_passes_privacy_gate():
    verify_distribution_assets(ASSETS)
