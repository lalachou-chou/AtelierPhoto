"""Decode/export an explicitly provided RAW; optional upstream fixture download."""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?")
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    from PIL import Image

    from atelier.imaging import NEUTRAL, decode, digest, features
    from atelier.pipeline import export_one
    directory = ROOT / "test-output" / "raw-check"
    directory.mkdir(parents=True, exist_ok=True)
    if args.download:
        path = directory / "RAW_CANON_40D_SRAW_V103.CR2"
        source = "https://raw.githubusercontent.com/letmaik/rawpy/main/test/RAW_CANON_40D_SRAW_V103.CR2"
        if not path.exists():
            urllib.request.urlretrieve(source, path)
        (directory / "SOURCE.txt").write_text("Fixture from rawpy/test, originally rawsamples.ch. CC BY-NC-SA 4.0. Test only; excluded from application distributions.\n" + source, encoding="utf-8")
    elif args.path:
        path = Path(args.path).resolve()
    else:
        parser.error("Pass a RAW path or --download for the upstream test fixture")
    before = digest(path)
    proxy, _ = decode(path, preview=True)
    pixels, _ = decode(path)
    size = (pixels.shape[1], pixels.shape[0])
    assert pixels.dtype.name == "float32"
    assert float(pixels.min()) >= 0 and float(pixels.max()) <= 1
    features(proxy)
    del pixels
    recipe = dict(NEUTRAL, exposure=.15)
    style = {"exposure": 0., "temperature": 0., "contrast": 0., "saturation": 0.}
    exported = export_one({"path": str(path), "data": {"digest": before, "recipe": recipe, "style": style}}, directory, "JPEG")
    with Image.open(exported) as image:
        assert image.size == size
        assert image.info["icc_profile"]
    assert digest(path) == before
    report = {"ok": True, "raw": path.name, "size": size, "preview_size": [proxy.shape[1], proxy.shape[0]], "float_pipeline": True, "original_unchanged": True, "export": exported}
    (directory / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
