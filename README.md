# Atelier Photo

Application de bureau pour Windows et Mac : tri des photos par scènes,
apprentissage de vos choix et de vos retouches, export non destructif.
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

Au premier lancement, créer un profil. On peut importer directement un lot avec
la sélection et le filtre par défaut, ou personnaliser le profil avant de commencer.

Pour le personnaliser, cliquer sur **Apprendre de reportages triés**, puis sur
**Ajouter un reportage : rush + photos retenues**. Choisir le dossier du rush
complet, puis le dossier des photos retenues, retouchées ou non. Les sous-dossiers
sont inclus dans les deux cas. Répéter pour
ajouter autant de reportages que souhaité. Les reportages enregistrés dans ce
profil réapparaissent à chaque ouverture de la liste.

Cocher les reportages à utiliser pour l’apprentissage ; les décocher permet de
les garder pour plus tard. **Retirer les éléments sélectionnés** les retire du
profil, y compris après apprentissage. Le bouton **Appliquer et relancer
l’apprentissage** recalcule la sélection et le filtre sur les seuls reportages
cochés, sans relire les photos déjà analysées. Sans reportage coché, ou si les
reportages restants ne suffisent plus pour apprendre, la sélection et le filtre
par défaut sont utilisés, complétés par les groupes de références cochés.
**Annuler** abandonne les changements.
Les fichiers photo, les lots déjà importés et les corrections validées dans ces
lots sont conservés.

Les retenues sont associées aux originaux par leur chemin, leur nom
(`DSC0123.jpg` ↔ `DSC0123.ARW`, suffixes de retouche compris), puis par ressemblance.
Les reportages restent séparés, même si leurs noms de fichiers se répètent.
Les correspondances ambiguës sont signalées et ignorées. Choisir un dossier de
rush contenant les originaux et conserver les exports retouchés dans un dossier
distinct. Si le dossier des retenues est à l’intérieur du rush, il est exclu du
rush pour éviter de compter les retouches comme des originaux supplémentaires.

- **Sélection** : au moins 6 originaux, dont 2 retenus et un écarté au total.
- **Filtre couleur** : au moins 5 paires original / retouche couleur de même
  cadrage. Les recadrages et versions noir et blanc n’enseignent que la sélection.
  Si le filtre ne peut pas être appris, le filtre par défaut reste utilisé.

Attendre le bilan avant d’importer un nouveau lot. **Suspendre**, puis **Gérer les
tâches → Reprendre** permettent de continuer sans doublonner les exemples. Un reportage
inachevé peut être repris depuis la liste. Si un fichier est illisible ou absent,
le profil précédent est conservé : corriger le fichier puis relancer depuis la
liste, ou retirer le reportage concerné. Pour un fichier simplement absent, le
remettre à son emplacement permet aussi de reprendre la tâche suspendue.

**Gérer les tâches → Supprimer** retire une tâche en attente, suspendue ou
interrompue. Une analyse inachevée est supprimée avec son lot incomplet et ses
aperçus. Supprimer une tâche d’export conserve les fichiers déjà exportés ;
supprimer une tâche d’apprentissage conserve les reportages enregistrés et le
profil déjà appris. Les corrections mémorisées avec **Valider le lot** restent
conservées lorsque l’on change ou retire les reportages d’apprentissage.

**Effacer les corrections apprises** oublie uniquement les corrections mémorisées
par **Valider le lot**, pour le profil sélectionné. Les reportages d’apprentissage
et les lots existants sont conservés ; les prochains lots n’utiliseront plus ces
corrections. Valider à nouveau un ancien lot peut les mémoriser à nouveau.

Un rush déjà présent dans la liste ne peut pas être ajouté une seconde fois.
Le logiciel ajuste la sélection et le rendu ; il ne réentraîne
pas les poids DINOv3. Pour juger le résultat, utiliser un reportage distinct de
ceux fournis pour l’apprentissage.

### Ajouter des références sans rush

Une **référence est une photo exemple sans son rush associé**.

Ouvrir **Apprendre de reportages triés**, puis cliquer sur **Ajouter des références**,
à côté du bouton **Ajouter un reportage**. Sélectionner les photos dont le sujet
et le rendu plaisent, idéalement les versions finales retouchées. Les formats RAW,
JPEG et PNG sont acceptés.

Chaque ajout apparaît comme **un groupe dans la liste**, avec son nom et son
nombre de photos. Cocher le groupe pour l’utiliser ; le décocher pour le garder
sans qu’il influence les prochains imports. Les reportages et les références
peuvent être utilisés ensemble ou séparément.

Appliquer les modifications pour enregistrer ces choix. **Annuler** conserve la
configuration précédente. **Retirer les éléments sélectionnés** retire les
groupes choisis du profil sans supprimer les photos d’origine.

