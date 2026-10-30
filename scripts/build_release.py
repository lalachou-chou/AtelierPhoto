"""Build on the target OS using pyside6-deploy and a standalone Nuitka bundle."""
import argparse
import configparser
import os
import platform
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def collect_notices(bundle):
    import importlib.metadata
    import sysconfig
    resources = bundle / "Contents" / "Resources" if bundle.suffix == ".app" else bundle
    resources.mkdir(parents=True, exist_ok=True)
    target = resources / "third-party-licenses"
    target.mkdir(exist_ok=True)
    # The official python.org macOS installer keeps this under Python.app,
    # while Homebrew and Windows place it at the interpreter prefix. Search
    # both layouts so a valid Python installation never makes the build fail.
    candidates = [
        Path(sys.base_prefix) / "LICENSE.txt",
        Path(sys.base_prefix) / "Resources/Python.app/Contents/Resources/LICENSE.txt",
        Path(sys.base_prefix) / "Python.app/Contents/Resources/LICENSE.txt",
        Path(sys.executable).resolve().parents[2] / "Resources/Python.app/Contents/Resources/LICENSE.txt",
    ]
    try:
        stdlib = Path(sysconfig.get_path("stdlib"))
        candidates.extend((stdlib / "LICENSE.txt", stdlib.parent / "LICENSE.txt"))
    except (KeyError, TypeError):
        pass
    python_license = next((path for path in dict.fromkeys(candidates) if path.is_file()), None)
    if python_license is None:
        raise RuntimeError("Licence Python introuvable dans cette installation. "
                           "Réinstallez Python depuis python.org ou Homebrew.")
    shutil.copy2(python_license, target / "Python-LICENSE.txt")
    for name in ("numpy", "pillow", "PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6", "rawpy", "onnxruntime", "protobuf", "flatbuffers"):
        distribution = importlib.metadata.distribution(name)
        for file in distribution.files or []:
            if any(t in str(file).lower() for t in ("license", "copying", "copyright", "notice")):
                source = distribution.locate_file(file)
                if source.is_file():
                    relative = Path(*[p for p in Path(file).parts if p not in ("..", ".")])
                    destination = target / name / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", resources)
    shutil.copy2(ROOT / "README.md", resources)
    shutil.copytree(ROOT / "docs", resources / "docs", dirs_exist_ok=True)


def copy_macos_bundle(source, destination, version):
    """PySide6's final copy dereferences framework links; copy the original instead."""
    source, destination = Path(source).resolve(), Path(destination).absolute()
    if source == destination or destination.suffix != ".app" or destination.is_symlink():
        raise ValueError("Destination du bundle invalide")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".macos-bundle-", dir=destination.parent) as directory:
        staging = Path(directory) / destination.name
        shutil.copytree(source, staging, symlinks=True)
        plist = staging / "Contents" / "Info.plist"
        with plist.open("rb") as stream:
            info = plistlib.load(stream)
        info["LSMinimumSystemVersion"] = "15.0"
        info["CFBundleIdentifier"] = "org.atelierphoto.AtelierPhoto"
        info["CFBundleVersion"] = version
        for key in ("NSDesktopFolderUsageDescription", "NSDocumentsFolderUsageDescription",
                    "NSDownloadsFolderUsageDescription", "NSRemovableVolumesUsageDescription"):
            info[key] = "Importer vos photos et enregistrer les exports dans le dossier choisi."
        with plist.open("wb") as stream:
            plistlib.dump(info, stream)
        backup = Path(directory) / "previous.app"
        if destination.exists():
            destination.rename(backup)
        try:
            staging.rename(destination)
        except BaseException:
            if backup.exists():
                backup.rename(destination)
            raise


