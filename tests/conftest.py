import numpy as np
import pytest
from PIL import Image

from atelier.store import Store


class TestEncoder:
    """Deterministic test double only; application always uses real DINOv3."""
    __test__ = False
    version = "test-encoder-v1"

    def encode(self, image):
        x = np.asarray(image.resize((8, 8)), dtype=np.float32).ravel() + 1
        return (x / np.linalg.norm(x)).tolist()


@pytest.fixture
def encoder():
    return TestEncoder


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path / "library")
    yield instance
    instance.close()


@pytest.fixture
def photos(tmp_path):
    result = []
    generator = np.random.default_rng(12)
    for i in range(5):
        pixels = generator.integers(30, 220, (96, 128, 3), dtype=np.uint8)
        path = tmp_path / f"photo_{i}.png"
        Image.fromarray(pixels).save(path)
        result.append(str(path))
    return result

