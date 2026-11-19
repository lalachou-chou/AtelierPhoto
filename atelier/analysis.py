import copy

import numpy as np

from .framing import FULL_FRAME, ratio_crop
from .imaging import NEUTRAL, clamp_recipe, color_features, render
from .local import suggest
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
    peak = stats["peak"]
    if stats["black"] > .97 or stats["white"] > .97:
        return "reject", ["Image presque entièrement noire ou blanche"]
    if peak < .00012 + .00018 * selectivity and stats["spread"] > .12:
        if kept_before:
            return "review", ["Photo floue, mais vous avez retenu une photo proche : à vérifier"]
        return "reject", ["Photo entièrement floue : mise au point manquée ou bougé"]
    if stats["sharpness"] < .0003 + .0007 * selectivity:
        return "review", ["Netteté incertaine : flou artistique ou sujet à vérifier"]
    return "keep", []


def rendering_target(entry, stats):
    if "before" not in entry:
        return entry["features"]
    before, after = entry["before"], entry["after"]
    target = {key: float(np.clip((stats[key] + .05) * (after[key] + .05) / (before[key] + .05) - .05, 0, 1))
              for key in ("luma", "spread", "saturation")}
    if entry["features"]["saturation"] < .015:
        target["saturation"] = 0.
    target["rgb"] = np.clip(np.array(stats["rgb"]) + np.array(after["rgb"]) - before["rgb"], 0, 1)
    return target


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
    paired = similar(embedding, snapshot.get("examples", []))
    # When the LUT could not be fitted (e.g. a single pair), the delivered
    # image still supplies a local rendering target.
    # A fitted personal look already renders colour; only monochrome examples still add a target.
    personal = snapshot.get("personal_look")
    # A RAW reference without sidecar shows no delivered look: resemblance only.
    targets = [n for n in nearest if n[0].get("render", True)] + [p for p in paired if p[1] >= .82 and (not personal or p[0]["features"]["saturation"] < .015)]
    targets.sort(key=lambda hit: hit[1], reverse=True)
    target = [rendering_target(entry, stats) for entry, score in targets[:3] if score >= targets[0][1] - .08]
    if target:
        # Correct the remaining difference after the learned look, so the two
        # sources of learning complement each other instead of doubling the look.
        rendered = color_features(render(small, LEARNED_NEUTRAL, style, look)) if "knots" in style else stats
        def median(k):
            return float(np.median([t[k] for t in target]))
        style["exposure"] = float(np.clip(np.log2((median("luma") + .05) / (rendered["luma"] + .05)), -.65, .65))
        rgb = np.median([t["rgb"] for t in target], axis=0)
        style["temperature"] = float(np.clip(((rgb[0] - rgb[2]) - (rendered["rgb"][0] - rendered["rgb"][2])) * 1.5, -.35, .35))
        style["contrast"] = float(np.clip((median("spread") - rendered["spread"]) / max(.15, rendered["spread"]), -.45, .45))
        saturation = median("saturation")
        style["saturation"] = (-1. if saturation < .015 and rendered["saturation"] >= .015 else
                               float(np.clip((saturation - rendered["saturation"]) / max(.15, rendered["saturation"]), -.6, .6)))
    base = LEARNED_NEUTRAL if "knots" in style or target else NEUTRAL
    recipe = dict(base)
    # Search the relevant corrections separately. Selection-only decisions
    # should not displace edits in the nearest neighbours.
    edits = similar(embedding, snapshot.get("edit_feedback", snapshot["feedback"]))
    for key in recipe:
        corrections = [(f["manual_settings"][key] if "manual_settings" in f else base[key] + f["delta"][key], s)
                       for f, s in edits if s > .82 and ("manual_settings" in f or key in f["delta"])]
        if corrections:
            recipe[key] = float(np.average([v for v, _ in corrections], weights=[s ** 6 for _, s in corrections]))
    recipe = clamp_recipe(recipe)
    local_edits = learned_local_edits(embedding, snapshot)
    tools = learned_tools(embedding, snapshot)
    aspect = stats.get("aspect")
    framing = {}
    if aspect:
        manual_crops = similar(embedding, snapshot.get("crop_feedback", []))
        for matches in (manual_crops, paired):
            close = [(e, s) for e, s in matches if "crop" in e and e.get("aspect") and s >= .82
                     and abs(np.log(aspect / e["aspect"])) < .18]
            if close:
                best = close[0][1]
                edges = np.median([e["crop"] for e, s in close if s >= best - .035], axis=0).tolist()
                framing = {"crop": None if edges == FULL_FRAME else edges}
                break
        if not framing:
            ratios = [e["features"]["aspect"] for e, s in nearest if s >= .82 and e["features"].get("aspect")
                      and (abs(np.log(e["features"]["aspect"])) < .04 or (e["features"]["aspect"] >= 1) == (aspect >= 1))]
            if ratios:
                framing = {"crop": ratio_crop(aspect, float(np.median(ratios)))}
        if framing:
            framing["initial_crop"] = framing["crop"]
    votes = [1 if f["decision"] == "keep" else -1 for f, _ in feedback if f["decision"] in ("keep", "reject")]
    preference = float(np.mean(votes)) if votes else 0.
    if not reasons:
        reasons.append("Qualité technique satisfaisante")
    return {"proposed": status, "decision": status, "reasons": reasons, "similarity": similarity,
            "preference": preference, "blocked": blocked, "style": style,
            "base_recipe": dict(base), "initial_recipe": dict(recipe), "recipe": recipe,
            "validated": False, "group": None, "local_edits": local_edits,
            "initial_local_edits": [dict(e) for e in local_edits],
            "tools": tools, "initial_tools": copy.deepcopy(tools), **framing}