Le profil mémorise leur contenu et leur rendu pour personnaliser les prochains lots :

- **Sélection** : la ressemblance aux références contribue au classement, même
  avec le modèle par défaut ou un modèle appris sur des reportages. Les contrôles
  techniques et le tri par scène restent actifs.
- **Retouches** : les références les plus proches guident l’exposition, la
  température, le contraste et la saturation. Si un filtre par défaut ou appris
  est présent, ces ajustements complètent son rendu.

Sans rush ni paires original / retouche, ces exemples ne montrent pas les photos
à écarter ni les étapes exactes d’une retouche. Ils personnalisent les préférences
du profil, en complément des reportages.

Attendre le message de fin du traitement, puis importer les photos à trier :
elles bénéficieront des exemples cochés. Les lots déjà importés gardent leurs
propositions et leurs retouches ; changer les exemples ne refait pas leur analyse.

**Suspendre**, puis **Gérer les tâches → Reprendre** permettent de poursuivre le
traitement. Si une nouvelle référence est illisible, les réglages précédents
restent actifs : corriger le fichier puis relancer depuis la liste, ou retirer
le groupe concerné.

Les groupes restent mémorisés après fermeture. Recocher un groupe déjà analysé
réutilise les données enregistrées, même si ses photos ont ensuite été déplacées.
Les références ajoutées avec une ancienne version sont réunies automatiquement
dans le groupe **Références déjà ajoutées**, lui aussi décochable.

Une photo identique présente dans plusieurs groupes ne compte qu’une fois parmi
les références actives. **Effacer les corrections apprises** conserve les groupes.

## Trier, retoucher et exporter

1. Importer des fichiers, un dossier ou les glisser sur la zone
   **Déposez un dossier ou des photos ici**, au-dessus de la galerie.
   Les sous-dossiers sont inclus. La sélectivité garde davantage de photos à gauche,
   moins à droite. Survoler le titre **Sélectivité** ou son curseur affiche les
   explications ; un double-clic sur le curseur le remet au centre.
   Elle s’applique aux prochains imports et recalcule aussi le tri
   du lot affiché au relâchement du curseur, sans relire les photos. Les choix
   manuels et les retouches sont conservés ; valider à nouveau après le recalcul.
   Chaque lot retrouve son réglage lorsqu’on le sélectionne. Terminer ou supprimer
   une tâche d’export suspendue avant de modifier son tri. Avec le profil fourni,
   le centre vise **environ 16 % de retenues**, indépendamment du taux du corpus
   d’apprentissage, avec **jusqu’à 35 % de photos à vérifier**. Les profils appris sur vos reportages
   conservent leur propre taux. Les doublons, défauts techniques et scènes très
   répétitives peuvent réduire le nombre retenu. Les photos **À vérifier** sont
   comptées séparément : elles ne font pas partie des retenues et ne sont pas exportées.
   Leur plafond inclut les doutes techniques et les corrections passées qui
   invitent à vérifier une photo. Il concerne les décisions automatiques : les
   choix manuels conservés peuvent dépasser ces proportions. Pour 100 photos
   exploitables et suffisamment variées, la cible au centre est de 16 retenues,
   jusqu’à 35 à vérifier et le reste écarté.
   Lors d’une suspension, ces proportions s’appliquent aux photos déjà analysées ;
   le tri reste provisoire et sera recalculé sur l’ensemble à la fin de l’import.
   Après une interruption brutale, les photos dont le tri n’a pas été calculé
   apparaissent **en attente de tri**, sans gonfler le compteur des retenues.
   Reprendre l’import via **Gérer les tâches** pour terminer le lot.
2. Examiner **Retenues**, **À vérifier**, **Écartées** et **Erreurs de lecture**.
   **Voir les variantes** ou un double-clic ouvre la scène ; **Tout afficher**
   revient à la galerie. Les touches 1, 2 et 3 changent la décision.
3. Comparer l’original et la retouche. Ctrl/Cmd + clic sélectionne plusieurs
   photos ; les curseurs s’appliquent à toute la sélection. **Rétablir** remet la
   recette initiale ; un double-clic sur un curseur rétablit ce seul réglage.
   Le bouton de filtre coupe ou réapplique le filtre sur tout le lot, export compris.
4. **Valider le lot**, puis exporter les retenues en JPEG qualité 95, PNG ou
   **RAW + XMP**. Les photos à vérifier ne sont pas exportées. Les RAW sont copiés
   à l’identique ; les JPEG/PNG d’un export RAW + XMP deviennent des JPEG retouchés.
   Aucun fichier existant n’est écrasé.
