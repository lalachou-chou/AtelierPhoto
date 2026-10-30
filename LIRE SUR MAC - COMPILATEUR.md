# Dossier de compilation Atelier Photo sur macOS

Ce dossier est à remettre à un Mac de construction, pas au Mac final.
Il cible un Mac Apple Silicon (M1, M2, M3…) sous macOS 15 ou supérieur.

Le script détecte `python3` ou `python`, contrôle qu'il s'agit d'un Python arm64
en version 3.12, 3.13 ou 3.14, puis crée un environnement `.venv` propre dans
ce dossier. Il installe les roues natives, vérifie explicitement ONNX Runtime
avec `CPUExecutionProvider`, lance les tests, compile la `.app` et fabrique le DMG.
La roue macOS d'ONNX Runtime ne fournit pas toujours le lien ABI court attendu
par Nuitka ; le script le restaure temporairement dans le `.venv` de compilation
et le recrée aussi dans l'application finale. Cette correction est automatique.

## Préparation du Mac de construction

Le Mac de construction doit avoir Internet pendant la préparation, Python 3.12,
3.13 ou 3.14 arm64 et les outils Apple. Python peut venir de python.org ou
Homebrew. Si les outils Apple ne sont pas présents, ouvrez Terminal et lancez :

```sh
xcode-select --install
```

Terminez la fenêtre proposée. Cette étape ne sera pas nécessaire sur le Mac final.

## Compilation

Créez d'abord un dossier local **AtelierPhoto-Build** dans votre dossier utilisateur
(Finder → Aller → Départ). Décompressez l'archive dans ce dossier, par exemple
`~/AtelierPhoto-Build/AtelierPhoto-Mac-Builder`.

Ne compilez pas dans iCloud Drive, Dropbox, OneDrive ou un autre dossier
synchronisé. Bureau, Documents et même Téléchargements peuvent être synchronisés
sur votre Mac. Le script refuse les chemins connus sous `Library/Mobile Documents`
et `Library/CloudStorage` avant d'installer ou de compiler quoi que ce soit.

Décompressez ce dossier, gardez tous ses fichiers ensemble, puis double-cliquez
sur **Construire Atelier Photo (Mac).command**. Le script effectue automatiquement la
préparation, l'installation des roues, le test ONNX Runtime, les tests du projet,
la compilation et le contrôle de l'application.

À la fin, le résultat est dans `dist` :

```text
AtelierPhoto-0.4.0-macOS-arm64-test.dmg
```

Transférez uniquement ce DMG au Mac final. Le Mac final n'a besoin ni de Python,
ni de Homebrew, ni de Xcode, ni de Terminal.

Le DMG n'est ni signé avec un certificat Developer ID ni notarié. macOS peut donc
demander une première autorisation dans Réglages Système → Confidentialité et
sécurité → Ouvrir quand même. Une signature ad hoc locale est conservée, car elle
est nécessaire pour exécuter du code arm64 sur Apple Silicon.

## En cas d'échec

Si le message contient **resource fork, Finder information, or similar detritus
not allowed**, la signature refuse des métadonnées Finder dans le bundle.
La compilation sous iCloud peut réintroduire ces attributs malgré le nettoyage.
Repartez de cette archive dans le dossier local indiqué ci-dessus : ne déplacez
pas l'ancien dossier de travail avec son `.venv`, `deployment` ou `dist`.
N'ouvrez pas « Afficher le contenu du paquet » pendant la construction.
Le nettoyage des attributs du bundle avant signature reste automatique.

Ne réutilisez pas un `.venv` provenant de Windows ou d'une autre architecture.
Le dossier de compilation doit être neuf. Les rapports se trouvent dans
`test-output`, notamment le diagnostic ONNX Runtime et celui du bundle.
