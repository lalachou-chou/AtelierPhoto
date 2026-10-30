"""Work around the macOS ONNX Runtime wheel's missing compatibility symlink."""
import sys
from pathlib import Path


def ensure_onnx_dylib_alias():
    """Return the capi directory after restoring libonnxruntime.1.dylib.

    The arm64 wheel currently ships the versioned file only. Its extension module
    asks dyld for the unversioned ABI name through @rpath; Nuitka needs that name
    to exist while resolving dependencies. The symlink is local to the disposable
    build venv and is never installed on the user's Mac.
    """
    if sys.platform != "darwin":
        return None
    import onnxruntime

    capi = Path(onnxruntime.__file__).resolve().parent / "capi"
    target = capi / "libonnxruntime.1.30.0.dylib"
    alias = capi / "libonnxruntime.1.dylib"
    if not target.is_file():
        candidates = sorted(capi.glob("libonnxruntime.1.*.dylib"))
        if len(candidates) != 1:
            raise RuntimeError(f"Bibliothèque ONNX Runtime versionnée introuvable dans {capi}")
        target = candidates[0]
    if alias.is_symlink():
        if alias.resolve() != target.resolve():
            raise RuntimeError(f"Lien ONNX Runtime incorrect : {alias}")
    elif alias.exists():
        raise RuntimeError(f"Un fichier incompatible occupe le nom ONNX Runtime : {alias}")
    else:
        alias.symlink_to(target.name)
    return capi


def ensure_app_onnx_dylib_alias(app):
    """Preserve the ABI alias after Nuitka copies native libraries into the app."""
    if sys.platform != "darwin":
        return 0
    app = Path(app)
    count = 0
    targets = list(app.rglob("libonnxruntime.1.*.dylib"))
    if not targets:
        raise RuntimeError(f"Bibliothèque ONNX Runtime absente du bundle {app}")
    for target in targets:
        alias = target.with_name("libonnxruntime.1.dylib")
        if alias.is_symlink():
            if alias.resolve() != target.resolve():
                raise RuntimeError(f"Lien ONNX Runtime incorrect dans le bundle : {alias}")
        elif alias.exists():
            continue
        else:
            alias.symlink_to(target.name)
        count += 1
    return count
