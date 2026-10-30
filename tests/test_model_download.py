import hashlib
import io
import json

import pytest

from atelier.model_assets import MODEL_FILES, MODEL_REPOSITORY
from scripts import download_model


def manifest(tmp_path):
    expected = b"verified model fixture"
    data = {"repository": MODEL_REPOSITORY, "revision": "pinned-revision",
            "input_size": [448, 448], "dimension": 384,
            "sha256": {name: hashlib.sha256(expected).hexdigest() for name in MODEL_FILES}}
    (tmp_path / "model.json").write_text(json.dumps(data))
    return expected


def test_downloads_both_pinned_files_and_then_works_offline(tmp_path, monkeypatch):
    data = manifest(tmp_path)
    monkeypatch.setattr(download_model, "ROOT", tmp_path)
    urls = []

    def fetch(url, **kwargs):
        urls.append(url)
        return io.BytesIO(data)

    monkeypatch.setattr(download_model.urllib.request, "urlopen", fetch)
    download_model.main()
    assert urls == [f"https://huggingface.co/{MODEL_REPOSITORY}/resolve/pinned-revision/onnx/{name}"
                    for name in MODEL_FILES]
    download_model.main()
    assert len(urls) == 2
    assert all((tmp_path / name).read_bytes() == data for name in MODEL_FILES)


def test_invalid_download_does_not_replace_existing_file(tmp_path, monkeypatch):
    manifest(tmp_path)
    target = tmp_path / "model.onnx"
    target.write_bytes(b"old local file")
    monkeypatch.setattr(download_model, "ROOT", tmp_path)
    monkeypatch.setattr(download_model.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(b"bad download"))
    with pytest.raises(ValueError, match="Empreinte"):
        download_model.main()
    assert target.read_bytes() == b"old local file"
    assert not list(tmp_path.glob("*.part"))
