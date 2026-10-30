"""Build-time download of complete distribution license texts."""
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "atelier" / "assets"


def main():
    manifest = {}
    for name, url in {
        "LGPL-3.0.txt": "https://www.gnu.org/licenses/lgpl-3.0.txt",
        "GPL-3.0.txt": "https://raw.githubusercontent.com/qt/qtbase/dev/LICENSES/GPL-3.0-only.txt",
        "OpenSSL-LICENSE.txt": "https://raw.githubusercontent.com/openssl/openssl/openssl-3.5.8/LICENSE.txt",
    }.items():
        path = ROOT / name
        if not path.exists():
            with urllib.request.urlopen(url, timeout=60) as response:
                content = response.read()
            if not any(tag in content for tag in (b"GENERAL PUBLIC LICENSE", b"Apache License")) or b"<html" in content.lower():
                raise ValueError("Texte de licence invalide")
            path.write_bytes(content)
        manifest[name] = {"source": url, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (ROOT / "gnu-licenses.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
