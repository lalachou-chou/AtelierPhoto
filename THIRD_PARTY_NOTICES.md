# Composants tiers

Cette application embarque ou utilise les composants suivants. Conserver leurs
licences avec toute distribution binaire ; les fichiers de licence fournis dans
les paquets doivent être inclus dans le bundle de distribution.

- PySide6 / Qt — LGPLv3, GPLv3 ou licence commerciale selon composants.
  https://doc.qt.io/qtforpython-6/licenses.html
- NumPy — BSD-3-Clause. https://numpy.org/doc/stable/license.html
- Pillow 12.3 — MIT-CMU. https://github.com/python-pillow/Pillow/blob/main/LICENSE
- rawpy — MIT ; LibRaw et dépendances selon leurs licences embarquées.
  https://github.com/letmaik/rawpy
- ONNX Runtime — MIT. https://github.com/microsoft/onnxruntime/blob/main/LICENSE
- Python — PSF et licences des composants inclus, texte dans `third-party-licenses`.
  https://www.python.org/downloads/source/
- Protobuf — BSD-3-Clause ; FlatBuffers — Apache-2.0 ; textes fournis avec les paquets.
- OpenSSL 3.x (runtime Windows vérifié : 3.5.8) — Apache-2.0,
  texte inclus dans `atelier/assets/OpenSSL-LICENSE.txt`.
  https://github.com/openssl/openssl/tree/openssl-3.5.8
- DINOv3 Small ViT-S/16 — Meta, DINOv3 License ; conversion ONNX float32
  par ONNX Community. Licence incluse dans `atelier/assets/DINOv3-LICENSE.txt`.
  https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md
  https://huggingface.co/onnx-community/dinov3-vits16-pretrain-lvd1689m-ONNX

La révision et l’empreinte des poids distribués figurent dans
`atelier/assets/model.json`. L’application ne remplace pas DINOv3 par un encodeur
factice lorsque les poids sont absents ; les doubles utilisés dans les tests
ne font pas partie du parcours utilisateur.

Distribution Qt : bibliothèques partagées non modifiées de PySide6/Qt 6.11.2.
Les textes LGPLv3 et GPLv3 sont inclus dans `atelier/assets` ; les notices des
paquets figurent dans `third-party-licenses`. L’utilisateur est autorisé à
remplacer les bibliothèques Qt par une version compatible et à effectuer les
opérations d’ingénierie inverse nécessaires au débogage de telles modifications.
Sources correspondant à cette version :
https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.2-src/
https://download.qt.io/archive/qt/6.11/6.11.2/submodules/
Les obligations applicables lors d’une redistribution sont décrites par Qt :
https://www.qt.io/development/open-source-lgpl-obligations
Le clavier virtuel Qt et les plugins TLS inutilisés ne sont pas distribués.

Construction de l’installateur : Inno Setup 6.7.3. Le compilateur préparé par le
script utilise son régime non commercial ; une utilisation commerciale de cet
outil de build nécessite la licence correspondante de son éditeur.
https://jrsoftware.org/isorder.php
