# Vérification macOS — 5 octobre 2026

La cible retenue après clarification avec l’utilisateur est **macOS 15 ou supérieur
sur Apple Silicon**, avec Python 3.12 arm64 natif pour la construction.
Les Mac Intel ne font pas partie du périmètre. La compatibilité des dépendances
et la préparation de la distribution ont été vérifiées depuis Windows ; aucun
lancement sur un Mac réel n’a encore été effectué.

## Résultats vérifiés

Les 11 dépendances et sous-dépendances de `requirements-tested.txt` ont été
résolues et téléchargées pour macOS arm64 / CPython 3.12, sans les installer sur
Windows. Les en-têtes de 445 binaires natifs présents dans ces paquets ont été
inspectés : tous possèdent une tranche arm64 pour macOS avec un minimum ≤ 15.0.
L’audit comprend également des composants Qt non utilisés par l’application ;
ces composants ne seront pas tous embarqués dans le bundle.

| Composant | Version | Minimum natif le plus élevé constaté |
| --- | --- | --- |
| PySide6 Essentials / Addons / shiboken6 | 6.11.2 | 15.0 |
| NumPy | 2.5.3 | 14.0 |
| ONNX Runtime | 1.30.0 | 14.0 |
| Pillow | 12.3.0 | 11.0 |
| rawpy / LibRaw | 0.27.1 | 11.0 |
| Protobuf | 7.36.2 | 12.0 |
| FlatBuffers / packaging | 25.12.19 / 26.3 | Python pur |

Les noms des wheels Qt annoncent macOS 13, mais les en-têtes Mach-O de leurs
modules, notamment QtCore, QtGui et QtWidgets, déclarent un minimum 15.0.
La précédente annonce « macOS 14+ » a donc été corrigée. Modifier uniquement
`Info.plist` ou une variable de compilation ne rendrait pas ces binaires compatibles
avec macOS 14. Une comparaison supplémentaire avec PySide6 6.10.2 a retrouvé
le même minimum dans les modules inspectés ; aucune rétrogradation n’a été appliquée.

La roue macOS arm64 d’ONNX Runtime 1.30.0 contient la bibliothèque versionnée
`libonnxruntime.1.30.0.dylib`, tandis que son module natif demande aussi le nom ABI
`libonnxruntime.1.dylib` via `@rpath`. Le script de construction crée ce lien dans
l’environnement temporaire avant Nuitka et le préserve dans le bundle final ; cela
évite l’erreur Nuitka « failed to find path @rpath/libonnxruntime.1.dylib ».

