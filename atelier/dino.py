"""Offline DINOv3 Small image embeddings, with a fixed 448 × 448 contract."""
import numpy as np
from PIL import Image

from .config import MODEL_DIMENSION, MODEL_FILE, MODEL_NAME, MODEL_SIZE
from .model_assets import MODEL_FILES, verify_model


class DinoEncoder:
    def __init__(self, path=MODEL_FILE):
        manifest = verify_model(path)
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), sess_options=options,
                                            providers=["CPUExecutionProvider"])
        # Both graph and external weights, resolution and preprocessing define
        # the embedding space used by references, feedback and trained profiles.
        hashes = "/".join(manifest["sha256"][name] for name in MODEL_FILES)
        self.version = f"{MODEL_NAME}/rgb-bilinear-imagenet-cls-l2-v1/{hashes}"

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

