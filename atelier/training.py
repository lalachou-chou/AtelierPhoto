"""Learn a profile from reportages already sorted by the photographer.

A reportage is the complete rush plus the photos finally delivered (edited
exports). Delivered photos are matched to their original by file name
(``DSC08947N&B.jpg`` → ``DSC08947.JPG``), otherwise by visual similarity.
The matched pairs teach two things:

* which photos are kept (selection model, see selection.py);
* how they are edited (colour look, see look.py).
"""
import re
from pathlib import Path

import numpy as np

from . import look as looks
from . import selection

VISUAL_MATCH = .90


def _stem(name):
    return re.sub(r"[^0-9a-z]", "", Path(name).stem.lower())


def match(rush, kept):
    """Return {kept index: rush index}. ``rush``/``kept``: lists of dicts with name, embedding."""
    stems = {}
    for i, r in enumerate(rush):
        stems.setdefault(_stem(r["name"]), i)
    ordered = sorted(stems, key=len, reverse=True)
    result = {}
    for k, item in enumerate(kept):
        stem = _stem(item["name"])
        if stem in stems:
            result[k] = stems[stem]
            continue
        # Exports often add a suffix: "DSC08947 N&B", "IMG_1234-Edit-2".
        prefix = next((s for s in ordered if len(s) >= 4 and stem.startswith(s)), None)
        if prefix is not None:
            result[k] = stems[prefix]
    unmatched = [k for k in range(len(kept)) if k not in result]
    if unmatched and rush:
        matrix = np.asarray([r["embedding"] for r in rush], dtype=np.float64)
        for k in unmatched:
            similarity = matrix @ np.asarray(kept[k]["embedding"], dtype=np.float64)
            best = int(np.argmax(similarity))
            if similarity[best] >= VISUAL_MATCH:
                result[k] = best
    return result


def learn(rows, load_sample, encoder_version):
    """Build the profile model from stored training rows.

    ``rows``: store.training(profile); ``load_sample(row)`` returns its look sample.
    Returns (model dict, list of warnings).
    """
    warnings = []
    reportages = {}
    for row in rows:
        reportages.setdefault(row["reportage"], {"rush": [], "kept": []})[row["role"]].append(row)
    samples, sources, targets = [], [], []
    summary = {"reportages": 0, "photos": 0, "kept": 0, "pairs": 0}
    for reportage in reportages.values():
        rush = [r for r in reportage["rush"] if r["data"].get("model") == encoder_version]
        kept = [r for r in reportage["kept"] if r["data"].get("model") == encoder_version]
        if not rush or not kept:
            continue
        pairs = match([{"name": r["data"]["name"], "embedding": r["data"]["embedding"]} for r in rush],
                      [{"name": r["data"]["name"], "embedding": r["data"]["embedding"]} for r in kept])
        if len(pairs) < len(kept):
            warnings.append(f"{len(kept) - len(pairs)} photo(s) retenue(s) sans original correspondant dans le rush (ignorées).")
        chosen = set(pairs.values())
        samples.append([{"stats": r["data"]["stats"], "embedding": r["data"]["embedding"], "time": r["data"].get("time"),
                         "name": r["data"]["name"], "kept": i in chosen} for i, r in enumerate(rush)])
        for k, i in pairs.items():
            # Crops and rotations change the framing: such pairs only teach the selection.
            if abs(rush[i]["data"]["stats"]["aspect"] - kept[k]["data"]["stats"]["aspect"]) > .02:
                continue
            source, target = load_sample(rush[i]), load_sample(kept[k])
            if source is not None and target is not None and source.shape == target.shape:
                sources.append(source.astype(np.float32))
                targets.append(target.astype(np.float32))
        summary["reportages"] += 1
        summary["photos"] += len(rush)
        summary["kept"] += len(chosen)
    if not samples:
        raise ValueError("Aucun reportage exploitable : il faut le rush complet et les photos retenues correspondantes.")
    model = dict(summary)
    model["selector"] = selection.train(samples, encoder_version, source="profil")
    try:
        model["look"] = looks.fit(sources, targets)
        model["pairs"] = model["look"]["pairs"]
    except ValueError as exc:
        warnings.append(str(exc))
        model["look"] = None
    return model, warnings
