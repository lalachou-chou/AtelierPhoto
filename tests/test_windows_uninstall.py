"""Opt-in installation test with a unique AppId and entirely temporary files."""
import ctypes
import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from atelier import windows_lifecycle
from atelier.store import Store


@pytest.mark.skipif(os.name != "nt", reason="Windows kernel mutex")
def test_running_application_publishes_installer_mutex(monkeypatch):
    from ctypes import wintypes

    name = "AtelierPhoto.Test." + uuid.uuid4().hex
    monkeypatch.setattr(windows_lifecycle, "APP_MUTEX", name)
    monkeypatch.setattr(windows_lifecycle, "_mutex", None)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.OpenMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    assert not kernel.OpenMutexW(0x100000, False, name)
    windows_lifecycle.mark_running()
    handle = windows_lifecycle._mutex
    try:
        windows_lifecycle.mark_running()
        assert windows_lifecycle._mutex == handle
        opened = kernel.OpenMutexW(0x100000, False, name)
        assert opened
        kernel.CloseHandle(opened)
    finally:
        kernel.CloseHandle(handle)
    assert not kernel.OpenMutexW(0x100000, False, name)


@pytest.mark.skipif(os.name != "nt" or os.environ.get("ATELIER_TEST_INSTALLER") != "1",
                    reason="Set ATELIER_TEST_INSTALLER=1 for the isolated Inno Setup lifecycle test")
def test_install_upgrade_uninstall_removes_profiles_and_components(tmp_path, monkeypatch):
    import winreg
    from ctypes import wintypes

    root = Path(__file__).resolve().parents[1]
    compiler = root / ".build-tools/inno/ISCC.exe"
    if not compiler.is_file():
        pytest.skip("Inno Setup is not available")
    token = uuid.uuid4().hex
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "AtelierPhoto.exe").write_bytes(b"installer fixture; never launched")
    (bundle / "runtime.dll").write_bytes(b"bundled runtime")
    (bundle / "assets").mkdir()
    (bundle / "assets/model.onnx").write_bytes(b"bundled model")
    app_dir, data_dir = tmp_path / "application", tmp_path / "data"
    # All recursive cleanup targets are bound to this unique temporary fixture.
    assert app_dir.resolve().is_relative_to(tmp_path.resolve())
    assert data_dir.resolve().is_relative_to(tmp_path.resolve())
    script = (root / "packaging/windows.iss").read_text(encoding="utf-8")
    assert f"AppMutex={windows_lifecycle.APP_MUTEX}" in script
    script = script.replace("AppId={{03D9A7F4-FC1B-4563-9C14-05D456760E50}", "AppId=AtelierPhotoTest" + token)
    script = script.replace("AppName=Atelier Photo", "AppName=Atelier Photo Test " + token)
    script = script.replace("DefaultGroupName=Atelier Photo", "DefaultGroupName=Atelier Photo Test " + token)
    script = script.replace(r"DefaultDirName={localappdata}\Programs\AtelierPhoto", f"DefaultDirName={app_dir}")
    script = script.replace(r"{localappdata}\AtelierPhoto", str(data_dir))
    script = script.replace(windows_lifecycle.APP_MUTEX, "AtelierPhoto.Test." + token)
    assert "{localappdata}" not in script  # Never touch the real user's library.
    source = tmp_path / "test.iss"
    source.write_text(script, encoding="utf-8-sig")

    def run(command):
        result = subprocess.run([str(arg) for arg in command], capture_output=True, text=True, timeout=90)
        log = tmp_path / "installer.log"
        assert result.returncode == 0, result.stdout + result.stderr + (log.read_text(errors="replace") if log.exists() else "")

    run([compiler, f"/DBundleDir={bundle}", f"/O{tmp_path}", "/Fsetup-test", source])
    setup = tmp_path / "setup-test.exe"
    install_args = [setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/TASKS=",
                    f"/DIR={app_dir}", f"/LOG={tmp_path / 'installer.log'}"]
    run(install_args)
    uninstall = app_dir / "unins000.exe"
    try:
        library = Store(data_dir)
        try:
            profile = library.create_profile("Must be removed")
            cache = library.private_dir(profile, "training", "example")
            (cache / "sample.npy").write_bytes(b"learned data")
        finally:
            library.close()
        (data_dir / "library.sqlite3-wal").touch()
        (data_dir / "library.sqlite3-shm").touch()
        (data_dir / "application.lock").touch()
        original, exported = tmp_path / "original.jpg", tmp_path / "export.jpg"
        original.write_bytes(b"original photo")
        exported.write_bytes(b"exported photo")
        run(install_args)  # Updating must preserve the profile and its caches.
        assert (cache / "sample.npy").read_bytes() == b"learned data"
        assert (data_dir / "library.sqlite3").is_file()
        assert (app_dir / "assets/model.onnx").is_file()
        # The same mutex used by the real app must block destructive uninstall.
        monkeypatch.setattr(windows_lifecycle, "APP_MUTEX", "AtelierPhoto.Test." + token)
        monkeypatch.setattr(windows_lifecycle, "_mutex", None)
        windows_lifecycle.mark_running()
        try:
            blocked = subprocess.run([str(uninstall), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=20)
            assert blocked.returncode != 0
            assert (data_dir / "library.sqlite3").is_file()
            assert (app_dir / "AtelierPhoto.exe").is_file()
        finally:
            kernel = ctypes.WinDLL("kernel32")
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel.CloseHandle(windows_lifecycle._mutex)
        run([uninstall, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
        # Inno's self-deletion helper outlives the main uninstall process briefly.
        deadline = time.monotonic() + 10
        while app_dir.exists() and time.monotonic() < deadline:
            time.sleep(.1)
        assert not data_dir.exists()
        assert not app_dir.exists()
        key = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\AtelierPhotoTest{token}_is1"
        with pytest.raises(FileNotFoundError):
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
                pass
        group = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs" / ("Atelier Photo Test " + token)
        assert not group.exists()
        assert original.read_bytes() == b"original photo"
        assert exported.read_bytes() == b"exported photo"
    finally:
        if uninstall.exists() and uninstall.with_suffix(".dat").exists():
            run([uninstall, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
