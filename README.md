# Atelier Photo

Application de bureau en français pour Windows et Mac : tri d’un rush par scènes,
filtre appris sur vos propres retouches et export non destructif. Le profil apprend
à partir de reportages que vous avez déjà triés (rush complet + photos livrées).
Tout le traitement est local, y compris DINOv3 Small ViT-S/16 en 448 × 448. Aucun serveur, compte ou
appel réseau à l’exécution.

## Lancer sur cet ordinateur

**Mac de test :** utiliser le DMG autonome décrit dans [LIRE SUR MAC.md](LIRE%20SUR%20MAC.md).
Python, Homebrew, Xcode et Terminal ne sont pas nécessaires sur le Mac qui utilise
le programme. Sans autre Mac de construction, la compilation peut se faire dans
GitHub Actions depuis le navigateur : [guide Windows](docs/COMPILER_MAC_DEPUIS_WINDOWS.md).
Pour compiler directement sur un Mac de construction, utiliser
`dist/0.4.0/AtelierPhoto-0.4.0-Mac-builder.zip` et `LIRE SUR MAC - COMPILATEUR.md`.

**Windows :** double-cliquer sur **Construire Atelier Photo (Windows).cmd** produit
`dist/AtelierPhoto-0.4.0-Windows-x64-Setup.exe` (tests, compilation Nuitka,
installateur Inno Setup, diagnostic du binaire). Lancer ensuite l’installateur, puis
**Atelier Photo** dans le menu Démarrer. La version portable est
`dist/0.4.0/AtelierPhoto.dist/AtelierPhoto.exe` ; conserver tout le dossier `.dist`.
L’installateur de la version précédente reste dans `dist/archives/`.

Pour la version depuis les sources :

Double-cliquer sur **Lancer Atelier Photo.cmd**. L’environnement `.venv` et le
modèle sont préparés dans ce dossier. On peut aussi lancer :

```powershell
.\.venv\Scripts\python.exe main.py
```

## Installer depuis les sources

L'archive `dist/0.4.0/AtelierPhoto-0.4.0-Mac-sources.zip` est destinée à une machine de
construction. Pour GitHub Actions depuis Windows, utiliser l'archive légère
`dist/0.4.0/AtelierPhoto-0.4.0-GitHub-sources.zip`. Ces archives se régénèrent avec
`python scripts/make_mac_transfer.py` (`--builder`, `--github`). Le testeur reçoit seulement le DMG
compilé ; le guide **LIRE SUR MAC.md** ne lui demande aucune ligne de commande.

Python 3.12 recommandé. Windows 11 x64 ou macOS 15+ Apple Silicon ; 16 Go de RAM
recommandés. Créer un environnement virtuel puis installer les dépendances :

```sh
python -m venv .venv
# Windows : .venv\Scripts\activate
# macOS : source .venv/bin/activate
python -m pip install -r requirements-tested.txt
python -m pip install -e ".[dev]"
python scripts/download_model.py
python scripts/download_licenses.py
python main.py
```

La préparation nécessite Internet. Le téléchargement du modèle (environ 86 Mo) est
épinglé à une révision et vérifié par SHA-256 dans `atelier/assets/model.json`.
Le modèle est ensuite inclus dans la distribution. L’application ne télécharge
jamais silencieusement un modèle manquant ; elle indique comment le réinstaller.

## Utilisation

1. Créer un profil puis **Apprendre d’un reportage trié** : choisir le dossier du
   rush complet, puis celui des photos gardées et retouchées. Les photos livrées sont
   reliées à leur original par le nom de fichier (`DSC0123.jpg` ↔ `DSC0123.ARW`,
   `DSC0123N&B.jpg` compris) ou, à défaut, par ressemblance. Le profil apprend
   **quelles photos vous gardez** et **comment vous les retouchez**. Chaque reportage
   ajouté complète l’apprentissage (plusieurs reportages variés donnent de meilleurs
   résultats). Sans apprentissage, un profil par défaut est utilisé.
   L’apprentissage se fait depuis les reportages triés ; les anciennes références sont conservées pour la compatibilité.
