"""Prepare a private native Mac environment once, then start the desktop UI."""
import hashlib
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atelier.model_assets import verify_model  # noqa: E402
from scripts.macos_builder import MAX_PYTHON, MIN_PYTHON, _probe  # noqa: E402


def validate_host():
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise RuntimeError("Utilisez un Mac Apple Silicon et Python natif, sans Rosetta.")
    if int(platform.mac_ver()[0].split(".")[0]) < 15:
        raise RuntimeError("macOS 15 ou supérieur est nécessaire.")
    if not (3, 12) <= sys.version_info[:2] <= (3, 14):
        raise RuntimeError("Installez Python 3.12, 3.13 ou 3.14 en suivant Installer depuis les sources dans README.md.")


def installation_key(requirements, python):
    digest = hashlib.sha256(requirements.read_bytes())
    version = subprocess.run([str(python), "-c", "import sys; print(sys.version)"],
                             capture_output=True, text=True, check=True).stdout
    digest.update(version.encode())
    return digest.hexdigest()


def prepare(root=ROOT):
    validate_host()
    environment = root / ".venv"
    python = environment / "bin" / "python"
    if not python.exists():
        if environment.exists():
            raise RuntimeError("Le dossier .venv est incomplet ou vient de Windows. "
                               "Décompressez l'archive Mac dans un nouveau dossier.")
        print("Création de l'environnement Python local…", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    details = _probe(python)
    if not details or not MIN_PYTHON <= details[:2] <= MAX_PYTHON or details[2] != "arm64":
        raise RuntimeError("Le .venv doit utiliser Python macOS arm64 3.12, 3.13 ou 3.14. "
                           "Décompressez les sources dans un nouveau dossier, sans recopier ce .venv.")
    requirements = root / "requirements-tested.txt"
    marker = environment / "atelier-runtime.sha256"
    expected = installation_key(requirements, python)
    if not marker.exists() or marker.read_text(encoding="utf-8").strip() != expected:
        print("Installation des dépendances Mac. Internet est nécessaire pour cette étape…",
              flush=True)
        subprocess.run([str(python), "-m", "pip", "install", "--force-reinstall", "--only-binary=:all:",
                        "-r", str(requirements)], cwd=root, check=True)
        subprocess.run([str(python), "-c",
                        "import numpy, PIL, rawpy, onnxruntime; "
                        "from PySide6 import QtCore, QtGui, QtWidgets"], cwd=root, check=True)
        marker.write_text(expected + "\n", encoding="utf-8")
    # Launch never downloads the model: verify the copy included in the archive.
    assets = root / "atelier" / "assets"
    verify_model(assets / "model.onnx")
    return python


def main():
    try:
        python = prepare()
        print("Démarrage d'Atelier Photo. Gardez ce Terminal ouvert pendant l'utilisation.",
              flush=True)
        return subprocess.call([str(python), str(ROOT / "main.py"), *sys.argv[1:]], cwd=ROOT)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Erreur : {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
