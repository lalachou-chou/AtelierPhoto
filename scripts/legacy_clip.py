"""Historical CLIP baseline for comparison scripts only."""
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

MODEL_FILE = Path(__file__).resolve().parents[1] / "test-output/selection-models/clip/vision_model_quantized.onnx"
MODEL_NAME = "CLIP ViT-B/32 · ONNX int8"
from atelier.imaging import digest


class ClipEncoder:
    def __init__(self, path=MODEL_FILE):
        path = Path(path)
        if not path.exists():
            raise RuntimeError("Modèle CLIP absent. Restaurez les poids historiques dans test-output/selection-models/clip pour ce benchmark.")
        checksum = digest(path)
        manifest_path = path.with_name("model.json")
        if not manifest_path.exists():
            raise RuntimeError("Manifeste du modèle absent. Réinstallez le modèle.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if checksum != manifest["sha256"]:
            raise RuntimeError("Le modèle CLIP est endommagé. Réinstallez-le.")
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
        self.version = f"{MODEL_NAME}/{checksum}"

    def encode(self, image):
        width, height = image.size
        ratio = 224 / min(width, height)
        image = image.resize((int(width * ratio), int(height * ratio)), Image.Resampling.BICUBIC)
        image = ImageOps.fit(image, (224, 224), method=Image.Resampling.BICUBIC)
        x = np.asarray(image.convert("RGB"), dtype=np.float32) / 255
        x = (x - np.array([.48145466, .4578275, .40821073], dtype=np.float32)) / np.array([.26862954, .26130258, .27577711], dtype=np.float32)
        output = self.session.run(["image_embeds"], {"pixel_values": x.transpose(2, 0, 1)[None]})[0][0]
        return (output / max(float(np.linalg.norm(output)), 1e-12)).tolist()