2. Importer un lot de fichiers ou un dossier, ou les déposer dans la galerie.
   Régler la sélectivité avant l’import (50 % ≈ le taux de sélection appris, un
   peu plus large ; « Prudente » garde davantage). Un dossier inclut ses sous-dossiers ;
   les fichiers cachés `._*` créés par macOS sont ignorés.
3. Examiner **Retenues**, **À vérifier**, **Écartées** et **Erreurs de lecture**.
   Les photos sont regroupées par scène (rafale ou moment) ; **Voir les variantes**
   affiche toute la scène pour échanger la photo retenue en un clic. Un double-clic
   sur une photo ouvre aussi ses variantes. **Tout afficher** revient sur la photo
   d’origine, sélectionnée et visible dans la galerie. Les touches 1, 2 et 3
   changent la décision. Ctrl/Cmd + clic sélectionne plusieurs photos.
4. Comparer l’original et la retouche ; ajuster les curseurs. Ils modifient toutes
   les photos sélectionnées. **Rétablir** revient à la recette initiale du lot.
   Un double-clic sur un curseur (exposition, température, etc.) remet ce seul
   réglage à sa valeur initiale ; sur la sélectivité, il revient à 50 %.
   **Retirer le filtre sur tout le lot / Réappliquer le filtre sur tout le lot** coupe ou rétablit le filtre appliqué sur toutes
   les photos du lot ; ce choix est mémorisé et respecté à l’export.
5. **Valider le lot**, puis **Exporter** les retenues en JPEG qualité 95, PNG ou
   **RAW + XMP** : les RAW sont copiés à l’identique (vérifiés par SHA-256) avec un
   fichier `.xmp` de même nom contenant la retouche (exposition, contraste,
   saturation lus par Lightroom / Camera Raw et darktable). Dans ce mode, les
   JPEG/PNG du lot sont exportés en JPEG retouché.
   Les photos encore à vérifier ne sont pas exportées. Les noms sont réservés
   exclusivement : aucun fichier existant n’est écrasé.
   **Mettre l’export en pause** termine la photo en cours puis mémorise la progression.
   **Reprendre l’export** continue au fichier suivant, avec le même format et le même
   dossier, sans réexporter les photos déjà terminées. La reprise reste disponible
   en sélectionnant le lot après avoir fermé puis rouvert l’application.
6. Sélectionner un lot dans la colonne de gauche, puis **Supprimer le lot
   sélectionné** pour le retirer après confirmation. Ses aperçus et tâches sont
   supprimés ; les originaux, exports et corrections déjà mémorisées restent intacts.

Les lots sont persistés après chaque fichier. **Suspendre** attend la fin de la
photo courante ; **Reprendre une tâche** reprend le travail. Un lot inachevé doit
être terminé avant validation. Après fermeture forcée, la reprise reste possible.
En cas de coupure exactement pendant la publication d’un export, une nouvelle
copie peut être produite à la reprise ; aucun export précédent n’est écrasé.

## Mémoire et apprentissage

Le moteur utilise DINOv3 Small ViT-S/16 en ONNX float32 sur CPU : image entière
redimensionnée en 448 × 448 (bilinéaire), normalisation ImageNet, vecteur CLS de
384 dimensions normalisé L2. Aucun téléchargement n’a lieu pendant l’utilisation.
Le graphe `model.onnx` et ses poids `model.onnx_data` sont vérifiés par SHA-256.

Après la migration depuis CLIP, réimportez vos références et réapprenez vos
reportages dans un nouveau profil. Les corrections CLIP et les anciens modèles de
sélection sont conservés mais ne sont pas appliqués aux nouveaux vecteurs DINOv3.
Les lots terminés restent consultables et exportables ; un lot CLIP interrompu
doit être relancé comme nouveau lot. Le filtre de couleur appris reste utilisable.
Le modèle de sélection par défaut a été réentraîné avec le nouveau moteur.

