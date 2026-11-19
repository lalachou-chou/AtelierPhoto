"""Offline DINOv3 Small image embeddings, with a fixed 448 × 448 contract."""
import numpy as np
from PIL import Image

from .config import MODEL_DIMENSION, MODEL_FILE, MODEL_NAME, MODEL_SIZE
from .local_runtime import load_runtime
from .model_assets import MODEL_FILES, verify_model


class DinoEncoder:
    def __init__(self, path=MODEL_FILE, threads=2):
        manifest = verify_model(path)
        self.path = path
        self.threads = None
        self.set_threads(threads)
        # Both graph and external weights, resolution and preprocessing define
        # the embedding space used by references, feedback and trained profiles.
        hashes = "/".join(manifest["sha256"][name] for name in MODEL_FILES)
        self.version = f"{MODEL_NAME}/rgb-bilinear-imagenet-cls-l2-v1/{hashes}"

    def set_threads(self, threads):
        """Thread count only changes speed: the CPU graph and its outputs stay the same.

        Encodes already running keep the session they started with.
        """
        threads = max(1, int(threads))
        if threads == self.threads:
            return
        ort = load_runtime()
        options = ort.SessionOptions()
        options.enable_profiling = False
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(self.path), sess_options=options,
                                            providers=["CPUExecutionProvider"])
        self.threads = threads

    def encode(self, image):
        image = image.convert("RGB").resize((MODEL_SIZE, MODEL_SIZE), Image.Resampling.BILINEAR)
        x = np.asarray(image, dtype=np.float32) * np.float32(1. / 255)
        x = (x - np.array([.485, .456, .406], dtype=np.float32)) / np.array([.229, .224, .225], dtype=np.float32)
        output = self.session.run(["pooler_output"],
                                  {"pixel_values": np.ascontiguousarray(x.transpose(2, 0, 1)[None])})[0]
        if output.shape != (1, MODEL_DIMENSION) or not np.isfinite(output).all():
            raise RuntimeError("Sortie DINOv3 invalide : vecteur de 384 dimensions attendu.")
        vector = output[0]
        norm = float(np.linalg.norm(vector))
        if norm < 1e-12:
            raise RuntimeError("Sortie DINOv3 invalide : vecteur nul.")
        return (vector / norm).tolist()

