"""Download public model assets only; never uploads or opens photographs."""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1] / 'test-output' / 'selection-models'
REPOS = {
    'siglip2': ('onnx-community/siglip2-base-patch16-224-ONNX', ['onnx/vision_model_quantized.onnx']),
    'dinov3': ('onnx-community/dinov3-vits16-pretrain-lvd1689m-ONNX', ['onnx/model.onnx', 'onnx/model.onnx_data']),
    'dinov3_base': ('onnx-community/dinov3-vitb16-pretrain-lvd1689m-ONNX', ['onnx/model.onnx', 'onnx/model.onnx_data']),
}


def download(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_suffix(target.suffix + '.part')
        with urllib.request.urlopen(url, timeout=120) as src, temporary.open('wb') as dst:
            while block := src.read(1024 * 1024):
                dst.write(block)
        temporary.replace(target)
    print(target.name, target.stat().st_size, flush=True)


def main():
    for name, (repo, files) in REPOS.items():
        directory = ROOT / name
        directory.mkdir(parents=True, exist_ok=True)
        manifest = directory / 'manifest.json'
        if manifest.exists():
            revision = json.loads(manifest.read_text())['revision']
        else:
            with urllib.request.urlopen('https://huggingface.co/api/models/' + repo, timeout=30) as stream:
                revision = json.load(stream)['sha']
        for file in ['config.json', 'preprocessor_config.json', 'README.md'] + files:
            download(f'https://huggingface.co/{repo}/resolve/{revision}/{file}', directory / file)
        hashes = {file: hashlib.file_digest((directory / file).open('rb'), 'sha256').hexdigest() for file in files}
        manifest.write_text(json.dumps({'repo': repo, 'revision': revision, 'sha256': hashes}, indent=2))
    download('https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task', ROOT / 'face_landmarker.task')
    download('https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/int8/1/efficientdet_lite0.tflite', ROOT / 'efficientdet_lite0.tflite')


if __name__ == '__main__':
    main()
