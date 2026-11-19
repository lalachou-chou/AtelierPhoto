"""Estimate axis-aligned crops from the small, oriented training samples."""
import numpy as np
from PIL import Image

from .look import LUMA, alignment

FULL_FRAME = [0., 0., 1., 1.]


def _resize(pixels, width, height):
    image = Image.fromarray(np.uint8(np.clip(pixels, 0, 1) * 255))
    return np.asarray(image.resize((width, height), Image.Resampling.BILINEAR), dtype=np.float32) / 255


def register_pair(source, target):
    """Return aligned source pixels and normalized edges, or abstain on a weak match."""
    if source.shape == target.shape and alignment(source, target) >= .9:
        return source, FULL_FRAME
    h, w = source.shape[:2]
    th, tw = target.shape[:2]
    # At each possible scale, locate the delivered frame by zero-mean
    # normalized cross correlation. Integral images normalize every candidate
    # window; FFT computes the dot products without materializing the windows.
    gray = source @ LUMA
    integral = np.pad(gray, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    squares = np.pad(gray ** 2, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    transform = np.fft.rfft2(gray)
    def windows(table, height, width):
        return table[height:, width:] - table[:-height, width:] - table[height:, :-width] + table[:-height, :-width]

    candidates = []
    for width in range(max(8, round(w * .25)), w + 1):
        height = round(width * th / tw)
        if height < 8 or height > h:
            continue
        template = _resize(target, width, height) @ LUMA
        template -= template.mean()
        norm = np.linalg.norm(template)
        if norm < .001:
            continue
        corr = np.fft.irfft2(transform * np.fft.rfft2(template, s=(h, w), axes=(0, 1)).conj(),
                             s=(h, w), axes=(0, 1))[:h-height+1, :w-width+1]
        variance = windows(squares, height, width) - windows(integral, height, width) ** 2 / (width * height)
        scores = corr / (norm * np.sqrt(np.maximum(variance, 1e-10)))
        # Keep two separated locations so repeating textures cannot teach an arbitrary offset.
        for _ in range(2):
            y, x = np.unravel_index(scores.argmax(), scores.shape)
            score = scores[y, x]
            if score < .88:
                break
            box = np.array([x / w, y / h, (x + width) / w, (y + height) / h])
            candidates.append((float(score), box))
            scores[max(0, y - 2):y + 3, max(0, x - 2):x + 3] = -1
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: item[0], reverse=True)
    score, box = candidates[0]
    if any(other >= score - .035 and np.max(np.abs(edges - box)) > .09 for other, edges in candidates[1:]):
        return None, None
    x, y, right, bottom = np.rint(box * [w, h, w, h]).astype(int)
    return _resize(source[y:bottom, x:right], tw, th), box.tolist()


def ratio_crop(aspect, target):
    """Centered suggestion based only on an example's visible aspect ratio."""
    width, height = min(1., target / aspect), min(1., aspect / target)
    if min(width, height) >= .98:
        return None
    return [(1 - width) / 2, (1 - height) / 2, (1 + width) / 2, (1 + height) / 2]