def relocate_macos_resources(bundle):
    """Move package data out of the code-only Contents/MacOS directory."""
    bundle = Path(bundle)
    source = bundle / "Contents" / "MacOS" / "atelier" / "assets"
    if not source.is_dir() or source.is_symlink():
        return False
    destination = bundle / "Contents" / "Resources" / "atelier" / "assets"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.move(str(source), str(destination))
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    if sys.platform == "darwin":
        if platform.machine() != "arm64" or int(platform.mac_ver()[0].split(".")[0]) < 15:
            raise RuntimeError("Construisez sur macOS 15+ avec Python arm64 natif, sans Rosetta.")
        os.environ["MACOSX_DEPLOYMENT_TARGET"] = "15.0"
    # A short project-local cache avoids long Windows Store redirection paths.
    os.environ.setdefault("NUITKA_CACHE_DIR", str(ROOT / ".build-cache"))
    sys.path.insert(0, str(ROOT))
    if sys.platform == "darwin":
        from scripts.macos_bundle import require_local_build_directory
        require_local_build_directory(ROOT)
        from scripts.macos_onnx import ensure_onnx_dylib_alias
        ensure_onnx_dylib_alias()
    from atelier import __version__
    from atelier.dino import DinoEncoder
    DinoEncoder()  # Fail the build if the offline model is missing/corrupt.
    for name in ("LGPL-3.0.txt", "GPL-3.0.txt", "OpenSSL-LICENSE.txt", "DINOv3-LICENSE.txt"):
        if not (ROOT / "atelier" / "assets" / name).is_file():
            raise RuntimeError("Licences manquantes : exécuter scripts/download_licenses.py avant le build.")
    executable = shutil.which("pyside6-deploy") or str(Path(sys.executable).parent / ("pyside6-deploy.exe" if sys.platform == "win32" else "pyside6-deploy"))
    spec = ROOT / "pysidedeploy.spec"
    if not spec.exists():
        subprocess.run([executable, "main.py", "--init", "--force", "--name", "AtelierPhoto"], check=True)
    config = configparser.ConfigParser()
    config.read(spec, encoding="utf-8")
    config["app"]["title"] = "AtelierPhoto"
    config["app"]["project_dir"] = str(ROOT)
    config["app"]["input_file"] = str(ROOT / "main.py")
    release_directory = ROOT / "dist" / __version__
    release_directory.mkdir(parents=True, exist_ok=True)
    config["app"]["exec_directory"] = str(release_directory)
    config["python"]["python_path"] = sys.executable
    config["nuitka"]["mode"] = "standalone"
    flags = ["--assume-yes-for-downloads", "--noinclude-qt-translations",
             "--include-package=atelier", "--include-package=rawpy",
             "--nofollow-import-to=onnxruntime.backend", "--nofollow-import-to=onnxruntime.quantization", "--nofollow-import-to=onnxruntime.tools",
             "--noinclude-unittest-mode=nofollow", "--noinclude-qt-plugins=platforminputcontexts", "--noinclude-qt-plugins=tls",
             "--include-data-dir=atelier/assets=atelier/assets", "--output-filename=AtelierPhoto",
             "--company-name=AtelierPhoto", "--product-name=AtelierPhoto", f"--product-version={__version__}"]
    if sys.platform == "win32":
        flags += ["--windows-console-mode=disable", "--mingw64", "--jobs=4"]
    elif sys.platform == "darwin":
        flags += ["--macos-create-app-bundle", "--macos-app-name=AtelierPhoto", f"--macos-app-version={__version__}",
                  "--macos-target-arch=arm64"]
    config["nuitka"]["extra_args"] = shlex.join(flags)
    with spec.open("w", encoding="utf-8") as stream:
        config.write(stream)
    (ROOT / "dist").mkdir(exist_ok=True)
    command = [executable, "-c", str(spec), "--force", "--keep-deployment-files", "--extra-ignore-dirs", "tests,scripts,.venv,test-output,dist,build,.build-cache,.build-tools,deployment"]
    if args.dry_run:
        command.append("--dry-run")
    started = time.time()
    subprocess.run(command, check=True)
    if not args.dry_run:
        if sys.platform == "darwin":
            copy_macos_bundle(ROOT / "deployment" / "main.app", release_directory / "AtelierPhoto.app", __version__)
        # Some pyside6-deploy versions return zero even when Nuitka fails.
        bundles = list(release_directory.glob("*.app")) if sys.platform == "darwin" else list(release_directory.glob("*.dist"))
        binaries = [p for b in bundles for p in b.rglob("AtelierPhoto.exe" if sys.platform == "win32" else "AtelierPhoto") if p.is_file()]
        if not binaries:
            raise RuntimeError("La compilation n’a pas produit de binaire. Consultez les erreurs Nuitka ci-dessus.")
        if all(p.stat().st_mtime < started - 2 for p in binaries):
            raise RuntimeError("Le binaire trouvé est ancien : la compilation n’a pas abouti.")
        for bundle in bundles:
            if sys.platform == "darwin":
                relocate_macos_resources(bundle)
            collect_notices(bundle)
            if sys.platform == "darwin":
                from macos_bundle import seal_bundle
                from macos_onnx import ensure_app_onnx_dylib_alias
                ensure_app_onnx_dylib_alias(bundle)
                seal_bundle(bundle)  # Apple Silicon requires an identity-free ad-hoc seal.
        print("Bundle vérifié :", binaries[0])


if __name__ == "__main__":
    main()
