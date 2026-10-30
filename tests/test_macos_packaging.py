import io
import plistlib
import struct
from pathlib import Path

import pytest

from scripts.build_release import (
    collect_notices,
    copy_macos_bundle,
    relocate_macos_resources,
)
from scripts.macos_bundle import ARM64, inspect_bundle, mach_o_slices, require_local_build_directory, seal_bundle


@pytest.mark.parametrize("suffix", [
    "Library/Mobile Documents/com~apple~CloudDocs/Téléchargements/AtelierPhoto-Mac-Builder",
    "Library/CloudStorage/OneDrive/Test",
])
def test_synced_build_location_is_rejected(tmp_path, suffix):
    with pytest.raises(RuntimeError, match="archive neuve"):
        require_local_build_directory(tmp_path / suffix)


def test_local_build_location_is_accepted(tmp_path):
    root = tmp_path / "AtelierPhoto-Build" / "AtelierPhoto-Mac-Builder"
    assert require_local_build_directory(root) == root.resolve()


def test_builder_rejects_cloud_before_installing_or_compiling(tmp_path, monkeypatch, capsys):
    from scripts import macos_builder as builder
    monkeypatch.setattr(builder, "ROOT", tmp_path / "Library/Mobile Documents/com~apple~CloudDocs/project")
    def unexpected():
        pytest.fail("Host preparation must not run in a synchronized folder")
    monkeypatch.setattr(builder, "check_host", unexpected)
    assert builder.main() == 1
    assert "~/AtelierPhoto-Build" in capsys.readouterr().err


def macho(cpu=ARM64, minimum=15, platform=1, legacy=False, filetype=2):
    # Layout specified by Apple's mach-o/loader.h; SDK deliberately differs.
    if legacy:
        command = struct.pack("<IIII", 0x24, 16, minimum << 16, 26 << 16)
    else:
        command = struct.pack("<IIIIII", 0x32, 24, platform, minimum << 16, 26 << 16, 0)
    return struct.pack("<IIIIIIII", 0xFEEDFACF, cpu, 0, filetype, 1, len(command), 0, 0) + command


def app_fixture(root, native=None):
    app = root / "AtelierPhoto.app"
    executable = app / "Contents" / "MacOS" / "AtelierPhoto"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(native if native is not None else macho())
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleExecutable": "AtelierPhoto", "CFBundleShortVersionString": "0.2.0",
        "LSMinimumSystemVersion": "15.0"}))
    return app


@pytest.mark.parametrize("legacy", [False, True])
def test_native_minimum_is_not_sdk_version(legacy):
    slices = mach_o_slices(io.BytesIO(macho(minimum=13, legacy=legacy)))
    assert slices[0]["minimum"] == (13, 0, 0)
    assert slices[0]["platform"] == 1


def test_universal_binary_reads_both_architectures():
    intel, arm = macho(cpu=0x01000007), macho(minimum=14)
    header = struct.pack(">II", 0xCAFEBABE, 2)
    header += struct.pack(">IIIII", 0x01000007, 0, 48, len(intel), 0)
    header += struct.pack(">IIIII", ARM64, 0, 48 + len(intel), len(arm), 0)
    slices = mach_o_slices(io.BytesIO(header + intel + arm))
    assert [s["cpu"] for s in slices] == [0x01000007, ARM64]
    assert slices[1]["minimum"] == (14, 0, 0)


def test_bad_native_header_is_reported():
    with pytest.raises(ValueError, match="tronqué"):
        mach_o_slices(io.BytesIO(macho()[:20]))
    damaged = bytearray(macho())
    struct.pack_into("<I", damaged, 36, 0)
    with pytest.raises(ValueError, match="Longueur"):
        mach_o_slices(io.BytesIO(damaged))


@pytest.mark.parametrize("native", [macho(cpu=0x01000007), macho(minimum=16), macho(platform=2)])
def test_bundle_rejects_wrong_architecture_os_or_platform(tmp_path, native):
    with pytest.raises(ValueError, match="incompatible"):
        inspect_bundle(app_fixture(tmp_path, native))


