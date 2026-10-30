"""Package an existing Mac app with an Applications shortcut, preserving signatures."""
import argparse
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.macos_bundle import inspect_bundle


def create_dmg(app, output):
    if sys.platform != "darwin":
        raise RuntimeError("La création du DMG nécessite macOS.")
    app, output = Path(app).resolve(), Path(output).absolute()
    inspect_bundle(app)
    if output.suffix != ".dmg" or output.is_symlink() or app in output.parents:
        raise ValueError("Destination DMG invalide")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite a previously working installer before the new one is verified.
    with tempfile.TemporaryDirectory(prefix=".atelier-dmg-", dir=output.parent) as directory:
        staging = Path(directory)
        content = staging / "content"
        content.mkdir()
        copied = content / app.name
        subprocess.run(["/usr/bin/ditto", str(app), str(copied)], check=True)
        (content / "Applications").symlink_to("/Applications", target_is_directory=True)
        guide = Path(__file__).resolve().parents[1] / "packaging/macos/INSTALLER.html"
        shutil.copy2(guide, content / "Lire avant installation.html")
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(copied)], check=True)
        temporary = staging / "installer.dmg"
        subprocess.run(["/usr/bin/hdiutil", "create", "-volname", "Atelier Photo",
                        "-srcfolder", str(content), "-format", "UDZO", str(temporary)], check=True)
        subprocess.run(["/usr/bin/hdiutil", "verify", str(temporary)], check=True)
        temporary.replace(output)
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("app", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with (args.app / "Contents/Info.plist").open("rb") as stream:
        version = plistlib.load(stream)["CFBundleShortVersionString"]
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", version):
        raise ValueError("Version du bundle invalide")
    output = args.output or args.app.parent.parent / f"AtelierPhoto-{version}-macOS-arm64-test.dmg"
    print(create_dmg(args.app, output))


if __name__ == "__main__":
    main()
