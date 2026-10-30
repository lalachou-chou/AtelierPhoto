import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts import start_macos
from atelier.model_assets import MODEL_FILES, MODEL_REPOSITORY


def library(tmp_path):
    (tmp_path / "requirements-tested.txt").write_text("example==1\n", encoding="utf-8")
    assets = tmp_path / "atelier/assets"
    assets.mkdir(parents=True)
    model = b"test model"
    for name in MODEL_FILES:
        (assets / name).write_bytes(model)
    (assets / "model.json").write_text(json.dumps({
        "repository": MODEL_REPOSITORY, "input_size": [448, 448], "dimension": 384,
        "sha256": {name: hashlib.sha256(model).hexdigest() for name in MODEL_FILES}}))
    environment = tmp_path / ".venv/bin"
    environment.mkdir(parents=True)
    (environment / "python").touch()
    return tmp_path


def test_ready_environment_does_not_install_again(tmp_path, monkeypatch):
    root = library(tmp_path)
    monkeypatch.setattr(start_macos, "validate_host", lambda: None)
    marker = root / ".venv/atelier-runtime.sha256"
    marker.write_text(start_macos.installation_key(root / "requirements-tested.txt"))
    calls = []
    monkeypatch.setattr(start_macos.subprocess, "run", lambda *a, **k: calls.append(a))
    assert start_macos.prepare(root) == root / ".venv/bin/python"
    assert not calls


def test_failed_install_can_be_retried(tmp_path, monkeypatch):
    root = library(tmp_path)
    monkeypatch.setattr(start_macos, "validate_host", lambda: None)

    def fail(*args, **kwargs):
        raise start_macos.subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(start_macos.subprocess, "run", fail)
    with pytest.raises(start_macos.subprocess.CalledProcessError):
        start_macos.prepare(root)
    assert not (root / ".venv/atelier-runtime.sha256").exists()


def test_corrupt_model_is_rejected_offline(tmp_path, monkeypatch):
    root = library(tmp_path)
    monkeypatch.setattr(start_macos, "validate_host", lambda: None)
    monkeypatch.setattr(start_macos.subprocess, "run", lambda *a, **k: None)
    (root / "atelier/assets/model.onnx_data").write_bytes(b"corruption")
    with pytest.raises(RuntimeError, match="Modèle endommagé"):
        start_macos.prepare(root)


@pytest.mark.parametrize("system,arch,version,python", [
    ("win32", "arm64", "15.0", (3, 12)),
    ("darwin", "x86_64", "15.0", (3, 12)),
    ("darwin", "arm64", "14.0", (3, 12)),
    ("darwin", "arm64", "15.0", (3, 11)),
])
def test_incompatible_host_is_rejected(monkeypatch, system, arch, version, python):
    monkeypatch.setattr(start_macos, "sys", SimpleNamespace(platform=system, version_info=python))
    monkeypatch.setattr(start_macos.platform, "machine", lambda: arch)
    monkeypatch.setattr(start_macos.platform, "mac_ver", lambda: (version, (), ""))
    with pytest.raises(RuntimeError):
        start_macos.validate_host()
