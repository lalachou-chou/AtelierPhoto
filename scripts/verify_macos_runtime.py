"""Fail early with a useful message if the native CPU ONNX Runtime is unusable."""
import json
import platform
import sys
from pathlib import Path


def main():
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise RuntimeError("ONNX Runtime doit être testé dans Python macOS arm64 natif.")
    import onnxruntime as ort

    providers = ort.get_available_providers()
    if "CPUExecutionProvider" not in providers:
        raise RuntimeError(f"ONNX Runtime CPU indisponible. Fournisseurs: {providers}")
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from atelier.dino import DinoEncoder

    encoder = DinoEncoder()
    if "CPUExecutionProvider" not in encoder.session.get_providers():
        raise RuntimeError(f"La session DINOv3 n'utilise pas CPUExecutionProvider: {encoder.session.get_providers()}")
    print(json.dumps({"ok": True, "onnxruntime": ort.__version__,
                      "providers": providers, "session": encoder.session.get_providers(),
                      "model": encoder.version}, indent=2))


if __name__ == "__main__":
    main()