**Apprentissage d’un reportage trié.** Les photos sont classées par heure de prise
de vue (EXIF) et découpées en scènes (moins de 20 s d’écart et contenu proche).
Un modèle de sélection (régression logistique sur la netteté, l’exposition, la
place de la photo dans sa scène et le contenu DINOv3) apprend vos choix ; un filtre
(table couleur 3D + courbe de tonalité adaptée à chaque photo) apprend vos retouches
à partir des paires original / retouche de même cadrage. Les photos recadrées ne
servent qu’à la sélection ; les versions noir et blanc sont ignorées pour le filtre.
Détails, méthode et mesures : `docs/SELECTION.md`. Pour mesurer la fidélité sur un
reportage déjà trié : `python scripts/evaluate_profile.py RUSH RETENUES`.

Les profils possèdent des copies normalisées des références, des caractéristiques
DINOv3, des statistiques de couleur et les corrections validées. Les originaux
peuvent être déplacés après ajout des références. Pour les nouveaux lots, les
originaux doivent rester disponibles jusqu’à l’export.

Seules les modifications explicites de sélection ou de curseur alimentent
l’apprentissage. Une simple acceptation ne devient pas une nouvelle référence.
Valider plusieurs fois est idempotent. L’apprentissage concerne les lots suivants,
jamais les décisions et recettes des lots précédents, qui gardent un instantané
du profil et la version exacte du modèle. Les préférences sont utilisées sur des
images suffisamment proches ; elles ne sont pas un entraînement profond.
Le compteur du profil indique les corrections mémorisées. La validation précise
le profil concerné et les nouvelles corrections. Les anciens profils et lots sont
migrés automatiquement à la première ouverture de la version 0.3.

La réinitialisation efface les références internes, apprentissages, lots et caches
du profil après confirmation. Elle conserve son nom, les originaux et les exports.
Ce n’est pas une garantie d’effacement forensique des sauvegardes ou d’un SSD.

Données : `%LOCALAPPDATA%\AtelierPhoto` sur Windows et
`~/Library/Application Support/AtelierPhoto` sur Mac. `ATELIER_DATA_DIR` permet
d’utiliser un autre dossier. Aucune télémétrie n’est intégrée.

## Traitement et limites de la version 0.3

- Sélection par scène : la meilleure image des meilleurs moments est retenue, une
  seconde image n’est ajoutée que si elle est réellement différente. Les autres
  images d’une scène retenue sont écartées ; les moments sans photo retenue et les
  variantes proches passent « à vérifier ». Le choix de l’image exacte dans une
  rafale (regard, sourire, yeux fermés) reste la partie la plus difficile : aucun
  détecteur de visage n’est intégré dans cette version.
- Filtre appris : l’intensité 1 reproduit vos retouches ; les curseurs s’ajoutent
  ensuite. En export RAW + XMP, seuls les réglages globaux sont écrits dans le XMP
  (la table couleur apprise n’a pas d’équivalent Lightroom).
- Netteté par régions, clipping d’exposition et estimation du bruit ; classification
  conservatrice avec motifs. Une photo floue sur toute l’image (aucune région
  nette) est écartée ; si vous avez déjà retenu une photo proche, elle passe
  seulement « à vérifier ». Un flou partiel (profondeur de champ) est « à vérifier ».
  Cette séparation reste une heuristique, pas une segmentation du sujet.
- DINOv3 Small float32 en 448 × 448 pour le contenu des photos et le découpage en scènes ; SHA-256 pour
  les doublons exacts. L’heure EXIF ordonne les photos (à défaut, la date du fichier).
- Retouches globales et ponctuelles (pas de masque) : pas de génération, recadrage,
  suppression d’objet ou récupération de détail inventé. Sans filtre appris, les
  références proches fournissent des statistiques de style (ancien comportement).
