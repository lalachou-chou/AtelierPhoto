"""Scene-aware photo selection learned from already sorted reportages.

A wedding rush contains bursts: several frames of the same moment. A
photographer keeps roughly one frame per worthwhile moment. The selection
therefore works in three steps:

1. ``scenes`` splits the chronological sequence into moments (time gap and
   DINOv3 similarity to the running scene centroid).
2. ``design`` builds one vector per photo: technical measures, context within
   its scene (relative sharpness, centrality, scene size) and the DINOv3
   embedding (content: portraits, couple, details...).
3. A logistic model trained on sorted reportages (rush + kept photos) scores
   each photo; ``decide`` keeps the best frame of the best scenes and adds a
   second frame only when it is visually different.

Everything is plain numpy so that training also runs inside the application.
"""
import numpy as np

FEATURE_VERSION = 2
TECH_KEYS = ("luma", "spread", "saturation", "sharpness", "peak", "noise", "black", "white")
SCENE_GAP = 20.  # seconds
SCENE_SIMILARITY = .80
DISTINCT = .93  # a second photo of a scene must differ at least this much
DEFAULT_C = .02


def tech_vector(stats):
    x = np.array([float(stats[k]) for k in TECH_KEYS], dtype=np.float64)
    x[3:6] = np.log(np.maximum(x[3:6], 0.) + 1e-6)
    return x


def chronological(times, names):
    """Sort key: capture time, then file name (bursts share whole seconds)."""
    return sorted(range(len(times)), key=lambda i: (times[i] if times[i] is not None else float("inf"), names[i]))


def scenes(times, embeddings, gap=None, similarity=None):
    """Labels for photos already in chronological order."""
    gap = SCENE_GAP if gap is None else gap
    similarity = SCENE_SIMILARITY if similarity is None else similarity
    embeddings = np.asarray(embeddings, dtype=np.float64)
    labels = np.zeros(len(embeddings), dtype=int)
    if not len(embeddings):
        return labels
    current, centroid = 0, embeddings[0].copy()
    for i in range(1, len(embeddings)):
        t0, t1 = times[i - 1], times[i]
        far = t0 is None or t1 is None or t1 - t0 > gap
        direction = centroid / max(np.linalg.norm(centroid), 1e-12)
        if far or embeddings[i] @ direction < similarity:
            current += 1
            centroid = embeddings[i].copy()
        else:
            centroid += embeddings[i]
        labels[i] = current
    return labels


def context(tech, times, embeddings, labels):
    embeddings = np.asarray(embeddings, dtype=np.float64)
    result = np.zeros((len(labels), 8))
    for label in np.unique(labels):
        members = np.where(labels == label)[0]
        sharp, peak = tech[members, 3], tech[members, 4]
        centroid = embeddings[members].mean(0)
        centroid /= max(np.linalg.norm(centroid), 1e-12)
        rank = np.argsort(np.argsort(-sharp))
        known = [times[i] for i in members if times[i] is not None]
        duration = max(known) - min(known) if known else 0.
        result[members, 0] = np.log(len(members))
        result[members, 1] = sharp - sharp.max()
        result[members, 2] = rank == 0
        result[members, 3] = rank / max(len(members) - 1, 1)
        result[members, 4] = embeddings[members] @ centroid
        result[members, 5] = peak - peak.max()
        result[members, 6] = np.log1p(max(duration, 0.))
        result[members, 7] = sharp - sharp.mean()
    return result


def design(stats, embeddings, times):
    """Feature matrix and scene labels for photos in chronological order."""
    tech = np.array([tech_vector(s) for s in stats]) if stats else np.zeros((0, len(TECH_KEYS)))
    labels = scenes(times, embeddings)
    ctx = context(tech, times, embeddings, labels)
    return np.hstack([tech, ctx, np.asarray(embeddings, dtype=np.float64)]), labels


