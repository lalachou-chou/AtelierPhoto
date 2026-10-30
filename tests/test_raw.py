import sys
from types import SimpleNamespace

import numpy as np
import pytest

from atelier.imaging import decode


def test_real_libraw_rejects_corrupt_file(tmp_path):
    path = tmp_path / "corrupt.cr3"
    path.write_bytes(b"Not a camera file")
    with pytest.raises(ValueError, match="RAW illisible"):
        decode(path)


def test_raw_pipeline_preserves_16_bit_values(tmp_path, monkeypatch):
    calls = []
    pixels = np.array([[[10001, 20002, 30003], [40004, 50005, 60006]]], dtype=np.uint16)
    class Raw:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def postprocess(self, **kwargs):
            calls.append(kwargs)
            return pixels
    monkeypatch.setitem(sys.modules, "rawpy", SimpleNamespace(imread=lambda path: Raw(), ColorSpace=SimpleNamespace(sRGB=1), LibRawError=RuntimeError))
    output, _ = decode(tmp_path / "sample.nef")
    np.testing.assert_allclose(output, pixels.astype(np.float32) / 65535)
    assert calls[0]["output_bps"] == 16
    assert calls[0]["use_camera_wb"] is True
    assert calls[0]["half_size"] is False
