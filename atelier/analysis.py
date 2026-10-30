import numpy as np

from .imaging import NEUTRAL, clamp_recipe
from .look import knots_for
from .selection import (
    chronological,
    compatible,
    decide,
    design,
    heuristic,
    rates,
    score,
)

_MATRICES = []


def _matrix(entries):
    """Embedding matrix of a snapshot list, built once per list instead of once per photo."""
    for source, matrix in _MATRICES:
        if source is entries:
            return matrix
    matrix = np.asarray([e["embedding"] for e in entries], dtype=np.float32)
    # Holding the list keeps its identity unique while it is cached.
    _MATRICES.append((entries, matrix))
    del _MATRICES[:-4]
    return matrix


def similar(embedding, entries, limit=8):
    if not entries:
        return []
    scores = _matrix(entries) @ np.asarray(embedding, dtype=np.float32)
    count = min(limit, len(entries))
    top = np.argpartition(scores, -count)[-count:]
    top = top[np.argsort(scores[top])[::-1]]
    return [(entries[int(i)], float(scores[i])) for i in top]


LEARNED_NEUTRAL = dict(NEUTRAL, intensity=1.)


def technical(stats, selectivity, kept_before):
    """Hard technical verdict. Only blank frames and whole-frame blur are rejected."""
    peak = stats.get("peak", stats["sharpness"])
    if stats["black"] > .97 or stats["white"] > .97:
        return "reject", ["Image presque entièrement noire ou blanche"]
    if peak < .00012 + .00018 * selectivity and stats["spread"] > .12:
        if kept_before:
            return "review", ["Photo floue, mais vous avez retenu une photo proche : à vérifier"]
        return "reject", ["Photo entièrement floue : mise au point manquée ou bougé"]
    if stats["sharpness"] < .0003 + .0007 * selectivity:
        return "review", ["Netteté incertaine : flou artistique ou sujet à vérifier"]
    return "keep", []


def propose(stats, embedding, snapshot, selectivity=.5, small=None):
    """Per-photo proposal. The final selection is made per scene by ``finalize``."""
    nearest = similar(embedding, snapshot["references"])
    similarity = float(np.mean([s for _, s in nearest[:3]])) if nearest else 0.
    feedback = [(e, s) for e, s in similar(embedding, snapshot["feedback"]) if s > .82]
    kept_before = any(e["decision"] == "keep" for e, _ in feedback)
    status, reasons = technical(stats, selectivity, kept_before)
    blocked = status == "reject"
    if stats["black"] > .35 or stats["white"] > .25:
        reasons.append("Ombres ou hautes lumières potentiellement perdues")
        if status == "keep":
            status = "review"
    if stats["noise"] > .035:
        reasons.append("Bruit visible possible")
        if status == "keep":
            status = "review"
    if snapshot["references"] and not snapshot.get("selector"):
        affinity = similarity + (.04 if kept_before else 0.)
        if not nearest or affinity < .60 + .12 * selectivity:
            reasons.append("Éloignée des références : décision à confirmer")
            if status == "keep":
                status = "review"
    if status == "keep" and any(e["decision"] in ("reject", "review") for e, _ in feedback):
        status = "review"
        reasons.append("Une correction passée invite à vérifier cette photo")
    look = snapshot.get("look")
    style = {"exposure": 0., "temperature": 0., "contrast": 0., "saturation": 0.}
    if look and small is not None:
        style["knots"] = knots_for(look, small)
    else:
        target = [entry["features"] for entry, _ in nearest]
        if target:
            def median(k):
                return float(np.median([t[k] for t in target]))
            style["exposure"] = float(np.clip(np.log2((median("luma") + .05) / (stats["luma"] + .05)), -.65, .65))
            rgb = np.median([t["rgb"] for t in target], axis=0)
            style["temperature"] = float(np.clip(((rgb[0] - rgb[2]) - (stats["rgb"][0] - stats["rgb"][2])) * 1.5, -.35, .35))
            style["contrast"] = float(np.clip(median("spread") - stats["spread"], -.2, .2))
            style["saturation"] = float(np.clip(median("saturation") - stats["saturation"], -.25, .25))
    base = LEARNED_NEUTRAL if "knots" in style else NEUTRAL
    recipe = dict(base)
    for key in recipe:
        corrections = [f["delta"][key] for f, _ in feedback if key in f["delta"]]
        if corrections:
            recipe[key] += float(np.mean(corrections))
    recipe = clamp_recipe(recipe)
    votes = [1 if f["decision"] == "keep" else -1 for f, _ in feedback if f["decision"] in ("keep", "reject")]
    preference = float(np.mean(votes)) if votes else 0.
    quality = float(np.clip(stats["sharpness"] * 80, 0, 1) - stats["black"] * .5 - stats["white"] * .7 - stats["noise"] + .1 * preference)
    if not reasons:
        reasons.append("Qualité technique satisfaisante")
    return {"proposed": status, "decision": status, "reasons": reasons, "similarity": similarity,
            "quality": quality, "preference": preference, "blocked": blocked, "style": style,
            "base_recipe": dict(base), "initial_recipe": dict(recipe), "recipe": recipe,
            "validated": False, "group": None}