5. **Mettre l’export en pause** termine la photo en cours. **Reprendre l’export**
   continue dans le même dossier et au même format, y compris après fermeture.
   Une coupure exactement pendant la publication d’un fichier peut produire une
   copie supplémentaire à la reprise.

Un lot doit être entièrement analysé avant validation. Supprimer un lot retire
ses aperçus et tâches, mais conserve les originaux, exports et corrections déjà
mémorisées. Seules les corrections explicites de sélection ou de réglage alimentent
la mémoire ; une simple acceptation n’ajoute pas d’exemple. Les apprentissages
s’appliquent aux prochains lots ; les anciens gardent leur profil de départ.

## Données et limites

Le profil fourni est décrit uniquement comme appris sur des **photos de mariages**.
Les ressources distribuées conservent les paramètres nécessaires au tri et à la
retouche, sans photos d’apprentissage, noms, chemins, métadonnées EXIF, exemples
individuels ou effectifs du corpus. Le packaging vérifie le profil fourni et refuse
les fichiers non autorisés dans les ressources. Les données utilisées pour créer
ce profil restent privées et ne doivent pas être ajoutées au dépôt ni aux archives.

Les profils sont dans `%LOCALAPPDATA%\AtelierPhoto` sur Windows et
`~/Library/Application Support/AtelierPhoto` sur Mac. `ATELIER_DATA_DIR` permet
un autre emplacement. Supprimer un profil efface sa mémoire et ses lots,
mais conserve les originaux et exports. Les originaux d’un lot doivent rester
accessibles jusqu’à l’export.

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
Les retouches sont globales, sans masque, recadrage ou génération de détails.

Le filtre appris n’est pas transposé dans le XMP : seuls les réglages globaux
compatibles y figurent, sans conversion de température en Kelvin pour les RAW.
Un RAW corrompu ou tronqué n’interrompt ni l’import ni l’apprentissage : il est
déplacé dans un sous-dossier **Photos corrompues** à côté de l’original (avec son
XMP éventuel), retiré du reportage ou du groupe de références, et signalé à la fin
de la tâche. Ce sous-dossier n’est jamais relu lors d’un import. Un boîtier simplement
non reconnu reste à sa place et apparaît dans **Erreurs de lecture**.
La prise en charge des boîtiers dépend de LibRaw. Les exports JPEG/PNG sont en
8 bits sRGB et les aperçus RAW peuvent différer légèrement du développement final.
Une image pleine résolution doit tenir en mémoire à l’export.

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
Ils vérifient aussi l’ajout et la reprise des références, ainsi que leur influence
sur le classement et le rendu avec un modèle et un filtre déjà présents.
Ruff contrôle aussi les scripts de préparation et de distribution.
Le diagnostic intégré vérifie aussi le vrai DINOv3, les processus de traitement,
l’aperçu Qt et l’export dans une bibliothèque temporaire indépendante. Il fonctionne
sur les sources et sur l’exécutable compilé.

Pour vérifier le rendu sur ses photos, conserver un reportage hors apprentissage,
examiner les moments manqués et les retouches, puis essayer un export et une
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

- `atelier/app.py`, `training_dialog.py`, `task_dialog.py` : interface Qt.
- `atelier/pipeline.py` : tâches d’analyse, d’apprentissage, de tri et d’export,
  avec suspension et reprise ; processus séparé pour les aperçus.
- `atelier/store.py` : base SQLite, profils, lots, corrections et migrations.
- `atelier/analysis.py`, `selection.py` : propositions par photo et tri par scène.
- `atelier/training.py`, `look.py` : correspondances rush / retenues et
  apprentissage de la sélection et du rendu couleur.
- `atelier/imaging.py`, `dino.py`, `xmp.py` : lecture, rendu, encodage et export XMP.
- `scripts/` : préparation, évaluation, compilation et distribution ;
  `tests/` : tests automatisés ; `packaging/` : ressources des installateurs.

Les anciens lots gardent une copie du profil utilisé à leur création. Les
migrations SQLite et les lecteurs d’anciennes tâches servent à préserver ce
travail ; ils ne sont pas du code inutilisé.

## Construire et distribuer

- **Windows** : après préparation des sources et installation des dépendances
  de test (`python -m pip install -e ".[dev]"` dans l’environnement activé), lancer
  **Construire Atelier Photo (Windows).cmd** pour les tests, la compilation et
  l’installateur Inno Setup. Le script utilise le Python de `.venv` (3.12, 3.13
  ou 3.14) et télécharge le compilateur nécessaire à la première construction.
  Les tests utilisent un dossier temporaire dans `test-output/`. L’exécutable
  est vérifié avant de créer `dist/AtelierPhoto-0.4.0-Windows-x64-Setup.exe`.
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
