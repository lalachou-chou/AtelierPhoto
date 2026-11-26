"""Decode, analyse and export (identical copy) an explicitly provided RAW; optional upstream fixture download."""
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

    from atelier.imaging import decode, digest, features
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
    image = decode(path)
    assert image.mode == "RGB" and max(image.size) <= 1280
    features(image)
    exported = export_one({"path": str(path), "data": {"digest": before}}, directory / "export")
    assert digest(exported) == before
    assert digest(path) == before
    report = {"ok": True, "raw": path.name, "analysis_size": list(image.size), "original_unchanged": True, "export": exported}
    (directory / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
