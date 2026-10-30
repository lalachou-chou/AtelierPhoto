import os
import subprocess
from pathlib import Path

import pytest

from scripts import macos_builder, macos_onnx


def test_find_python_prefers_supported_native_interpreter(monkeypatch):
    probes = {
        "python3": (3, 11, "arm64"),
        "python": (3, 13, "arm64"),
    }
    monkeypatch.setattr(macos_builder.shutil, "which", lambda name: name)
    monkeypatch.setattr(macos_builder, "_probe", lambda name: probes.get(str(name)))
    assert macos_builder.find_python() == Path("python")


def test_find_python_rejects_rosetta(monkeypatch):
    monkeypatch.setattr(macos_builder.shutil, "which", lambda name: name)
    monkeypatch.setattr(macos_builder, "_probe", lambda name: (3, 13, "x86_64"))
    with pytest.raises(RuntimeError, match="arm64"):
        macos_builder.find_python()


def test_host_check_reports_missing_xcode_tools(monkeypatch):
    monkeypatch.setattr(macos_builder, "sys", type("S", (), {"platform": "darwin"}))
    monkeypatch.setattr(macos_builder.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(macos_builder.platform, "mac_ver", lambda: ("15.0", (), ""))
    monkeypatch.setattr(macos_builder.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
        subprocess.CalledProcessError(1, a[0])))
    with pytest.raises(RuntimeError, match="outils de ligne de commande"):
        macos_builder.check_host()


def test_onnx_alias_is_created_only_on_mac(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("Les liens symboliques nécessitent une permission Windows")
    capi = tmp_path / "capi"
    capi.mkdir()
    target = capi / "libonnxruntime.1.30.0.dylib"
    target.write_bytes(b"dylib")
    fake_module = capi.parent / "__init__.py"
    fake_module.write_text("", encoding="utf-8")
    monkeypatch.setattr(macos_onnx.sys, "platform", "darwin")
    # The helper imports the package itself; use a tiny import shim instead.
    monkeypatch.setitem(__import__("sys").modules, "onnxruntime", type("Ort", (), {
        "__file__": str(fake_module),
    })())
    assert macos_onnx.ensure_onnx_dylib_alias() == capi
    assert (capi / "libonnxruntime.1.dylib").is_symlink()
    assert (capi / "libonnxruntime.1.dylib").resolve() == target.resolve()


def test_app_onnx_alias_is_created_inside_bundle(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("Les liens symboliques nécessitent une permission Windows")
    app = tmp_path / "AtelierPhoto.app" / "Contents" / "MacOS" / "onnxruntime" / "capi"
    app.mkdir(parents=True)
    target = app / "libonnxruntime.1.30.0.dylib"
    target.write_bytes(b"dylib")
    monkeypatch.setattr(macos_onnx.sys, "platform", "darwin")
    assert macos_onnx.ensure_app_onnx_dylib_alias(target.parents[4]) == 1
    assert (app / "libonnxruntime.1.dylib").is_symlink()