def test_bundle_copy_and_license_placement(tmp_path):
    source = app_fixture(tmp_path / "source")
    target = tmp_path / "release" / "AtelierPhoto.app"
    copy_macos_bundle(source, target, "0.2.0")
    collect_notices(target)
    executable, binaries, report = inspect_bundle(target)
    assert executable.read_bytes() == (source / "Contents" / "MacOS" / "AtelierPhoto").read_bytes()
    assert len(binaries) == 1 and report["minimum_macos"] == "15.0"
    assert {p.name for p in target.iterdir()} == {"Contents"}
    resources = target / "Contents" / "Resources"
    assert (resources / "THIRD_PARTY_NOTICES.md").exists()
    assert (resources / "third-party-licenses" / "Python-LICENSE.txt").exists()
    info = plistlib.loads((target / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleVersion"] == "0.2.0"


def test_python_license_search_supports_python_org_mac_layout(tmp_path, monkeypatch):
    import scripts.build_release as build
    framework = tmp_path / "Python.framework" / "Versions" / "3.14"
    license_path = framework / "Resources" / "Python.app" / "Contents" / "Resources" / "LICENSE.txt"
    license_path.parent.mkdir(parents=True)
    license_path.write_text("Python license", encoding="utf-8")
    monkeypatch.setattr(build.sys, "base_prefix", str(framework))
    monkeypatch.setattr(build.sys, "executable", str(framework / "bin/python3.14"))
    source = app_fixture(tmp_path / "source")
    target = tmp_path / "release" / "AtelierPhoto.app"
    copy_macos_bundle(source, target, "0.2.0")
    collect_notices(target)
    assert (target / "Contents/Resources/third-party-licenses/Python-LICENSE.txt").read_text(encoding="utf-8") == "Python license"


def test_bundle_copy_failure_restores_previous_release(tmp_path, monkeypatch):
    source = app_fixture(tmp_path / "source")
    target = app_fixture(tmp_path / "release")
    marker = target / "Contents" / "previous.txt"
    marker.write_text("previous", encoding="utf-8")
    rename = Path.rename
    def interrupted(path, destination):
        if path.name == "AtelierPhoto.app" and path.parent.name.startswith(".macos-bundle-"):
            raise OSError("interrupted copy")
        return rename(path, destination)
    monkeypatch.setattr(Path, "rename", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        copy_macos_bundle(source, target, "0.2.0")
    assert marker.read_text(encoding="utf-8") == "previous"


def test_framework_links_survive_copy(tmp_path):
    source = app_fixture(tmp_path / "source")
    resources = source / "Contents" / "Resources"
    resources.mkdir()
    (resources / "model.txt").write_text("model", encoding="utf-8")
    link = source / "Contents" / "MacOS" / "assets"
    try:
        link.symlink_to("../Resources", target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires permissions on this Windows host")
    target = tmp_path / "release" / "AtelierPhoto.app"
    copy_macos_bundle(source, target, "0.2.0")
    copied = target / "Contents" / "MacOS" / "assets"
    assert copied.is_symlink()
    assert (copied / "model.txt").read_text(encoding="utf-8") == "model"
    assert inspect_bundle(target)[2]["internal_symlinks"] == 1


def test_macos_resources_are_moved_out_of_code_directory(tmp_path):
    app = app_fixture(tmp_path)
    source = app / "Contents" / "MacOS" / "atelier" / "assets"
    source.mkdir(parents=True)
    (source / "model.json").write_text("{}", encoding="utf-8")
    assert relocate_macos_resources(app)
    assert not source.exists()
    assert (app / "Contents/Resources/atelier/assets/model.json").read_text(encoding="utf-8") == "{}"
    assert not relocate_macos_resources(app)


def test_config_finds_resources_in_macos_bundle(tmp_path, monkeypatch):
    import atelier.config as config
    app = app_fixture(tmp_path)
    assets = app / "Contents" / "Resources" / "atelier" / "assets"
    assets.mkdir(parents=True)
    monkeypatch.setattr(config.sys, "platform", "darwin")
    monkeypatch.setattr(config.sys, "executable", str(app / "Contents" / "MacOS" / "AtelierPhoto"))
    assert config.resource_directory() == assets


def test_mandatory_seal_orders_frameworks_and_never_uses_a_certificate(tmp_path, monkeypatch):
    import scripts.macos_bundle as mac
    app = app_fixture(tmp_path)
    framework = app / "Contents" / "Frameworks" / "QtCore.framework"
    binary = framework / "Versions" / "A" / "QtCore"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(macho(filetype=6))
    commands = []
    monkeypatch.setattr(mac.sys, "platform", "darwin")
    monkeypatch.setattr(mac.subprocess, "run", lambda command, **kwargs: commands.append(command))
    seal_bundle(app)
    signing = [c for c in commands if "--sign" in c]
    targets = [c[-1] for c in signing]
    assert targets.index(str(binary)) < targets.index(str(framework)) < targets.index(str(app))
    assert all("--deep" not in c and "runtime" not in c and "--timestamp" not in c for c in signing)
    assert all("--preserve-metadata" not in c for c in signing)
    assert all(c[c.index("--sign") + 1] == "-" for c in signing)
    assert "--verify" in commands[-1] and "--deep" in commands[-1]
