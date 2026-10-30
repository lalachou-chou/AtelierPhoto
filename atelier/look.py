"""Colour look learned from pairs (original rush photo, photographer's edit).

The look has two parts:

* a smooth 3D colour table (``N``³ lattice, trilinear interpolation) shared by
  every photo: the photographer's colour signature (warmth, skin, greens...);
* a per-photo luminance curve whose 9 control points are predicted from the
  photo's own tone statistics (ridge regression): a dark church and a bright
  garden do not receive the same exposure correction.

Both are fitted with closed-form least squares, so training runs locally in a
few seconds. Rendering is pointwise and resolution independent.
"""
import numpy as np
from PIL import Image, ImageFilter

LUT_SIZE = 9
KNOTS = 9
SAMPLE_WIDTH = 48
LUMA = np.array([.2126, .7152, .0722])


def sample(pixels):
    """Small, slightly blurred proxy used both for training and per-photo statistics."""
    image = Image.fromarray(np.round(np.clip(pixels, 0, 1) * 255).astype(np.uint8))
    image.thumbnail((256, 256), Image.Resampling.LANCZOS)
    image = image.filter(ImageFilter.GaussianBlur(1.5))
    height = max(1, round(SAMPLE_WIDTH * image.height / image.width))
    image = image.resize((SAMPLE_WIDTH, height), Image.Resampling.BOX)
    return np.asarray(image, dtype=np.float32) / 255


def tone_statistics(small):
    luma = small.reshape(-1, 3) @ LUMA
    mean = small.reshape(-1, 3).mean(0)
    return np.r_[np.quantile(luma, [.01, .05, .1, .25, .5, .75, .9, .95, .99]), mean, mean[0] - mean[2],
                 (luma < .03).mean(), (luma > .97).mean()]


def _trilinear(x, n):
    g = np.clip(x, 0, 1) * (n - 1)
    i0 = np.minimum(np.floor(g).astype(np.int64), n - 2)
    f = g - i0
    index, weight = [], []
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                index.append(((i0[:, 0] + dx) * n + (i0[:, 1] + dy)) * n + (i0[:, 2] + dz))
                weight.append((f[:, 0] if dx else 1 - f[:, 0]) * (f[:, 1] if dy else 1 - f[:, 1])
                              * (f[:, 2] if dz else 1 - f[:, 2]))
    return np.stack(index, 1), np.stack(weight, 1)


def _hat(luma):
    g = np.clip(luma, 0, 1) * (KNOTS - 1)
    i0 = np.minimum(np.floor(g).astype(np.int64), KNOTS - 2)
    f = g - i0
    w = np.zeros((luma.size, KNOTS))
    rows = np.arange(luma.size)
    w[rows, i0] = 1 - f
    w[rows, i0 + 1] = f
    return w


def apply_lut(lut, x, n=LUT_SIZE):
    index, weight = _trilinear(x.reshape(-1, 3), n)
    return (np.asarray(lut, dtype=np.float32)[index] * weight[..., None].astype(np.float32)).sum(1).reshape(x.shape)


def apply_tone(x, knots):
    luma = x.reshape(-1, 3) @ LUMA.astype(np.float32)
    shift = _hat(luma) @ np.asarray(knots, dtype=np.float64)
    return (x.reshape(-1, 3) + shift[:, None].astype(np.float32)).reshape(x.shape)


