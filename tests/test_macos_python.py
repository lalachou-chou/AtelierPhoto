import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import macos_builder, start_macos


@pytest.mark.parametrize("minor", [12, 13, 14])
def test_mac_launchers_find_versioned_python(tmp_path, minor):
    if os.name == "nt":
        bash = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
    else:
        bash = Path("/bin/bash")
    if not bash.is_file():
        pytest.skip("Bash is needed to exercise the Mac launchers")
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "scripts").mkdir()
    shutil.copy2(root / "scripts/macos_python.sh", tmp_path / "scripts/macos_python.sh")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    python = binaries / f"python3.{minor}"
    python.write_text('#!/bin/sh\n[ "$1" = "-c" ] && exit 0\nprintf "%s\\n" "$@"\n',
                      encoding="utf-8", newline="\n")
    python.chmod(0o755)
    # An old system Python must not hide a compatible versioned executable.
    old = binaries / "python3"
    old.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8", newline="\n")
    old.chmod(0o755)
    env = dict(os.environ, ATELIER_PYTHON="")
    command = [str(bash), "-c", 'export PATH="$PWD/bin:/usr/bin:/bin"; exec /bin/bash "$1"', "launcher-test"]
    for launcher, script in (("Construire Atelier Photo (Mac).command", "scripts/macos_builder.py"),
                             ("Lancer Atelier Photo.command", "scripts/start_macos.py")):
        target = tmp_path / launcher
        target.write_text((root / launcher).read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        result = subprocess.run([*command, target.as_posix()], cwd=tmp_path, env=env,
                                capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        assert script in result.stdout
    env["ATELIER_PYTHON"] = old.as_posix()
    result = subprocess.run([*command, target.as_posix()], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 1
    assert "ATELIER_PYTHON" in result.stderr


def test_builder_keeps_selected_python_instead_of_favoring_312(monkeypatch):
    monkeypatch.delenv("ATELIER_PYTHON", raising=False)
    monkeypatch.setattr(macos_builder.sys, "executable", "/native/python3.14")
    monkeypatch.setattr(macos_builder.shutil, "which", lambda _: None)
    monkeypatch.setattr(macos_builder, "_probe", lambda p: (3, 14, "arm64")
                        if str(p) == "/native/python3.14" else (3, 12, "arm64"))
    assert macos_builder.find_python() == Path("/native/python3.14")


@pytest.mark.parametrize("details", [(3, 11, "arm64"), (3, 15, "arm64"), (3, 14, "x86_64"), None])
def test_builder_rejects_incompatible_existing_venv(tmp_path, monkeypatch, details):
    python = tmp_path / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(macos_builder, "ROOT", tmp_path)
    monkeypatch.setattr(macos_builder, "_probe", lambda _: details)
    with pytest.raises(RuntimeError, match=".venv existant"):
        macos_builder.venv_python()


def test_builder_reinstalls_for_existing_314_environment(tmp_path, monkeypatch):
    python = tmp_path / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.touch()
    (tmp_path / "atelier").mkdir()
    (tmp_path / "atelier/__init__.py").write_text('__version__ = "0.4.0"', encoding="utf-8")
    monkeypatch.setattr(macos_builder, "ROOT", tmp_path)
    monkeypatch.setattr(macos_builder, "check_host", lambda: None)
    monkeypatch.setattr(macos_builder, "verify_onnx", lambda _: None)
    monkeypatch.setattr(macos_builder, "_probe", lambda _: (3, 14, "arm64"))
    calls = []
    monkeypatch.setattr(macos_builder.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    assert macos_builder.main() == 0
    assert all(cmd[0] == str(python) for cmd in calls)
    installs = [cmd for cmd in calls if cmd[1:4] == ["-m", "pip", "install"]]
    assert installs and all("--force-reinstall" in cmd for cmd in installs)
    assert any("Nuitka==4.1.1" in cmd for cmd in installs)
    assert not any(cmd[1:3] == ["-m", "venv"] for cmd in calls)


def test_launcher_reinstalls_when_venv_python_changes(tmp_path, monkeypatch):
    python = tmp_path / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.touch()
    requirements = tmp_path / "requirements-tested.txt"
    requirements.write_text("numpy==2.5.3\n", encoding="utf-8")
    monkeypatch.setattr(start_macos, "validate_host", lambda: None)
    monkeypatch.setattr(start_macos, "_probe", lambda _: (3, 14, "arm64"))
    monkeypatch.setattr(start_macos, "verify_model", lambda _: None)
    version = "3.12.14"
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(stdout=version)

    monkeypatch.setattr(start_macos.subprocess, "run", run)
    marker = tmp_path / ".venv/atelier-runtime.sha256"
    marker.write_text(start_macos.installation_key(requirements, python), encoding="utf-8")
    version = "3.14.8"
    assert start_macos.prepare(tmp_path) == python
    installs = [cmd for cmd in calls if "install" in cmd]
    assert len(installs) == 1 and "--force-reinstall" in installs[0]
    calls.clear()
    assert start_macos.prepare(tmp_path) == python
    assert not any("install" in cmd for cmd in calls)
