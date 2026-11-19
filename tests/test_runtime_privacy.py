import os
import sys
from types import SimpleNamespace

import pytest

from atelier.local_runtime import load_runtime


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_privacy_is_configured_before_native_import(monkeypatch, platform):
    import builtins

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "0")
    monkeypatch.delenv("ORT_RUNNING_UNIT_TESTS", raising=False)
    calls = []
    runtime = SimpleNamespace(disable_telemetry_events=lambda: calls.append("disable"))
    original_import = builtins.__import__

    def observe(name, *args, **kwargs):
        if name == "onnxruntime":
            assert os.environ["ORT_DISABLE_TELEMETRY"] == "1"
            if platform == "win32":
                assert os.environ["ORT_RUNNING_UNIT_TESTS"] == "1"
            calls.append("import")
            return runtime
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", observe)
    assert load_runtime() is runtime
    assert calls == ["import", "disable"]
