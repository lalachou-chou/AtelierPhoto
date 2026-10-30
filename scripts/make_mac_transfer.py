"""Create a clean source transfer, never bundling Windows libraries or user data."""
import argparse
import hashlib
import re
import stat
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atelier.model_assets import MODEL_FILES, verify_model


def sha256(stream):
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--github", action="store_true", help="Sources légères pour compilation en ligne")
    parser.add_argument("--builder", action="store_true", help="Dossier complet pour compiler directement sur Mac")
    args = parser.parse_args()
    if args.github and args.builder:
        raise ValueError("Choisissez --github ou --builder")
    model = ROOT / "atelier/assets/model.onnx"
    manifest = verify_model(model)
    files = [ROOT / name for name in (
        "main.py", "pyproject.toml", "requirements-tested.txt", "README.md",
        "THIRD_PARTY_NOTICES.md", "LIRE SUR MAC.md", "Lancer Atelier Photo.command",
        "Construire Atelier Photo (Mac).command", "LIRE SUR MAC - COMPILATEUR.md")]
    files.append(ROOT / ".gitignore")
    files.append(ROOT / ".github/workflows/macos-test.yml")
    for directory in ("atelier", "docs", "scripts", "tests", "packaging/macos"):
        for path in (ROOT / directory).rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts or path.is_symlink():
                continue
            if directory == "scripts" and path.suffix not in (".py", ".sh"):
                continue
            if directory == "tests" and path.suffix != ".py":
                continue
            if directory == "atelier" and path.suffix not in (".py", ".onnx", ".onnx_data", ".json", ".txt"):
                continue
            if args.github and path.suffix in (".onnx", ".onnx_data"):
                continue  # Too large for browser upload; CI downloads the pinned model.
            files.append(path)
    version = re.search(r'__version__ = "([^"]+)"', (ROOT / "atelier" / "__init__.py").read_text(encoding="utf-8")).group(1)
    if args.builder:
        target = ROOT / f"dist/{version}/AtelierPhoto-{version}-Mac-builder.zip"
        folder = "AtelierPhoto-Mac-Builder"
    elif args.github:
        target = ROOT / f"dist/{version}/AtelierPhoto-{version}-GitHub-sources.zip"
        folder = "AtelierPhoto-GitHub"
    else:
        target = ROOT / f"dist/{version}/AtelierPhoto-{version}-Mac-sources.zip"
        folder = "AtelierPhoto-Mac"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(files):
            relative = path.relative_to(ROOT).as_posix()
            if args.github and relative == ".github/workflows/macos-test.yml":
                relative = "workflow-macos-test.yml"  # Visible file for browser copy/paste.
            info = zipfile.ZipInfo(folder + "/" + relative)
            info.create_system = 3
            executable = path.suffix in (".command", ".sh")
            info.external_attr = (stat.S_IFREG | (0o755 if executable else 0o644)) << 16
            data = path.read_bytes()
            if executable:
                data = data.replace(b"\r\n", b"\n")
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise ValueError("Archive corrompue")
        if not args.github:
            for name in MODEL_FILES:
                with archive.open(folder + "/atelier/assets/" + name) as stream:
                    if sha256(stream) != manifest["sha256"][name]:
                        raise ValueError(f"Modèle corrompu dans l'archive : {name}")
        elif any(info.file_size > 25 * 1024 * 1024 for info in archive.infolist()):
            raise ValueError("Un fichier dépasse la limite d'envoi depuis le navigateur")
        print(f"{len(archive.namelist())} fichiers vérifiés")
    print(f"{target} ({target.stat().st_size:,} octets)")


if __name__ == "__main__":
    main()
