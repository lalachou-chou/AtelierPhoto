"""Inspect Mach-O compatibility and apply Apple's mandatory arm64 ad-hoc seal."""
import argparse
import json
import plistlib
import struct
import subprocess
import sys
from pathlib import Path

ARM64 = 0x0100000C
MINIMUM = (15, 0, 0)


def require_local_build_directory(path):
    """Reject known File Provider roots, including paths reached via symlinks.

    Cleaning xattrs once cannot prevent a sync provider from adding Finder
    metadata again while Nuitka or our final seal is signing the bundle.
    """
    path = Path(path).expanduser().resolve()
    for parent in (path, *path.parents):
        if (parent.name.casefold() in ("mobile documents", "cloudstorage")
                and parent.parent.name.casefold() == "library"):
            raise RuntimeError(
                "Le dossier de compilation se trouve dans iCloud Drive ou un dossier synchronisé. "
                "La signature macOS peut y échouer (resource fork / Finder information). "
                "Décompressez une archive neuve dans ~/AtelierPhoto-Build, hors iCloud, "
                "puis relancez Construire Atelier Photo (Mac).command. "
                "Ne recopiez pas les anciens dossiers .venv, deployment ou dist. "
                f"Chemin détecté : {path}"
            )
    return path


def version_tuple(value):
    return value >> 16, (value >> 8) & 255, value & 255


def read_exact(stream, size):
    data = stream.read(size)
    if len(data) != size:
        raise ValueError("En-tête Mach-O tronqué")
    return data


def mach_o_slices(stream, offset=0):
    """Read thin/fat Mach-O headers without executing or loading native code."""
    stream.seek(offset)
    magic = stream.read(4)
    fat = {b"\xca\xfe\xba\xbe": (">", False), b"\xbe\xba\xfe\xca": ("<", False),
           b"\xca\xfe\xba\xbf": (">", True), b"\xbf\xba\xfe\xca": ("<", True)}
    thin = {b"\xcf\xfa\xed\xfe": ("<", 32), b"\xfe\xed\xfa\xcf": (">", 32),
            b"\xce\xfa\xed\xfe": ("<", 28), b"\xfe\xed\xfa\xce": (">", 28)}
    if magic in fat:
        endian, wide = fat[magic]
        count = struct.unpack(endian + "I", read_exact(stream, 4))[0]
        if not 1 <= count <= 32 or offset:
            raise ValueError("En-tête Mach-O universel invalide")
        layout = endian + ("IIQQII" if wide else "IIIII")
        entries = [struct.unpack(layout, read_exact(stream, struct.calcsize(layout))) for _ in range(count)]
        result = []
        for entry in entries:
            result.extend(mach_o_slices(stream, entry[2]))
        return result
    if magic not in thin:
        return []
    endian, size = thin[magic]
    header = magic + read_exact(stream, size - 4)
    cpu, _, filetype, commands, command_bytes = struct.unpack_from(endian + "IIIII", header, 4)
    if commands > 65536 or command_bytes > 16 * 1024 * 1024:
        raise ValueError("Commandes Mach-O invalides")
    data = read_exact(stream, command_bytes)
    cursor, minimum, platform = 0, None, None
    for _ in range(commands):
        if cursor + 8 > len(data):
            raise ValueError("Commande Mach-O tronquée")
        command, length = struct.unpack_from(endian + "II", data, cursor)
        if length < 8 or cursor + length > len(data):
            raise ValueError("Longueur Mach-O invalide")
        if command == 0x32 and length >= 24:  # LC_BUILD_VERSION
            platform, value = struct.unpack_from(endian + "II", data, cursor + 8)
            minimum = version_tuple(value)
        elif command == 0x24 and length >= 16:  # LC_VERSION_MIN_MACOSX
            platform, minimum = 1, version_tuple(struct.unpack_from(endian + "I", data, cursor + 8)[0])
        cursor += length
    return [{"cpu": cpu, "filetype": filetype, "minimum": minimum, "platform": platform}]


def inspect_bundle(app):
    app = Path(app).resolve()
    if app.suffix != ".app" or not (app / "Contents").is_dir():
        raise ValueError("Application .app attendue")
    with (app / "Contents" / "Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    if info.get("LSMinimumSystemVersion") != "15.0":
        raise ValueError("La version minimale déclarée doit être macOS 15.0")
    executable = app / "Contents" / "MacOS" / info["CFBundleExecutable"]
    if not executable.resolve().is_relative_to(app):
        raise ValueError("Exécutable en dehors du bundle")
    binaries, links = [], 0
    for path in app.rglob("*"):
        if path.is_symlink():
            if not path.exists() or not path.resolve().is_relative_to(app):
                raise ValueError(f"Lien de framework invalide : {path.relative_to(app)}")
            links += 1
        elif path.is_file():
            with path.open("rb") as stream:
                slices = mach_o_slices(stream)
            if not slices:
                continue
            arm = [s for s in slices if s["cpu"] == ARM64]
            if not arm or any(s["platform"] != 1 or s["minimum"] is None or s["minimum"] > MINIMUM for s in arm):
                raise ValueError(f"Binaire incompatible macOS 15 arm64 : {path.relative_to(app)}")
            binaries.append(path)
    if executable not in binaries:
        raise ValueError("L’exécutable principal n’est pas un Mach-O arm64")
    return executable, binaries, {"architecture": "arm64", "minimum_macos": "15.0",
                                  "native_binaries": len(binaries), "internal_symlinks": links}


def seal_bundle(app):
    if sys.platform != "darwin":
        raise RuntimeError("La signature doit être exécutée sur macOS")
    app = require_local_build_directory(app)
    _, binaries, _ = inspect_bundle(app)
    subprocess.run(["/usr/bin/xattr", "-cr", str(app)], check=True)
    containers = [p for p in app.rglob("*") if not p.is_symlink() and p.is_dir()
                  and p.suffix in (".framework", ".app", ".xpc")]
    targets = sorted([*binaries, *containers], key=lambda p: len(p.parts), reverse=True)
    for target in [*targets, app]:
        # Recreate ad-hoc metadata from scratch.  Preserving an existing
        # Nuitka signature can make codesign reject resources nested below
        # Contents/MacOS (for example the bundled DINOv3 license file).
        command = ["/usr/bin/codesign", "--force", "--sign", "-"]
        subprocess.run([*command, str(target)], check=True)
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("app", type=Path)
    parser.add_argument("--self-test", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    executable, _, report = inspect_bundle(args.app)
    if args.self_test:
        if sys.platform != "darwin":
            raise RuntimeError("Le diagnostic natif nécessite un Mac")
        args.self_test.parent.mkdir(parents=True, exist_ok=True)
        args.self_test.unlink(missing_ok=True)
        subprocess.run([str(executable), "--self-test", str(args.self_test.resolve())], check=True, timeout=180)
        report["diagnostic"] = json.loads(args.self_test.read_text(encoding="utf-8"))
        if not report["diagnostic"].get("ok"):
            raise RuntimeError("Diagnostic natif en échec")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