def learned_tools(embedding, snapshot):
    """Clarity, curve and HSL validated on similar photos (weighted mean), or {}."""
    from .tools import mean
    neighbours = [(f["tools"], s ** 6) for f, s in similar(embedding, snapshot.get("tools_feedback", [])) if s > .82]
    return mean(neighbours) or {}


def learned_local_edits(embedding, snapshot):
    """Zone edits validated on similar photos, proposed again; masks are recomputed per photo."""
    from .prompt import describe
    from .store import uid
    neighbours = [(f, s) for f, s in similar(embedding, snapshot.get("local_feedback", [])) if s > .82]
    proposals = []
    for edit in suggest(neighbours):
        edit.update(id=uid(), prompt="Appris de vos photos validées", strength=1., enabled=True, proposed=True)
        edit["label"] = describe(edit) + " (appris)"
        proposals.append(edit)
    return proposals


def _plural(n, word):
    return f"{n} {word}{'s' if n > 1 else ''}"


def reselect(rows, snapshot, selectivity, cancel=None):
    """Recalculate from cached analysis, preserving explicit decisions and all edits."""
    manual = {}
    for row in rows:
        if cancel is not None and cancel.is_set():
            return None
        data = row["data"]
        if "error" in data:
            continue
        if data.get("manual_decision"):
            manual[row["id"]] = data["decision"]
        proposal = propose(data["features"], data["embedding"], snapshot, selectivity)
        for key in ("proposed", "decision", "reasons", "similarity", "preference", "blocked"):
            data[key] = proposal[key]
    finalize(rows, snapshot, selectivity)
    for row in rows:
        data = row["data"]
        if "error" in data:
            continue
        if row["id"] in manual:
            data["decision"] = manual[row["id"]]
            data["manual_decision"] = True
            data["reasons"].insert(0, "Votre choix manuel est conservé")
        data["validated"] = False
    return rows


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
        if snapshot["references"]:
            # Positive examples complement either the bundled or learned selector;
            # without a rush, references cannot supply negative training labels.
            scores += 2. * (float(np.std(scores)) or 1.) * np.asarray([d.get("similarity", 0.) for d in data])
        source = "profil" if selector.get("source") == "profil" else "défaut"
        base_rate = selector["rate"] if source == "profil" else None
    else:
        scores = heuristic(x) + 2. * np.asarray([d.get("similarity", 0.) for d in data])
        base_rate = None
        source = None
    spread = float(np.std(scores)) or 1.
    scores = scores + spread * np.asarray([d.get("preference", 0.) for d in data])
    blocked = {i for i, d in enumerate(data) if d["blocked"]}
    first_by_digest = {}
    duplicates = set()
    for i, d in enumerate(data):
        j = first_by_digest.setdefault(d["digest"], i)
        if j != i:
            duplicates.add(i)
    keep_rate, review_rate = rates(base_rate, selectivity)
    uncertain = {i for i, d in enumerate(data) if d["proposed"] == "review"
                 and any(reason != "Qualité technique satisfaisante" for reason in d["reasons"])}
    decisions = decide(scores, labels, embeddings, keep_rate, review_rate, blocked | duplicates, uncertain)
    best = {}
    for i in np.argsort(-scores):
        if i not in blocked and i not in duplicates:
            best.setdefault(labels[i], int(i))
    kept_scenes = {labels[i] for i in range(len(data)) if decisions[i] == "keep"}
    sizes = np.bincount(labels)
    # Keep a single group identifier even when every frame was rejected.
    for i, label in enumerate(labels):
        best.setdefault(label, i)
    for i, d in enumerate(data):
        label = labels[i]
        size = int(sizes[label])
        leader = best[label]
        d["score"] = float(scores[i])
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
        d["reasons"] = ([reason] if reason else []) + technical_notes
        if source and i not in duplicates:
            d["reasons"].append(f"Modèle de sélection : {source}")
        if snapshot["references"] and i not in blocked and i not in duplicates:
            d["reasons"].append("Vos références contribuent au classement par ressemblance")
        d["proposed"] = d["decision"] = status
        d.pop("selection_pending", None)
    return rows