- RAW via la version embarquée de LibRaw : les boîtiers inconnus sont signalés.
  Développement en 16 bits vers des pixels flottants ; export JPEG/PNG en 8 bits
  sRGB. Les aperçus RAW utilisent un développement réduit, qui peut légèrement
  différer du dématriçage pleine résolution.
- En export RAW + XMP, la température n’est pas traduite en Kelvin pour les RAW
  (balance « telle que prise ») ; la valeur Atelier est gardée dans le XMP.
- EXIF compatibles conservés pour JPEG/PNG après correction d’orientation ; les
  métadonnées propriétaires RAW ne sont pas recopiées dans cette version.
  Une image PNG transparente est composée sur fond blanc pour le traitement photo.
- L’import et l’apprentissage préparent deux photos en parallèle, avec sauvegarde dans l’ordre et reprise possible. La retouche travaille par bandes ; une
  image pleine résolution doit néanmoins tenir en mémoire à l’export.
- Les références finales permettent une interprétation de style, pas la
  reconstitution des paramètres originaux. Les valeurs de qualité ne constituent
  pas un jugement esthétique fiable sans validation humaine.

## Vérifier et distribuer

```sh
python -m pytest -q
python scripts/build_release.py --dry-run
python scripts/build_release.py
```

Le diagnostic `--self-test chemin/rapport.json` vérifie DINOv3, les processus de
traitement, l’export et l’aperçu Qt dans une bibliothèque temporaire indépendante.
Il fonctionne aussi sur l’exécutable compilé. Les workflows de test et de build
Windows/macOS sont fournis ; le workflow de build se lance manuellement.

`pyside6-deploy` / Nuitka construit sur l’OS cible un répertoire autonome avec Qt,
LibRaw, ONNX Runtime et les poids DINOv3. Un compilateur C et des téléchargements de
build peuvent être nécessaires. `--keep-deployment-files` conserve le bundle dans
`deployment/` et copie le résultat dans `dist/` ; distribuer le répertoire `.dist`
complet, pas l’exécutable isolé.

Windows : compiler `packaging/windows.iss` avec Inno Setup 6 et passer
`/DBundleDir="chemin absolu du répertoire .dist"` pour obtenir l’installateur.
La signature Authenticode nécessite votre certificat de distribution.
`scripts/prepare_inno.ps1` prépare si besoin le compilateur Inno Setup portable
dans `.build-tools`, après vérification de sa signature officielle.

Mac : le workflow **Construire le DMG Mac de test** compile sur macOS 15 arm64,
teste le binaire et fournit un DMG contenant l'application autonome et le guide.
Aucun certificat Developer ID, secret Apple ou appel de notarisation n'est utilisé.
L'empreinte ad hoc locale exigée par Apple Silicon est créée automatiquement.
Le contrôle préalable vérifie les architectures et les versions minimales des
binaires. La copie préserve les liens des frameworks Qt ; les ressources et notices
sont placées dans `Contents/Resources`. Pour le protocole Mac et les résultats
effectivement obtenus, voir `docs/MACOS.md`. Le guide de compilation depuis le
navigateur Windows se trouve dans `docs/COMPILER_MAC_DEPUIS_WINDOWS.md`.

La CI proposée teste Windows, macOS 15 et macOS 26 ; le bundle Mac est construit sur
macOS 15 arm64 et testé avant archivage. Elle n’a pas été exécutée tant que ce dossier
n’est pas poussé sur GitHub. Les essais locaux ne remplacent pas la validation
sur un Mac réel et sur des RAW de vos boîtiers.

Voir `docs/SELECTION.md` pour la méthode et les mesures de la version 0.3,
`docs/AUDIT.md` pour les vérifications de la version 0.2,
`docs/VALIDATION.md` pour le protocole de qualification photographique et
`THIRD_PARTY_NOTICES.md` pour les composants tiers.
