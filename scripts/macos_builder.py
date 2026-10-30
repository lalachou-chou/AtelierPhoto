"""Prepare and build Atelier Photo on a native Apple Silicon Mac.

This script is intentionally independent of Homebrew's command names. It finds
the installed python3, creates a clean project-local virtual environment, checks
the CPU ONNX Runtime provider, then builds and verifies the standalone app.
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MIN_PYTHON = (3, 12)
MAX_PYTHON = (3, 14)


def _probe(candidate):
    try:
        result = subprocess.run(
            [str(candidate), "-c", "import platform,sys; print(sys.version_info[0], sys.version_info[1], platform.machine())"],
            capture_output=True, text=True, check=True,
        )
        major, minor, machine = result.stdout.strip().split()
        return (int(major), int(minor), machine)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None


def find_python():
    names = []
    override = os.environ.get("ATELIER_PYTHON")
    if override:
        names.append(override)
    else:
        names.extend((sys.executable, "python3.14", "python3.13", "python3.12", "python3", "python",
                      "/opt/homebrew/bin/python3", "/usr/local/bin/python3"))
    seen = set()
    for value in names:
        path = shutil.which(value) or value
        if path in seen:
            continue
        seen.add(path)
        details = _probe(path)
        if details and details[0:2] >= MIN_PYTHON and details[0:2] <= MAX_PYTHON and details[2] == "arm64":
            return Path(path)
    raise RuntimeError(
        "Python arm64 3.12, 3.13 ou 3.14 est requis. "
        "Le Python doit être natif Apple Silicon, pas Rosetta. "
        "Installez Python depuis python.org ou Homebrew, puis relancez."
    )


def check_host():
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise RuntimeError("La compilation doit être faite sur macOS Apple Silicon, sans Rosetta.")
    version = platform.mac_ver()[0].split(".")
    if not version or int(version[0]) < 15:
        raise RuntimeError("La compilation cible macOS 15 ou supérieur.")
    try:
        subprocess.run(["/usr/bin/xcrun", "--find", "clang"], check=True,
                       stdout=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError(
            "Les outils de ligne de commande Apple manquent. "
            "Lancez une fois `xcode-select --install`, terminez l'installation, puis relancez."
        ) from error


def venv_python():
    path = ROOT / ".venv" / "bin" / "python"
    if path.exists():
        details = _probe(path)
        if not details or not MIN_PYTHON <= details[:2] <= MAX_PYTHON or details[2] != "arm64":
            raise RuntimeError("Le Python du .venv existant doit être en version 3.12, 3.13 ou 3.14 arm64. "
                               "Décompressez les sources dans un nouveau dossier, sans recopier ce .venv.")
        return path
    if (ROOT / ".venv").exists():
        raise RuntimeError(".venv existe mais ne ressemble pas à un environnement macOS. "
                           "Décompressez les sources dans un nouveau dossier, sans recopier ce .venv.")
    interpreter = find_python()
    print(f"Python sélectionné : {interpreter}", flush=True)
    subprocess.run([str(interpreter), "-m", "venv", str(ROOT / ".venv")], check=True, cwd=ROOT)
    return path


def verify_onnx(python):
    subprocess.run([str(python), "-c",
                    "from scripts.macos_onnx import ensure_onnx_dylib_alias; "
                    "ensure_onnx_dylib_alias()"], check=True, cwd=ROOT)
    subprocess.run([str(python), str(ROOT / "scripts/verify_macos_runtime.py")], check=True, cwd=ROOT)


def main():
    try:
        from scripts.macos_bundle import require_local_build_directory
        require_local_build_directory(ROOT)
        check_host()
        python = venv_python()
        requirements = ROOT / "requirements-tested.txt"
        print("Installation des roues natives arm64 (dont ONNX Runtime CPU)…", flush=True)
        subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "--force-reinstall", "pip", "setuptools", "wheel"],
                       check=True, cwd=ROOT)
        # Matching package versions do not imply matching Python ABI after a
        # venv interpreter change. Reinstall wheels for the actual interpreter.
        subprocess.run([str(python), "-m", "pip", "install", "--force-reinstall", "--only-binary=:all:", "-r", str(requirements)],
                       check=True, cwd=ROOT)
        subprocess.run([str(python), "-m", "pip", "install", "--force-reinstall", "pytest>=8,<10", "Nuitka==4.1.1"],
                       check=True, cwd=ROOT)
        subprocess.run([str(python), str(ROOT / "scripts/download_model.py")], check=True, cwd=ROOT)
        verify_onnx(python)
        subprocess.run([str(python), str(ROOT / "scripts/download_licenses.py")], check=True, cwd=ROOT)
        subprocess.run([str(python), "-m", "pytest", "-q"], check=True, cwd=ROOT)
        print("Compilation de l'application autonome…", flush=True)
        subprocess.run([str(python), str(ROOT / "scripts/build_release.py")], check=True, cwd=ROOT)
        version = re.search(r'__version__ = "([^"]+)"', (ROOT / "atelier" / "__init__.py").read_text(encoding="utf-8")).group(1)
        app = ROOT / "dist" / version / "AtelierPhoto.app"
        report_dir = ROOT / "test-output"
        report_dir.mkdir(exist_ok=True)
        subprocess.run([str(python), str(ROOT / "scripts/macos_bundle.py"), str(app),
                        "--self-test", str(report_dir / "packaged-macos.json"),
                        "--report", str(report_dir / "macos-bundle.json")], check=True, cwd=ROOT)
        subprocess.run([str(python), str(ROOT / "scripts/create_macos_dmg.py"), str(app)],
                       check=True, cwd=ROOT)
        dmg = ROOT / "dist" / f"AtelierPhoto-{version}-macOS-arm64.dmg"
        print(json.dumps({"app": str(app), "dmg": str(dmg), "python": str(python)}, indent=2), flush=True)
        print("Compilation terminée. Transférez uniquement le DMG au Mac final.", flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Échec de la compilation : {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