def fit_logistic(x, y, c=DEFAULT_C, iterations=50):
    """L2 logistic regression (same objective as scikit-learn's C) by Newton steps."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    mu = x.mean(0)
    sd = x.std(0) + 1e-9
    z = np.hstack([(x - mu) / sd, np.ones((len(x), 1))])
    w = np.zeros(z.shape[1])
    penalty = np.full(z.shape[1], 1. / c)
    penalty[-1] = 0.  # intercept is not penalised
    for _ in range(iterations):
        p = 1. / (1. + np.exp(-np.clip(z @ w, -30, 30)))
        gradient = z.T @ (p - y) + penalty * w
        hessian = (z * (p * (1 - p))[:, None]).T @ z + np.diag(penalty + 1e-9)
        step = np.linalg.solve(hessian, gradient)
        w -= step
        if np.max(np.abs(step)) < 1e-7:
            break
    return {"mu": mu.tolist(), "sd": sd.tolist(), "w": w[:-1].tolist(), "b": float(w[-1])}


def score(model, x):
    x = np.asarray(x, dtype=np.float64)
    return ((x - np.asarray(model["mu"])) / np.asarray(model["sd"])) @ np.asarray(model["w"]) + model["b"]


def compatible(selector, encoder_version, dimension):
    return bool(selector) and selector.get("feature_version") == FEATURE_VERSION \
        and selector.get("encoder") == encoder_version and selector.get("dimension") == dimension


def train(samples, encoder_version, c=DEFAULT_C, source=""):
    """``samples``: list of reportages, each a list of dicts with stats, embedding, time, name, kept."""
    xs, ys, total = [], [], 0
    for reportage in samples:
        order = chronological([s["time"] for s in reportage], [s["name"] for s in reportage])
        ordered = [reportage[i] for i in order]
        x, _ = design([s["stats"] for s in ordered], [s["embedding"] for s in ordered], [s["time"] for s in ordered])
        xs.append(x)
        ys.extend(bool(s["kept"]) for s in ordered)
        total += len(ordered)
    y = np.asarray(ys)
    if total < 6 or y.sum() < 2 or y.sum() == len(y):
        raise ValueError("Pas assez de photos triées pour apprendre (au moins 6 photos dont 2 retenues, "
                         "idéalement un reportage complet de plusieurs centaines de photos).")
    model = fit_logistic(np.vstack(xs), y, c)
    dimension = int(np.vstack(xs).shape[1] - len(TECH_KEYS) - 8)
    model.update({"feature_version": FEATURE_VERSION, "encoder": encoder_version, "dimension": dimension,
                  "rate": float(y.mean()), "photos": int(total), "kept": int(y.sum()), "source": source})
    return model


def heuristic(x):
    """Fallback without a compatible model: sharpest and most typical frame of each scene."""
    return 2. * x[:, len(TECH_KEYS) + 1] + 1.5 * x[:, len(TECH_KEYS) + 2] + 3. * x[:, len(TECH_KEYS) + 4]


def rates(base_rate, selectivity):
    """Selectivity 0 (prudente) keeps about twice as much as 1 (exigeante)."""
    keep = float(np.clip(base_rate * 1.25 * 2 ** ((.5 - selectivity) * 2), .03, .9))
    return keep, float(min(keep, 1 - keep))


def decide(scores, labels, embeddings, keep_rate, review_rate, blocked=()):
    """Return 'keep' / 'review' / 'reject' per photo (chronological order).

    ``blocked`` photos (technical failure) are never kept.
    """
    n = len(scores)
    embeddings = np.asarray(embeddings, dtype=np.float64)
    blocked = set(blocked)
    budget = max(1, int(round(keep_rate * n))) if n else 0
    order = [i for i in np.argsort(-np.asarray(scores)) if i not in blocked]
    best = {}
    for i in order:
        best.setdefault(labels[i], i)
    keep = np.zeros(n, dtype=bool)
    # 70 % of the budget: one frame per moment, best moments first.
    for i in order:
        if keep.sum() >= round(budget * .7):
            break
        if best[labels[i]] == i:
            keep[i] = True
    # Remaining budget: any good frame that adds something to its scene.
    for i in order:
        if keep.sum() >= budget:
            break
        if keep[i]:
            continue
        same = np.where(keep & (labels == labels[i]))[0]
        if all(embeddings[i] @ embeddings[j] < DISTINCT for j in same):
            keep[i] = True
    review = np.zeros(n, dtype=bool)
    review_budget = int(round(review_rate * n))
    # Moments without any kept frame first, then the alternatives of kept moments.
    covered = set(labels[keep])
    candidates = [i for i in order if not keep[i] and labels[i] not in covered and best[labels[i]] == i]
    first = set(candidates)
    candidates += [i for i in order if not keep[i] and i not in first]
    for i in candidates[:review_budget]:
        review[i] = True
    return np.where(keep, "keep", np.where(review, "review", "reject"))
