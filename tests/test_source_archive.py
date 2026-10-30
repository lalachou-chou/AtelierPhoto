import shutil
import sys
import zipfile
from pathlib import Path

from scripts import make_mac_transfer


def test_github_archive_from_checkout_without_models(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1]
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    for path in source.iterdir():
        if path.is_file() and path.suffix in (".py", ".md", ".toml", ".txt", ".cmd", ".command"):
            shutil.copy2(path, checkout / path.name)
    for name in (".gitignore", ".gitattributes"):
        shutil.copy2(source / name, checkout / name)
    for name in ("atelier", "scripts", "tests", "docs", "packaging", ".github"):
        shutil.copytree(source / name, checkout / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.onnx", "*.onnx_data"))
    assert not (checkout / "atelier/assets/model.onnx").exists()
    # A local training manifest outside assets must not enter source transfers.
    (checkout / "atelier" / "private-dataset.json").write_text('{"paths": ["private/photo.jpg"]}', encoding="utf-8")
    monkeypatch.setattr(make_mac_transfer, "ROOT", checkout)
    monkeypatch.setattr(sys, "argv", ["make_mac_transfer.py", "--github"])
    make_mac_transfer.main()
    archive_path = next((checkout / "dist").rglob("*-GitHub-sources.zip"))
    with zipfile.ZipFile(archive_path) as archive:
        prefix = "AtelierPhoto-GitHub/"
        names = {name.removeprefix(prefix) for name in archive.namelist()}
        required = {
            ".gitignore", ".gitattributes", ".github/workflows/build.yml",
            ".github/workflows/test.yml", ".github/workflows/macos-test.yml",
            "Lancer Atelier Photo.cmd", "Construire Atelier Photo (Windows).cmd",
            "packaging/windows.iss", "scripts/prepare_inno.ps1",
            "scripts/macos_python.sh",
            "atelier/training_dialog.py",
            "atelier/assets/model.json", "atelier/assets/default_profile.json",
            "tests/test_training.py", "docs/COMPILER_MAC_DEPUIS_WINDOWS.md",
        }
        assert required <= names
        assert "atelier/private-dataset.json" not in names
        assert not any(name.endswith((".onnx", ".onnx_data")) for name in names)
        launcher = archive.getinfo(prefix + "Construire Atelier Photo (Mac).command")
        assert launcher.external_attr >> 16 & 0o111
        assert b"\r\n" not in archive.read(launcher)
