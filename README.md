# Atelier Photo

Application de bureau pour Windows et Mac : **tri automatique des rushs photo et
de leurs variantes**. À l’import, Atelier regroupe chaque scène avec ses variantes,
retient la meilleure image et propose le reste à vérifier ou à écarter. Vos
reportages déjà triés et vos photos de référence orientent ce tri.
Atelier ne retouche, ne recadre et ne modifie aucune photo.
Le traitement est entièrement local, sans compte ni connexion pendant l’utilisation.

## Installer l’application

Windows 11 x64 ou macOS 15+ Apple Silicon ; 16 Go de RAM recommandés.

Ouvrir la page [Releases](https://github.com/lalachou-chou/AtelierPhoto/releases)
et choisir le fichier correspondant à son système :

- **Windows** : télécharger l’installateur `.exe` dont le nom se termine par
  `Windows-x64-Setup.exe`, lancer
  l’installateur, puis ouvrir **Atelier Photo** depuis le menu Démarrer.
- **Mac** : télécharger le fichier `.dmg`, l’ouvrir et glisser **AtelierPhoto.app**
  dans **Applications**. Le [guide Mac](LIRE%20SUR%20MAC.md) détaille l’installation
  et l’autorisation du premier lancement.

Les installateurs embarquent Python, les bibliothèques et le modèle d’analyse.
Il n’est pas nécessaire d’installer des outils de développement pour utiliser
l’application.

**Code → Download ZIP** et les archives `sources` ou `builder` contiennent du
code à exécuter ou à compiler ; ce ne sont pas les installateurs de l’application.

## Apprendre avec ses reportages et ses références

Au premier lancement, un guide en cinq étapes présente le parcours :
**Profil → Reportages et références → Importer → Vérifier le tri → Exporter**.
On peut revenir à une étape ou le rouvrir depuis **Aide**.

Le **profil actif** reste visible dans la colonne **Profil et lots**, avec son bilan
d’apprentissage et un accès direct à **Reportages et références…**.
**Gérer les profils…** permet de créer, choisir et personnaliser ses profils.
Le dernier profil actif est retrouvé au prochain lancement.
**Importer…** ouvre la préparation du lot : vérifiez le profil et la sélectivité,
puis choisissez les fichiers ou le dossier. Sans profil existant, **Mon premier profil**
est créé au premier import confirmé, avec le modèle de tri fourni.

### Reportages déjà triés

Cliquer sur **Reportages et références…**, puis sur **Ajouter un reportage…**.
Choisir le dossier du rush complet, puis le dossier des photos retenues, retouchées
ou non. Les sous-dossiers sont inclus dans les deux cas. Répéter pour ajouter
autant de reportages que souhaité. Atelier apprend quelles photos vous gardez et
lesquelles vous écartez.

Cocher les reportages à utiliser ; les décocher permet de les garder pour plus tard.
**Retirer les éléments sélectionnés** les retire du profil. **Appliquer et relancer
l’apprentissage** recalcule le modèle de tri sur les seuls reportages cochés, sans
relire les photos déjà analysées. Sans reportage coché, le modèle de tri fourni est
utilisé, complété par les groupes de références cochés. **Annuler** abandonne les changements.

Les retenues sont associées aux originaux par leur chemin, leur nom
(`DSC0123.jpg` ↔ `DSC0123.ARW`, suffixes de retouche compris), puis par ressemblance.
Les reportages restent séparés, même si leurs noms de fichiers se répètent.
Les correspondances ambiguës sont signalées et ignorées. Si le dossier des retenues
est à l’intérieur du rush, il est exclu du rush.
Il faut au moins 6 originaux, dont 2 retenus et un écarté au total ; plusieurs
reportages complets donnent un tri bien plus fidèle.

### Références sans rush

Une **référence est une photo que vous aimez, sans son rush associé** : RAW, JPEG ou PNG.
Ouvrir **Reportages et références…**, puis **Ajouter des références**. Chaque ajout
apparaît comme un groupe cochable dans la liste.

Les références aident le tri de deux façons :

- **Classement et variantes** : la ressemblance aux références s’ajoute au score de
  chaque photo. Entre deux variantes d’une même scène, la plus proche de vos
  références est favorisée. Une photo retenue qui leur ressemble l’indique
  (« Proche de vos références »).
- **Prudence sans modèle appris** : sans reportage appris, une photo éloignée de
  toutes les références passe « à vérifier » au lieu d’être retenue d’office.

Les contrôles techniques (flou, image noire ou blanche, doublons) restent prioritaires.
Pour les références, la variété compte plus que le nombre. Une photo présente dans
plusieurs groupes ne compte qu’une fois. Les groupes restent mémorisés après fermeture ;
recocher un groupe déjà analysé réutilise les données enregistrées, même si ses
photos ont été déplacées.

Attendre le bilan de l’apprentissage avant d’importer un nouveau lot. Les lots déjà
importés gardent leurs propositions. **Suspendre**, puis **Gérer les tâches → Reprendre**
permettent de continuer sans doublonner les exemples. Si un fichier est illisible,
le profil précédent est conservé : corriger le fichier puis relancer, ou retirer
le reportage ou le groupe concerné.

**Effacer les corrections apprises** oublie uniquement les décisions mémorisées par
**Valider le lot**. Les reportages, les références et les lots sont conservés.

Le menu **Charge** en bas de la fenêtre règle la part de l’ordinateur utilisée
par les importations et apprentissages : **Rapide**, **Équilibrée** ou **Discrète**.
Le choix est mémorisé et peut être changé pendant un traitement ; il ne modifie
jamais les résultats.

## Trier et exporter

1. Ouvrir **Importer** ou déposer les fichiers dans la galerie. La préparation
   du nouveau lot permet de choisir son profil et sa sélectivité ; les sous-dossiers
   sont inclus. À la fin de l’analyse, **la sélection est faite automatiquement** :
   les photos sont rangées par heure de prise de vue, regroupées en scènes
   (variantes d’un même moment), et la meilleure image de chaque scène est retenue.
   Une seconde image n’est retenue que si elle est vraiment différente.
   La sélectivité garde davantage de photos à gauche, moins à droite. Avec le profil
   fourni, le centre vise **environ 16 % de retenues**, avec **jusqu’à 35 % de photos
   à vérifier**. Les profils appris conservent leur propre taux. **Options du lot**
   permet de recalculer le tri d’un lot déjà importé à partir des données analysées ;
   les choix manuels sont conservés.
   Après une interruption, les photos dont le tri n’a pas été calculé apparaissent
   **en attente de tri** ; reprendre l’import via **Gérer les tâches**.
2. Examiner **Retenues**, **À vérifier**, **Écartées** et **Erreurs de lecture**.
   **Groupes de variantes** ouvre une scène du lot ; **Isoler ses variantes** ouvre
   celle de la photo affichée. **Garder uniquement celle-ci** retient cette photo et
   écarte les autres du groupe. **Revenir au lot** affiche toutes les photos.
   Cliquer sur l’aperçu ou double-cliquer sur une vignette ouvre la photo en grand.
   Les touches 1, 2 et 3 retiennent, mettent à vérifier ou écartent, aussi dans la vue
   agrandie, qui passe alors à la photo suivante. Ctrl/Cmd + clic sélectionne plusieurs
   photos pour leur donner la même décision.
3. **Exporter** valide le lot et **copie les retenues à l’identique** dans le dossier
   choisi, avec leurs XMP voisins (`photo.xmp` ou `photo.nef.xmp`), sous leur nom
   d’origine. Si le nom est pris, « (2) », « (3) »… est ajouté : aucun fichier n’est
   écrasé. Chaque copie est vérifiée par empreinte ; si l’original a changé depuis
   l’import, l’export est refusé. Les photos à vérifier ne sont pas copiées.
4. **Mettre l’export en pause** termine la photo en cours. **Reprendre l’export**
   continue dans le même dossier, y compris après fermeture.
5. Dans **Options du lot**, **Supprimer ce lot…** retire le lot sélectionné et ses aperçus après
   confirmation. Les photos d’origine, les exports et les corrections déjà apprises sont conservés.

Seules les décisions changées à la main alimentent la mémoire du profil, à la
validation ; une simple acceptation n’ajoute pas d’exemple. Les apprentissages
s’appliquent aux prochains lots ; les anciens gardent leur profil de départ.

## Données et limites

Le profil fourni est décrit uniquement comme appris sur des **photos de mariages**.
Les ressources distribuées conservent seulement les paramètres du modèle de tri,
sans photos d’apprentissage, noms, chemins, métadonnées EXIF, exemples
individuels ou effectifs du corpus. Le packaging vérifie le profil fourni et refuse
les fichiers non autorisés dans les ressources. Les données utilisées pour créer
ce profil restent privées et ne doivent pas être ajoutées au dépôt ni aux archives.

Les profils sont dans `%LOCALAPPDATA%\AtelierPhoto` sur Windows et
`~/Library/Application Support/AtelierPhoto` sur Mac. `ATELIER_DATA_DIR` permet
un autre emplacement. Supprimer un profil efface sa mémoire et ses lots,
mais conserve les originaux et exports. Les originaux d’un lot doivent rester
accessibles jusqu’à l’export. Une bibliothèque créée par une version précédente
s’ouvre normalement ; ses anciens réglages de retouche et de recadrage sont ignorés.

Sous Windows, fermer Atelier Photo puis utiliser **Paramètres → Applications →
Applications installées → Atelier Photo → Désinstaller**. La désinstallation
supprime le programme, ses composants embarqués, ses raccourcis et le dossier
`%LOCALAPPDATA%\AtelierPhoto` : profils, apprentissages, reportages enregistrés,
lots, aperçus et tâches. Les originaux et exports dans vos dossiers personnels
sont conservés. Installer une mise à jour conserve les profils.
Cette suppression des données nécessite un installateur contenant cette version
du désinstallateur ; un ancien installateur ne se met pas à jour tout seul.
Un emplacement personnalisé via `ATELIER_DATA_DIR` reste à nettoyer séparément :
le désinstallateur ne supprime pas un dossier arbitraire indiqué par une variable
d’environnement.

Pour vérifier le cycle Windows avec Inno Setup disponible dans `.build-tools/inno`,
exécuter en PowerShell `$env:ATELIER_TEST_INSTALLER='1'`, puis
`python -m pytest tests/test_windows_uninstall.py -q`. Le test utilise un
identifiant d’application unique et des données temporaires ; il vérifie la
mise à jour, le blocage pendant l’exécution et la suppression des données,
composants, raccourcis et entrée de désinstallation.

DINOv3 Small analyse le contenu en 448 × 448 sur CPU. Le tri combine ce contenu,
la netteté, l’exposition et le contexte de la scène. Il n’y a pas de détecteur de
visage : le regard, le sourire ou les yeux fermés demandent une vérification.

Le modèle livré exécute des opérations ONNX standard et lit ses poids dans
`model.onnx_data`, à côté du graphe. L’analyse et l’apprentissage du profil
s’effectuent sur l’ordinateur. Hugging Face sert à préparer les fichiers du
modèle avant leur distribution. Atelier désactive la télémétrie d’ONNX Runtime
avant son initialisation. Sous Windows, l’autodiagnostic vérifie que le processus
qui exécute DINOv3 ne s’inscrit pas au fournisseur de télémétrie de Microsoft.

Une photo reconnue comme endommagée est écartée pendant l’import d’un lot,
l’apprentissage sur un rush ou l’ajout de références. Le fichier est
déplacé dans un sous-dossier **Photos corrompues** à côté de l’original (avec son
XMP éventuel), retiré du reportage ou du groupe de références, et signalé à la fin
de la tâche. Ce sous-dossier est ignoré lors du parcours du dossier parent.

Dans le profil concerné, cliquez sur **Récupérer les photos corrompues**,
cochez les fichiers et choisissez le dossier où enregistrer les copies. Pour
les RAW, le logiciel tente d’extraire l’aperçu du boîtier. Sa résolution dépend
du fichier. Il peut aussi récupérer certains JPEG tronqués ou PNG dont les
métadonnées sont endommagées. Vérifiez visuellement chaque copie, puis
importez-la comme photo ou comme référence si vous souhaitez l’utiliser.
Le résultat de chaque tentative reste disponible depuis le même bouton.

Un boîtier simplement
non reconnu reste à sa place et apparaît dans **Erreurs de lecture**.
La prise en charge des boîtiers dépend de LibRaw. Les aperçus RAW sont un développement
neutre du boîtier : ils servent à juger la photo, pas à la livrer.

## Installer depuis les sources

Cette section sert à lancer le code du dépôt, sans fabriquer d’installateur.
Télécharger ou cloner les sources, puis ouvrir un terminal dans le dossier qui
contient `main.py`. Le projet accepte **Python 3.12, 3.13 ou 3.14 en 64 bits**.
Python reste installé à son emplacement habituel ; seul l’environnement `.venv`
est créé dans le dossier du projet.

Si un environnement `.venv` fonctionne déjà dans ce dossier sur cette machine,
passer directement à son activation, sans le recréer.
Ne pas lancer la création par-dessus ce dossier avec une autre version de Python :
les bibliothèques compilées pour l’ancienne version peuvent y rester.

**Windows — Invite de commandes (`cmd`) :**

Afficher d’abord les versions installées :

```bat
py --list
```

Choisir une version compatible dans cette liste. Par exemple, avec Python 3.14 :

```bat
py -3.14 -m venv .venv
.venv\Scripts\activate.bat
```

Avec Python 3.13 ou 3.12, remplacer `-3.14` par `-3.13` ou `-3.12`.
Le message « No suitable Python runtime found » signifie que la version demandée
n’est pas installée ou détectée par `py` ; il ne dépend pas du dossier du projet.
Si `py` n’est pas disponible, vérifier `python --version` puis utiliser
`python -m venv .venv` si cette version est compatible.

**Mac — Terminal, avec Python natif Apple Silicon :**

Vérifier que `python3 --version` indique 3.12, 3.13 ou 3.14, puis :

```sh
python3 -m venv .venv
source .venv/bin/activate
```

**Puis, dans ce même terminal avec l’environnement activé :**

```sh
python -m pip install -r requirements-tested.txt
python -m pip install -e .
python scripts/download_model.py
python scripts/download_licenses.py
python main.py
```

Cette préparation nécessite Internet. Les poids DINOv3 (environ 86 Mo) sont
épinglés et vérifiés par SHA-256 ; l’application ne les télécharge pas à l’exécution.
Pour les lancements suivants, utiliser **Lancer Atelier Photo.cmd** sur Windows,
ou `./.venv/bin/python main.py` sur Mac, depuis le dossier du projet.
Le dossier `.venv` est propre à la machine : ne pas le transférer entre Windows et Mac.

Si NumPy signale des fichiers `cp312` incompatibles avec Python 3.14 (ou un autre
décalage de version), réinstaller les dépendances pour le Python de l’environnement
activé, puis relancer l’application :

```sh
python -m pip install --force-reinstall --only-binary=:all: -r requirements-tested.txt
python main.py
```

## Vérifier les sources

Après la préparation ci-dessus, dans le terminal avec `.venv` activé :

```sh
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check atelier scripts tests
python main.py --self-test test-output/diagnostic.json
```

Les tests couvrent l’apprentissage cumulé, les correspondances, la reprise,
la préservation du profil en cas d’erreur, la sélectivité des lots existants,
les corrections mémorisées, les dialogues et filtres de galerie, les lanceurs,
les archives de sources et la confidentialité des ressources distribuées.
Ils vérifient aussi l’ajout et la reprise des références, leur influence sur le
classement et sur le choix de la variante retenue dans une scène, ainsi que
l’export à l’identique avec les XMP voisins, sans écrasement.
Ruff contrôle aussi les scripts de préparation et de distribution.
Le diagnostic intégré vérifie aussi le vrai DINOv3, les processus de traitement,
l’aperçu Qt et l’export à l’identique dans une bibliothèque temporaire indépendante. Il fonctionne
sur les sources et sur l’exécutable compilé.

Pour vérifier le tri sur ses photos, conserver un reportage hors apprentissage,
examiner les moments manqués et les variantes retenues, puis essayer un export et une
reprise après fermeture. Deux outils complémentaires restent disponibles :

```sh
python scripts/evaluate_profile.py RUSH RETENUES --report test-output/evaluation.json
python scripts/check_raw_sample.py CHEMIN_PHOTO_RAW
```

L’évaluation utilise des blocs temporels séparés pour apprendre et mesurer.
Fournir deux dossiers distincts, les retenues hors du rush. Elle mesure la fidélité
aux choix fournis, pas une qualité esthétique universelle. Les essais sur les
boîtiers et les systèmes réellement utilisés restent nécessaires.

## Repères dans le code

- `atelier/app.py`, `workspace_ui.py`, `training_dialog.py`, `task_dialog.py` : interface Qt.
- `atelier/pipeline.py` : tâches d’analyse, d’apprentissage, de tri et d’export
  (copie à l’identique), avec suspension et reprise.
- `atelier/store.py` : base SQLite, profils, lots et corrections de tri.
- `atelier/analysis.py`, `selection.py` : propositions par photo, scènes, variantes
  et influence des références.
- `atelier/training.py` : correspondances rush / retenues et apprentissage de la sélection.
- `atelier/imaging.py`, `dino.py`, `xmp.py` : lecture, mesures, vecteur de contenu et XMP voisins.
- `scripts/` : préparation, évaluation, compilation et distribution ;
  `tests/` : tests automatisés ; `packaging/` : ressources des installateurs.

Chaque lot garde une copie du profil utilisé à sa création. Les bibliothèques
créées par une autre version du schéma SQLite ne sont pas migrées : l’application
refuse de les ouvrir.

## Construire et distribuer

- **Windows** : après préparation des sources et installation des dépendances
  de test (`python -m pip install -e ".[dev]"` dans l’environnement activé), lancer
  **Construire Atelier Photo (Windows).cmd** pour les tests, la compilation et
  l’installateur Inno Setup. Le script utilise le Python de `.venv` (3.12, 3.13
  ou 3.14) et télécharge le compilateur nécessaire à la première construction.
  Les tests utilisent un dossier temporaire dans `test-output/`. L’exécutable
  est vérifié avant de créer `dist/AtelierPhoto-0.8.0-Windows-x64-Setup.exe`.
- **Mac depuis Windows** : suivre le
  [guide GitHub Actions](docs/COMPILER_MAC_DEPUIS_WINDOWS.md).
- **Mac de construction** : suivre
  [LIRE SUR MAC - COMPILATEUR.md](LIRE%20SUR%20MAC%20-%20COMPILATEUR.md).

Les tests GitHub Actions se lancent lors des pushes et des pull requests.
Les workflows de compilation se lancent manuellement et produisent des artefacts
à télécharger. Un push ne reconstruit pas les installateurs d’une Release :
il faut compiler puis publier les nouveaux fichiers. Vérifier la réussite des
tests et du build pour le commit à distribuer. Le DMG de test utilise une
signature ad hoc, sans certificat Developer ID ni notarisation.

Les workflows installent les dépendances Python en une seule commande et mettent
les téléchargements pip en cache pour les exécutions suivantes. Le cache est
renouvelé lorsque les dépendances ou le workflow changent. Les installateurs
Windows et Mac sont envoyés sans recompression par GitHub Actions.

Par défaut, **Build desktop bundles** produit l’installateur Windows `.exe` et le
DMG Mac. Cocher **Créer aussi les ZIP des applications Windows et Mac** dans
**Run workflow** pour ajouter les archives des applications autonomes.
**Construire le DMG Mac de test** propose la même option pour le Mac seul.
L’enveloppe ZIP utilisée par GitHub pour télécharger les artefacts reste présente,
même lorsque les ZIP des applications ne sont pas demandés.

`python scripts/make_mac_transfer.py --github` crée une archive des sources sans
poids ONNX. `--builder` prépare l’archive de construction Mac avec le modèle déjà
téléchargé. Les sorties sont dans `dist/`, volontairement ignoré par Git, comme
les caches et `test-output/`. Publier les installateurs en Releases ; ne pas
forcer l’ajout de photos, profils ou poids au dépôt.

Conserver les licences et [notices tierces](THIRD_PARTY_NOTICES.md) dans toute
distribution. Les scripts de construction les recopient dans le bundle.
