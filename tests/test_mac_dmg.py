import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import create_macos_dmg


@pytest.mark.parametrize("fail_verify", [False, True])
def test_dmg_published_only_after_verification(tmp_path, monkeypatch, fail_verify):
    app = tmp_path / "AtelierPhoto.app"
    app.mkdir()
    (app / "content").write_text("bundle")
    output = tmp_path / "result.dmg"
    output.write_bytes(b"previous installer")
    monkeypatch.setattr(create_macos_dmg.sys, "platform", "darwin")
    monkeypatch.setattr(create_macos_dmg, "inspect_bundle", lambda app: None)
    shortcuts = []

    def shortcut(path, target, **kwargs):
        # Real symlinks are exercised on Mac; Windows may lack their permission.
        shortcuts.append((path.name, target))
        path.write_text(target)

    monkeypatch.setattr(Path, "symlink_to", shortcut)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["check"]
        if command[0].endswith("ditto"):
            shutil.copytree(command[1], command[2])
        elif command[0].endswith("hdiutil") and command[1] == "create":
            folder = Path(command[command.index("-srcfolder") + 1])
            assert (folder / app.name / "content").read_text() == "bundle"
            assert (folder / "Applications").exists()
            guide = folder / "Lire avant installation.html"
            assert "Ouvrir quand même" in guide.read_text(encoding="utf-8")
            assert {p.name for p in folder.iterdir()} == {
                "AtelierPhoto.app", "Applications", "Lire avant installation.html"}
            Path(command[-1]).write_bytes(b"new installer")
        elif command[0].endswith("hdiutil") and command[1] == "verify":
            assert output.read_bytes() == b"previous installer"
            if fail_verify:
                raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(create_macos_dmg.subprocess, "run", run)
    if fail_verify:
        with pytest.raises(subprocess.CalledProcessError):
            create_macos_dmg.create_dmg(app, output)
        assert output.read_bytes() == b"previous installer"
    else:
        assert create_macos_dmg.create_dmg(app, output) == output
        assert output.read_bytes() == b"new installer"
    assert shortcuts == [("Applications", "/Applications")]
    assert [Path(c[0]).name for c in calls] == ["ditto", "codesign", "hdiutil", "hdiutil"]
    assert not list(tmp_path.glob(".atelier-dmg-*"))


def test_dmg_refuses_non_mac_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(create_macos_dmg.sys, "platform", "win32")
    with pytest.raises(RuntimeError, match="macOS"):
        create_macos_dmg.create_dmg(tmp_path / "app.app", tmp_path / "out.dmg")
    assert not list(tmp_path.iterdir())
