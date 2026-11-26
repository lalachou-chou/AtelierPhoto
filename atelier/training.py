"""Learn a profile from reportages already sorted by the photographer.

A reportage is the complete rush plus the photos finally delivered (edited
or not). Delivered photos are matched to their original by file name
(``DSC08947N&B.jpg`` → ``DSC08947.JPG``), otherwise by visual similarity.
The matched pairs teach which photos are kept (selection model, see selection.py).
"""
import re
from pathlib import Path

import numpy as np

from . import selection

VISUAL_MATCH = .90
MATCH_MARGIN = .02


def _stem(name):
    return re.sub(r"[^0-9a-z]", "", Path(name).stem.lower())


def match(rush, kept):
    """Return {kept index: rush index}. ``rush``/``kept``: lists of dicts with name, embedding."""
    stems = {}
    for i, r in enumerate(rush):
        stem = _stem(r["name"])
        if stem:
            stems.setdefault(stem, []).append(i)
    ordered = sorted(stems, key=len, reverse=True)
    result = {}
    paths = {Path(r["path"]): i for i, r in enumerate(rush) if r.get("path")}
    matrix = None
    for k, item in enumerate(kept):
        if item.get("path") and Path(item["path"]) in paths:
            result[k] = paths[Path(item["path"])]
            continue
        stem = _stem(item["name"])
        candidates = stems.get(stem, [])
        # Exports often add a suffix: "DSC08947 N&B", "IMG_1234-Edit-2".
        if not candidates:
            prefix = next((s for s in ordered if len(s) >= 4 and stem.startswith(s)
                           and not stem[len(s):len(s) + 1].isdigit()), None)
            candidates = stems[prefix] if prefix is not None else []
        if len(candidates) == 1:
            result[k] = candidates[0]
        elif rush:
            # Duplicate camera names need visual disambiguation. Never silently
            # choose the first file or another frame of an indistinguishable burst.
            candidates = candidates or list(range(len(rush)))
            if matrix is None:
                matrix = np.asarray([r["embedding"] for r in rush], dtype=np.float64)
            similarity = matrix[candidates] @ np.asarray(item["embedding"], dtype=np.float64)
            order = np.argsort(similarity)
            best = int(order[-1])
            separated = len(order) == 1 or similarity[best] - similarity[order[-2]] >= MATCH_MARGIN
            if similarity[best] >= VISUAL_MATCH and separated:
                result[k] = candidates[best]
    return result


def learn(rows, encoder_version):
    """Build the profile's selection model from stored training rows.

    ``rows``: store.training(profile). Returns (model dict, list of warnings).
    """
    warnings = []
    reportages = {}
    for row in rows:
        reportages.setdefault(row["reportage"], {"rush": [], "kept": []})[row["role"]].append(row)
    samples = []
    summary = {"reportages": 0, "photos": 0, "kept": 0}
    for reportage in reportages.values():
        rush, kept = reportage["rush"], reportage["kept"]
        if any(r["data"].get("model") != encoder_version for r in rush + kept):
            warnings.append("Un reportage utilise un ancien modèle d’image : réimportez-le (ignoré).")
            continue
        if not rush or not kept:
            warnings.append("Un reportage incomplet a été ignoré : rush et photos retenues sont nécessaires.")
            continue
        pairs = match([dict(r["data"], path=r.get("path")) for r in rush],
                      [dict(r["data"], path=r.get("path")) for r in kept])
        if len(pairs) < len(kept):
            warnings.append(f"{len(kept) - len(pairs)} photo(s) retenue(s) sans original certain dans le rush (ignorées).")
        if not pairs:
            # No positive labels means an unmatched reportage would teach the
            # model to reject all its photos, even though the user kept some.
            warnings.append("Un reportage sans correspondance certaine a été exclu de l’apprentissage.")
            continue
        chosen = set(pairs.values())
        samples.append([{"stats": r["data"]["stats"], "embedding": r["data"]["embedding"], "time": r["data"].get("time"),
                         "name": r["data"]["name"], "kept": i in chosen} for i, r in enumerate(rush)])
        summary["reportages"] += 1
        summary["photos"] += len(rush)
        summary["kept"] += len(chosen)
    if not samples:
        raise ValueError("Aucun reportage exploitable : il faut le rush complet et les photos retenues correspondantes.")
    model = dict(summary, encoder=encoder_version)
    try:
        model["selector"] = selection.train(samples, encoder_version, source="profil")
    except ValueError as exc:
        warnings.append(str(exc))
        model["selector"] = None
    return model, warnings
