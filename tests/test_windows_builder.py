import json
import subprocess
from pathlib import Path

import pytest

from atelier import __version__
from scripts import windows_builder


@pytest.mark.parametrize("diagnostic", ["success", "missing", "failed", "exit-error"])
def test_installer_requires_fresh_successful_diagnostic(tmp_path, monkeypatch, diagnostic):
    root = tmp_path / "Projet avec espaces"
    reports = root / "test-output"
    reports.mkdir(parents=True)
    report = reports / f"packaged-{__version__}.json"
    report.write_text('{"ok": true}', encoding="utf-8")
    monkeypatch.setattr(windows_builder, "ROOT", root)
    monkeypatch.setattr(windows_builder.sys, "platform", "win32")
    monkeypatch.setattr(windows_builder.sys, "version_info", (3, 14))
    monkeypatch.setattr(windows_builder.platform, "machine", lambda: "AMD64")
    calls = []

    def run(command, **kwargs):
        assert kwargs["check"] and kwargs["cwd"] == root
        calls.append(command)
        if "--basetemp" in command:
            base = Path(command[command.index("--basetemp") + 1])
            assert base.is_relative_to(reports)
            base.mkdir()
        if "--self-test" in command:
            assert not report.exists(), "An old report must be removed before the diagnostic"
            assert command[-1] == str(report)
            if diagnostic == "exit-error":
                raise subprocess.CalledProcessError(1, command)
            if diagnostic != "missing":
                report.write_text(json.dumps({"ok": diagnostic == "success"}), encoding="utf-8")
        if Path(command[0]).name == "ISCC.exe":
            installer = root / "dist" / f"AtelierPhoto-{__version__}-Windows-x64-Setup.exe"
            installer.parent.mkdir()
            installer.touch()

    monkeypatch.setattr(windows_builder.subprocess, "run", run)
    assert windows_builder.main() == (0 if diagnostic == "success" else 1)
    assert any(Path(cmd[0]).name == "ISCC.exe" for cmd in calls) == (diagnostic == "success")