Le champ `minos` et le format des architectures ont été contrôlés à partir des
définitions Apple : [loader.h](https://github.com/apple-oss-distributions/xnu/blob/main/EXTERNAL_HEADERS/mach-o/loader.h)
et [fat.h](https://github.com/apple-oss-distributions/xnu/blob/main/EXTERNAL_HEADERS/mach-o/fat.h).
L’inventaire avec empreintes SHA-256 se trouve dans
`test-output/macos-dependencies.json`. Les versions des paquets sont consultables
sur leurs pages officielles [PySide6 Essentials](https://pypi.org/project/PySide6-Essentials/6.11.2/),
[ONNX Runtime](https://pypi.org/project/onnxruntime/1.30.0/) et [rawpy](https://pypi.org/project/rawpy/0.27.1/).

Les chemins de données, l’import et l’export utilisent des API Python portables.
La mémoire Mac réside dans `~/Library/Application Support/AtelierPhoto`.
Le traitement utilise `spawn` et `freeze_support`, avec les tests de processus
et le vrai modèle DINOv3 inclus dans le diagnostic du binaire.

## Corrections de distribution

- Construction limitée à Python arm64 natif sur macOS 15+, sans Rosetta.
- Cible de compilation et version minimale du bundle fixées à 15.0 ; identifiant
  stable `org.atelierphoto.AtelierPhoto` est ajouté au plist.
- Copie du bundle Nuitka avec préservation des liens symboliques. Le code de
  copie de `pyside6-deploy` 6.11.2 utilise `shutil.copytree` sans `symlinks=True`,
  ce qui déréférence les liens des frameworks ; la copie finale est reconstruite
  depuis le bundle original. Une copie interrompue restaure le résultat précédent.
- Notices et licences dans `Contents/Resources`, sans fichiers supplémentaires
  à la racine de `.app`. Explications d’accès aux dossiers ajoutées à `Info.plist`.
- Renouvellement de l'empreinte ad hoc obligatoire pour Apple Silicon après préparation,
  sans certificat ni identité. Les fichiers Mach-O et frameworks sont traités de
  l'intérieur vers l'extérieur. L'option
  `--deep` sert à la vérification. Cette approche suit les
  [recommandations Apple](https://developer.apple.com/library/archive/technotes/tn2206/_index.html).
- Diagnostic du bundle compilé avant création du DMG. Signature Developer ID,
  notarisation et scripts associés supprimés à la demande de l'utilisateur.
  Le testeur installe par glisser-déposer, sans outils de développement ni Terminal.
- ZIP créé avec `ditto` pour préserver liens et permissions pendant le transfert.
  CI préparée pour macOS 15 et 26 arm64 ; labels confirmés dans la
  [liste officielle des runners GitHub](https://github.com/actions/runner-images).

Tests locaux : **40 réussis, 1 ignoré**. Les nouveaux tests couvrent Mach-O fin et
universel, minimum natif distinct du SDK, architecture incorrecte, plateforme
incorrecte, minimum trop récent, placement des ressources, restauration d’une
copie interrompue et ordre de signature. Le test de préservation effective des
liens est ignoré sur cet hôte Windows faute de permission de création ; il doit
être exécuté sur Mac. L’analyse Ruff réussit.

## Validation native à terminer

Pour le testeur, voir **LIRE SUR MAC.md** : uniquement ouvrir le DMG, copier
l'application puis éventuellement autoriser son ouverture dans les réglages.
Pour compiler depuis Windows, voir **COMPILER_MAC_DEPUIS_WINDOWS.md** ; la CI
installe les outils sur son serveur macOS, pas sur le Mac de test.
Sur un Mac de construction, `Construire Atelier Photo (Mac).command` prépare l'environnement, compile, vérifie le
binaire et crée un DMG local avec raccourci Applications. La création du DMG
conserve les liens et signatures via `ditto`, vérifie la copie et l'image avant
remplacement d'un éventuel installateur précédent. La version locale n'est pas
notarisée. Le script `create_macos_dmg.py` inclut un guide HTML et un raccourci
Applications. Le DMG final s'appelle `AtelierPhoto-0.4.0-macOS-arm64-test.dmg`.

Sur un Mac Apple Silicon sous macOS 15+, après préparation des sources :

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-tested.txt
python -m pip install -e ".[dev]" Nuitka==4.1.1
python scripts/download_model.py
python scripts/download_licenses.py
python -m pytest -q
python scripts/build_release.py
python scripts/macos_bundle.py dist/0.4.0/AtelierPhoto.app \
  --self-test test-output/packaged-macos.json --report test-output/macos-bundle.json
python scripts/create_macos_dmg.py dist/0.4.0/AtelierPhoto.app
```

La construction nécessite les outils de ligne de commande Xcode. Ensuite, lancer
l’application dans Finder et vérifier les dialogues natifs, glisser-déposer,
accès aux dossiers et disques externes, import RAW, aperçus, annulation/reprise,
validation/apprentissage, suppression des lots et export. Refaire le parcours
avec le réseau désactivé ; comparer orientation et couleurs sur un écran géré.

Le workflow `.github/workflows/macos-test.yml` est déclenchable manuellement depuis
le navigateur GitHub, sans secrets de signature. Le paquet pour le testeur contient
uniquement le DMG ; les rapports sont proposés dans un artifact séparé.
Tester l'installation sur un Mac sans Python, Homebrew ni Xcode, avec Gatekeeper
actif et un DMG transféré depuis Internet. Vérifier le parcours « Ouvrir quand même »
si nécessaire, puis le lancement par double-clic et le fonctionnement hors ligne.

La CI n’a pas été déclenchée : le dossier courant n’est pas un dépôt Git connecté.
Les étapes de compilation native, création du DMG et essai Finder restent
donc **non exécutées**, et aucun fichier `.app` ou DMG Mac n’est livré à ce stade.
# Compilation locale et iCloud

Décompressez les sources dans `~/AtelierPhoto-Build`, hors dossier synchronisé.
Les chemins sous `Library/Mobile Documents` (iCloud) et `Library/CloudStorage`
sont refusés avant compilation : la synchronisation peut ajouter des métadonnées
Finder incompatibles avec `codesign`, même après le nettoyage des attributs.
Après un tel échec, repartez d'une archive neuve ; ne transportez pas le `.venv`
ou les bundles de la tentative précédente. Le contrôle ne détecte pas tous les
emplacements personnalisés des logiciels de synchronisation.

Voir [l'explication Apple QA1940](https://developer.apple.com/library/archive/qa/qa1940/_index.html).

