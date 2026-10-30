"""Rebuild the bundled selector from a labeled dataset; preserve the color look."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atelier.config import resource_directory
from atelier.dino import DinoEncoder
from atelier.pipeline import prepare_photo
from atelier.selection import train
from scripts.distribution_assets import encoder_version, public_profile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path, help="JSON: paths and truth_indices (retained originals)")
    parser.add_argument("--output", type=Path, default=resource_directory() / "default_profile.json")
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    paths = dataset["paths"]
    kept = set(dataset["truth_indices"])
    if not kept or not kept <= set(range(len(paths))):
        raise ValueError("Indices des photos retenues invalides")
    encoder = DinoEncoder()
    samples = []
    for index, path in enumerate(paths):
        photo = prepare_photo(path, encoder, training=True)
        samples.append({"stats": photo["features"], "embedding": photo["embedding"],
                        "time": photo["time"], "name": Path(path).name, "kept": index in kept})
        if (index + 1) % 50 == 0 or index + 1 == len(paths):
            print(f"Apprentissage : {(index + 1) * 100 // len(paths)} %", flush=True)
    profile = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else {}
    profile["selector"] = train([samples], encoder.version, source="profil par défaut")
    profile = public_profile(profile, encoder_version(resource_directory()))
    temporary = args.output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(profile, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print("Profil distribuable enregistré.", flush=True)


if __name__ == "__main__":
    main()