def _plural(n, word):
    return f"{n} {word}{'s' if n > 1 else ''}"


def finalize(rows, snapshot, selectivity=.5):
    """Scene-aware decisions for a whole batch (rows are updated in place).

    Photos are ordered by capture time and split into moments; the profile's
    learned model (or the sharpness heuristic) ranks them; the best frame of
    the best moments is kept, alternatives go to review, the rest is set aside.
    Technical failures stay rejected; exact copies are rejected.
    """
    valid = [r for r in rows if "error" not in r["data"]]
    if not valid:
        return rows
    order = chronological([r["data"].get("time") for r in valid], [str(r["path"]) for r in valid])
    valid = [valid[i] for i in order]
    data = [r["data"] for r in valid]
    embeddings = np.asarray([d["embedding"] for d in data], dtype=np.float64)
    times = [d.get("time") for d in data]
    x, labels = design([d["features"] for d in data], embeddings, times)
    selector = snapshot.get("selector")
    if compatible(selector, snapshot.get("model"), embeddings.shape[1]):
        scores = score(selector, x)
        base_rate = selector["rate"]
        source = "profil" if selector.get("source") == "profil" else "défaut"
    else:
        scores = heuristic(x) + 2. * np.asarray([d.get("similarity", 0.) for d in data])
        base_rate = .16
        source = None
    spread = float(np.std(scores)) or 1.
    scores = scores + spread * np.asarray([d.get("preference", 0.) for d in data])
    blocked = {i for i, d in enumerate(data) if d.get("blocked", d["proposed"] == "reject")}
    first_by_digest = {}
    duplicates = set()
    for i, d in enumerate(data):
        j = first_by_digest.setdefault(d["digest"], i)
        if j != i:
            duplicates.add(i)
    keep_rate, review_rate = rates(base_rate, selectivity)
    decisions = decide(scores, labels, embeddings, keep_rate, review_rate, blocked | duplicates)
    best = {}
    for i in np.argsort(-scores):
        if i not in blocked and i not in duplicates:
            best.setdefault(labels[i], int(i))
    kept_scenes = {labels[i] for i in range(len(data)) if decisions[i] == "keep"}
    sizes = np.bincount(labels)
    for i, d in enumerate(data):
        label = labels[i]
        size = int(sizes[label])
        leader = best.get(label, i)
        d["score"] = float(scores[i])
        d["scene"] = int(label)
        d["group"] = valid[leader]["id"] if size > 1 else None
        technical_notes = [r for r in d["reasons"] if r != "Qualité technique satisfaisante"]
        if i in duplicates:
            status, reason = "reject", "Doublon exact ; un exemplaire est conservé"
        elif i in blocked:
            status, reason = "reject", None
        else:
            status = str(decisions[i])
            if status == "keep":
                reason = (f"Meilleure image de la scène ({_plural(size, 'photo')})" if leader == i
                          else "Autre image réussie et différente de la même scène")
            elif status == "review":
                reason = ("Moment sans photo retenue : à confirmer" if label not in kept_scenes
                          else "Variante de la photo retenue : comparer")
            else:
                reason = ("Moins réussie que la photo retenue de la même scène" if label in kept_scenes
                          else "Moment jugé secondaire par le profil")
            # A past correction or a technical doubt never lets a photo through unseen.
            if status == "keep" and d["proposed"] == "review" and technical_notes:
                status = "review"
        d["reasons"] = ([reason] if reason else []) + technical_notes
        if source and i not in duplicates:
            d["reasons"].append(f"Modèle de sélection : {source}")
        d["proposed"] = d["decision"] = status
    return rows