def fit_lut(sources, targets, n=LUT_SIZE, smooth=.05):
    x = np.concatenate([a.reshape(-1, 3) for a in sources]).astype(np.float64)
    t = np.concatenate([b.reshape(-1, 3) for b in targets]).astype(np.float64)
    index, weight = _trilinear(x, n)
    size = n ** 3
    a = np.zeros(size * size)
    for j in range(8):
        for k in range(8):
            a += np.bincount(index[:, j] * size + index[:, k], weights=weight[:, j] * weight[:, k], minlength=size * size)
    a = a.reshape(size, size)
    b = np.stack([sum(np.bincount(index[:, j], weights=weight[:, j] * t[:, c], minlength=size) for j in range(8))
                  for c in range(3)], 1)
    grid = np.stack(np.meshgrid(*[np.arange(n)] * 3, indexing="ij"), -1).reshape(-1, 3)
    laplacian = np.zeros((size, size))
    for axis in range(3):
        neighbour = grid.copy()
        neighbour[:, axis] += 1
        valid = neighbour[:, axis] < n
        i = np.where(valid)[0]
        j = (neighbour[valid, 0] * n + neighbour[valid, 1]) * n + neighbour[valid, 2]
        np.add.at(laplacian, (i, i), 1)
        np.add.at(laplacian, (j, j), 1)
        np.add.at(laplacian, (i, j), -1)
        np.add.at(laplacian, (j, i), -1)
    identity = grid / (n - 1)
    scale = len(x) / size
    lut = np.linalg.solve(a + smooth * scale * laplacian + 1e-3 * scale * np.eye(size), b + 1e-3 * scale * identity)
    return np.clip(lut, -.1, 1.1)


def _fit_knots(source, target):
    luma = source.reshape(-1, 3) @ LUMA
    w = _hat(luma)
    residual = target.reshape(-1, 3) @ LUMA - luma
    return np.linalg.solve(w.T @ w + .02 * np.eye(KNOTS), w.T @ residual)


def alignment(source, target):
    """Correlation of luminance edges: about 1 for the same framing, low after a crop."""
    if source.shape != target.shape:
        return 0.
    def edges(x):
        luma = x.astype(np.float64) @ LUMA
        return (np.diff(luma, axis=0)[:, :-1] + np.diff(luma, axis=1)[:-1]).ravel()
    a, b = edges(source), edges(target)
    if a.std() < 1e-6 or b.std() < 1e-6:
        return 0.
    return float(np.corrcoef(a, b)[0, 1])


def usable_pair(source, target):
    """Same framing (not cropped or straightened) and not a black & white version."""
    return alignment(source, target) >= .9 and not is_monochrome(target)


def is_monochrome(pixels):
    x = pixels.reshape(-1, 3)
    return float(np.mean(x.max(1) - x.min(1))) < .015


def fit(sources, targets, ridge=30.):
    """``sources``/``targets``: lists of aligned ``sample`` arrays."""
    pairs = [(a, b) for a, b in zip(sources, targets, strict=True) if usable_pair(a, b)]
    if len(pairs) < 5:
        raise ValueError("Pas assez de paires original / retouche pour apprendre le filtre (au moins 5).")
    sources = [a for a, _ in pairs]
    targets = [b for _, b in pairs]
    lut = fit_lut(sources, targets)
    knots = np.array([_fit_knots(apply_lut(lut, a), b) for a, b in pairs])
    stats = np.array([tone_statistics(a) for a in sources])
    mu, sd = stats.mean(0), stats.std(0) + 1e-6
    z = np.hstack([np.ones((len(stats), 1)), (stats - mu) / sd])
    penalty = np.eye(z.shape[1]) * ridge
    penalty[0, 0] = 1e-6
    coef = np.linalg.solve(z.T @ z + penalty, z.T @ knots)
    return {"version": 1, "lut_size": LUT_SIZE, "lut": np.round(lut, 5).tolist(),
            "tone": {"mu": mu.tolist(), "sd": sd.tolist(), "coef": coef.tolist()}, "pairs": len(pairs)}


def knots_for(look, small):
    tone = look["tone"]
    z = np.r_[1., (tone_statistics(small) - np.asarray(tone["mu"])) / np.asarray(tone["sd"])]
    return np.clip(z @ np.asarray(tone["coef"]), -.25, .25).tolist()


def apply(look, pixels, knots):
    """Pointwise look: colour table then the photo's tone curve."""
    x = apply_lut(look["lut"], pixels, look.get("lut_size", LUT_SIZE))
    return apply_tone(x, knots) if knots is not None else x
