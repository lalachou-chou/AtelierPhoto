"""Load the pinned ONNX engine with telemetry suppressed before initialization."""
import os
import sys


def load_runtime():
    # 1.30.0 checks this before creating the non-Windows telemetry client.
    os.environ["ORT_DISABLE_TELEMETRY"] = "1"
    if sys.platform == "win32":
        # In the pinned Windows build this internal switch skips registering
        # Microsoft.ML.ONNXRuntime. The public API alone is called too late
        # to prevent registration. The packaged self-test checks the provider.
        os.environ["ORT_RUNNING_UNIT_TESTS"] = "1"
    import onnxruntime

    onnxruntime.disable_telemetry_events()
    return onnxruntime
