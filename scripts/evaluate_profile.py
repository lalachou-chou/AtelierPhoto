"""Measure how closely Atelier reproduces a photographer's own sorting.

Usage::

    python scripts/evaluate_profile.py RUSH_DIR KEPT_DIR [--folds 5] [--cache features.npz]
                                       [--report rapport.json] [--selectivity 0.5]

The rush is split into consecutive time blocks. For each block, a profile is
trained on the other blocks (selection model), then the block is
analysed exactly like a new batch. Nothing in the evaluated block is ever seen
during training, so the scores estimate the behaviour on a new reportage.

Reported:
* strict: proposed "Retenue" photos that the photographer also kept;
* same moment: a proposed photo also counts when it is a near-identical frame
  (same moment, DINOv3 similarity >= 0.92, <= 15 s apart) of a kept photo;
* coverage of "Retenue + À vérifier".
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atelier.analysis import finalize, propose  # noqa: E402
from atelier.config import discover  # noqa: E402
from atelier.dino import DinoEncoder  # noqa: E402
from atelier.imaging import capture_time, decode, features  # noqa: E402
from atelier.training import learn, match  # noqa: E402


def extract(paths, encoder, label):
    items = []
    for index, path in enumerate(paths):
        image = decode(path)
        items.append({"name": Path(path).name, "path": path, "stats": features(image),
                      "embedding": encoder.encode(image), "time": capture_time(path)})
        if index % 50 == 0:
            print(f"  {label} {index}/{len(paths)}", flush=True)
    return items


def load_or_extract(rush_dir, kept_dir, cache):
    encoder = DinoEncoder()
    if cache and Path(cache).exists():
        with np.load(cache, allow_pickle=True) as data:
            if str(data["model"]) == encoder.version:
                return list(data["rush"]), list(data["kept"]), str(data["model"])
        print("Cache d’un ancien encodeur : recalcul avec DINOv3 Small 448 × 448.", flush=True)
    rush = extract(discover([rush_dir]), encoder, "rush")
    kept = extract(discover([kept_dir]), encoder, "retenues")
    if cache:
        np.savez(cache, rush=np.array(rush, dtype=object), kept=np.array(kept, dtype=object), model=encoder.version)
    return rush, kept, encoder.version


def scores(predicted, truth):
    tp = len(predicted & truth)
    precision = tp / max(len(predicted), 1)
    recall = tp / max(len(truth), 1)
    return {"proposees": len(predicted), "communes": tp, "precision": round(precision, 3), "rappel": round(recall, 3),
            "f1": round(2 * precision * recall / max(precision + recall, 1e-9), 3)}


def same_moment(predicted, truth, rows):
    """One-to-one matching where a near-identical frame of a kept photo counts."""
    by_id = {r["id"]: r for r in rows}
    used, hits = set(), 0
    for i in predicted:
        if i in truth:
            used.add(i)
            hits += 1
    for i in sorted(predicted - truth):
        a = by_id[i]["data"]
        candidates = [j for j in truth - used if by_id[j]["data"]["scene"] == a["scene"]
                      and abs((by_id[j]["data"]["time"] or 0) - (a["time"] or 0)) <= 15
                      and np.dot(by_id[j]["data"]["embedding"], a["embedding"]) >= .92]
        if candidates:
            used.add(max(candidates, key=lambda j: np.dot(by_id[j]["data"]["embedding"], a["embedding"])))
            hits += 1
    precision = hits / max(len(predicted), 1)
    recall = hits / max(len(truth), 1)
    return {"proposees": len(predicted), "communes": hits, "precision": round(precision, 3), "rappel": round(recall, 3),
            "f1": round(2 * precision * recall / max(precision + recall, 1e-9), 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("rush")
    parser.add_argument("kept")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--selectivity", type=float, default=.5)
    parser.add_argument("--cache")
    parser.add_argument("--report")
    args = parser.parse_args()
    rush, kept, version = load_or_extract(args.rush, args.kept, args.cache)
    pairs = match(rush, kept)
    kept_rush = set(pairs.values())
    order = sorted(range(len(rush)), key=lambda i: (rush[i]["time"] or 0, rush[i]["name"]))
    fold_of = {i: min(k * args.folds // len(order), args.folds - 1) for k, i in enumerate(order)}
    all_rows, predicted_keep, predicted_review = [], set(), set()
    for fold in range(args.folds):
        train_rush = [i for i in range(len(rush)) if fold_of[i] != fold]
        test_rush = [i for i in range(len(rush)) if fold_of[i] == fold]
        train_kept = [k for k, i in pairs.items() if fold_of[i] != fold]
        rows = [{"reportage": "r", "role": "rush", "id": f"r{i}", "data": {**rush[i], "model": version}} for i in train_rush]
        rows += [{"reportage": "r", "role": "kept", "id": f"k{k}", "data": {**kept[k], "model": version}} for k in train_kept]
        model, _ = learn(rows, version)
        snapshot = {"model": version, "references": [], "feedback": [], "selector": model["selector"]}
        batch = []
        for i in test_rush:
            item = rush[i]
            data = propose(item["stats"], item["embedding"], snapshot, args.selectivity)
            data.update({"digest": item["name"], "features": item["stats"], "embedding": item["embedding"], "time": item["time"]})
            batch.append({"id": i, "path": item["name"], "data": data})
        finalize(batch, snapshot, args.selectivity)
        all_rows += batch
        predicted_keep |= {r["id"] for r in batch if r["data"]["decision"] == "keep"}
        predicted_review |= {r["id"] for r in batch if r["data"]["decision"] == "review"}
        print(f"bloc {fold + 1}/{args.folds} : {len(test_rush)} photos, {sum(fold_of[i] == fold for i in kept_rush)} retenues par le photographe", flush=True)
    rate = len(kept_rush) / len(rush)
    rng = np.random.default_rng(0)
    random_pick = set(rng.choice(len(rush), len(predicted_keep), replace=False).tolist())
    report = {
        "photos": len(rush), "retenues_photographe": len(kept_rush), "taux_photographe": round(rate, 3),
        "selectivite": args.selectivity,
        "retenues_atelier": len(predicted_keep), "a_verifier_atelier": len(predicted_review),
        "strict": scores(predicted_keep, kept_rush),
        "meme_moment": same_moment(predicted_keep, kept_rush, all_rows),
        "retenues_et_a_verifier": scores(predicted_keep | predicted_review, kept_rush),
        "hasard_meme_volume": {"strict": scores(random_pick, kept_rush),
                               "meme_moment": same_moment(random_pick, kept_rush, all_rows)},
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
