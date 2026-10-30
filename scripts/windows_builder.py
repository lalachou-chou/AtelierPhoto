"""Build and verify the Windows app, then create its Inno Setup installer."""
import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    try:
        if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
            raise RuntimeError("La compilation Windows nécessite Python x64 sur Windows.")
        if not (3, 12) <= sys.version_info[:2] <= (3, 14):
            raise RuntimeError("Utilisez Python 3.12, 3.13 ou 3.14 dans .venv.")
        from atelier import __version__

        python = sys.executable
        print(f"Construction d'Atelier Photo {__version__} avec Python {platform.python_version()}…", flush=True)
        subprocess.run([python, "-m", "pip", "install", "--disable-pip-version-check",
                        "Nuitka==4.1.1", "pytest>=8,<10"], check=True, cwd=ROOT)
        reports = ROOT / "test-output"
        reports.mkdir(exist_ok=True)
        # Avoid inaccessible Windows Temp/pytest-of-* directories and collisions
        # with another test run. Only this run's temporary files are cleaned up.
        with tempfile.TemporaryDirectory(prefix="windows-build-", dir=reports) as temporary:
            subprocess.run([python, "-m", "pytest", "-q", "--basetemp", str(Path(temporary) / "pytest")],
                           check=True, cwd=ROOT)
        subprocess.run([python, str(ROOT / "scripts/build_release.py")], check=True, cwd=ROOT)
        bundle = ROOT / "dist" / __version__ / "AtelierPhoto.dist"
        report = reports / f"packaged-{__version__}.json"
        report.unlink(missing_ok=True)  # An old successful report must never mask a failed build.
        print("Vérification de l'exécutable compilé…", flush=True)
        subprocess.run([str(bundle / "AtelierPhoto.exe"), "--self-test", str(report)],
                       check=True, cwd=ROOT, timeout=300)
        if json.loads(report.read_text(encoding="utf-8")).get("ok") is not True:
            raise RuntimeError(f"Le diagnostic de l'exécutable a échoué : {report}")
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", str(ROOT / "scripts/prepare_inno.ps1")], check=True, cwd=ROOT)
        subprocess.run([str(ROOT / ".build-tools/inno/ISCC.exe"), f"/DAppVersion={__version__}",
                        f"/DBundleDir={bundle}", str(ROOT / "packaging/windows.iss")], check=True, cwd=ROOT)
        installer = ROOT / "dist" / f"AtelierPhoto-{__version__}-Windows-x64-Setup.exe"
        if not installer.is_file():
            raise RuntimeError("Inno Setup n'a pas produit l'installateur attendu.")
        print(f"Terminé : {installer}", flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Échec de la construction : {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
