import socket
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from PIL import Image

from atelier.dino import DinoEncoder
from atelier.config import MODEL_FILE
from atelier.model_assets import MODEL_FILES, MODEL_REPOSITORY


def test_real_model_offline(monkeypatch):
    if not MODEL_FILE.exists():
        pytest.skip("Run scripts/download_model.py to test the packaged model")
    def forbidden(*args, **kwargs):
        raise AssertionError("Runtime attempted a network connection")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    encoder = DinoEncoder()
    vector = np.asarray(encoder.encode(Image.new("RGB", (320, 240), "orange")))
    assert vector.shape == (384,)
    assert np.isfinite(vector).all()
    assert np.linalg.norm(vector) == pytest.approx(1., abs=1e-5)
    images = [Image.new("RGB", (320, 240), color) for color in ("orange", "blue", "green", "red")]
    serial = [encoder.encode(image) for image in images]
    with ThreadPoolExecutor(max_workers=2) as pool:
        parallel = list(pool.map(encoder.encode, images))
    np.testing.assert_allclose(parallel, serial, rtol=1e-6, atol=1e-7)


def test_missing_model_is_explicit(tmp_path):
    with pytest.raises(RuntimeError, match="absent"):
        DinoEncoder(tmp_path / "missing.onnx")


def test_preprocessing_keeps_whole_frame_at_448_and_uses_imagenet_normalization():
    class Session:
        def run(self, outputs, inputs):
            assert outputs == ["pooler_output"]
            pixels = inputs["pixel_values"]
            assert pixels.shape == (1, 3, 448, 448)
            assert pixels.dtype == np.float32 and pixels.flags.c_contiguous
            np.testing.assert_allclose(pixels[0, :, 224, 0],
                                       (np.array([1., 0., 0.]) - [.485, .456, .406]) / [.229, .224, .225], rtol=1e-6)
            np.testing.assert_allclose(pixels[0, :, 224, -1],
                                       (np.array([0., 0., 1.]) - [.485, .456, .406]) / [.229, .224, .225], rtol=1e-6)
            return [np.ones((1, 384), np.float32)]

    image = Image.new("RGB", (1200, 400), "green")
    image.paste("red", (0, 0, 50, 400))
    image.paste("blue", (1150, 0, 1200, 400))
    encoder = DinoEncoder.__new__(DinoEncoder)
    encoder.session = Session()
    assert np.linalg.norm(encoder.encode(image)) == pytest.approx(1., abs=1e-6)


@pytest.mark.parametrize("broken", MODEL_FILES)
def test_corrupt_graph_or_external_weights_are_rejected(tmp_path, broken):
    data = b"model fixture"
    for name in MODEL_FILES:
        (tmp_path / name).write_bytes(data)
    manifest = {"repository": MODEL_REPOSITORY, "input_size": [448, 448], "dimension": 384,
                "sha256": {name: hashlib.sha256(data).hexdigest() for name in MODEL_FILES}}
    (tmp_path / "model.json").write_text(json.dumps(manifest))
    (tmp_path / broken).write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="endommagé"):
        DinoEncoder(tmp_path / "model.onnx")


def test_old_clip_manifest_is_rejected(tmp_path):
    (tmp_path / "model.onnx").write_bytes(b"old model")
    (tmp_path / "model.json").write_text(json.dumps({"sha256": "old clip hash"}))
    with pytest.raises(RuntimeError, match="incompatible"):
        DinoEncoder(tmp_path / "model.onnx")


def test_bundled_selector_matches_real_encoder():
    from atelier.selection import compatible
    from atelier.store import default_profile
    if not MODEL_FILE.exists():
        pytest.skip("Packaged weights required")
    assert compatible(default_profile()["selector"], DinoEncoder().version, 384)

