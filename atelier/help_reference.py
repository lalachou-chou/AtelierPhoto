"""Référence technique complète d'Atelier Photo (Markdown).

Affichée dans l'onglet « Aide avancée » et copiée à l'identique dans
``docs/FONCTIONNEMENT_DETAILLE.md`` (un test vérifie que les deux sont égaux).
Chaque valeur citée ici provient du code ; le nom du module est indiqué pour
permettre de la vérifier.
"""

REFERENCE = r"""# Atelier Photo — fonctionnement détaillé

Ce document décrit ce que fait Atelier Photo, comment et avec quelles valeurs. Il s'adresse à toute personne qui veut vérifier le logiciel plutôt que lui faire confiance. Les modules cités sont dans le dossier `atelier/` du code source, les tests dans `tests/`.

## 1. Principes et garanties

- **Tout est local.** L'analyse, l'apprentissage, le rendu et l'export s'exécutent sur l'ordinateur. Aucune fonction de l'application n'envoie de photo, de vecteur, de réglage ou de statistique sur un réseau. Le seul téléchargement du projet est celui du modèle DINOv3, fait par `scripts/download_model.py` au moment de la préparation du logiciel, jamais à l'exécution.
- **Pas de télémétrie.** Avant d'initialiser le moteur ONNX Runtime 1.30.0, `local_runtime.py` positionne `ORT_DISABLE_TELEMETRY=1`. Sous Windows, il positionne aussi `ORT_RUNNING_UNIT_TESTS=1`, pour que le moteur ne s'inscrive pas au fournisseur de télémétrie `Microsoft.ML.ONNXRuntime`, puis il appelle `disable_telemetry_events()`. L'autodiagnostic (§ 18) vérifie sous Windows que le processus n'est pas inscrit.
- **Aucun pixel inventé.** Aucun modèle génératif n'est utilisé. Toutes les retouches sont des transformations photographiques déterministes : exposition, balance, contraste, saturation, courbe, clarté, TSL et table de couleurs. Elles s'appliquent pixel par pixel ou à travers des masques progressifs.
- **Les originaux ne sont jamais réécrits**, sauf si vous cochez « Remplacer les originaux » à l'export et confirmez (section 13.1 bis). Sinon, les exports sont de nouveaux fichiers. Avant chaque export, l'empreinte SHA-256 de la source est comparée à celle mesurée à l'analyse ; si elle diffère, l'export est refusé (« L'original a changé depuis son analyse »). Une copie à l'identique est relue et son empreinte comparée à l'original.
  Exception : un fichier reconnu comme **endommagé** est **déplacé**, sans être modifié, dans un sous-dossier `Photos corrompues` à côté de lui (§ 16).
- **Déterminisme.** Pour un même fichier, un même profil et une même version du modèle, l'analyse donne le même résultat. Il n'y a pas de tirage aléatoire dans le tri ni dans le rendu.

## 2. Architecture et processus

- **Interface.** Elle utilise Qt (PySide6) et s'exécute dans le processus principal (`app.py`, `workspace_ui.py`, `training_dialog.py`, `crop_dialog.py`, `task_dialog.py`, `recovery_dialog.py`, `help_ui.py`).
- **Tâches longues.** L'analyse, l'apprentissage, le tri, l'export et la récupération s'exécutent chacune dans **un processus séparé**, lancé en mode `spawn` (`pipeline.run_job`). L'interface reste fluide et une erreur du moteur ne peut pas la faire tomber. Une seule tâche tourne à la fois.
- **Préparation parallèle.** Dans ce processus, deux fils préparent les photos à l'avance (décodage, mesures, vecteur DINOv3), au plus deux photos devant la photo en cours. Les écritures en base restent ordonnées.
- **Aperçus.** Un second processus, `preview_worker`, rend l'aperçu de la vue agrandie. Seule la demande la plus récente est traitée. L'image source de l'aperçu est décodée une fois et gardée en mémoire tant que la photo ne change pas.
- **Bibliothèque.** C'est une base SQLite (`library.sqlite3`, journal WAL, clés étrangères actives, `secure_delete=ON`) accompagnée de dossiers privés.
- **Dossier de données.**

  | Système | Dossier |
  | --- | --- |
  | Windows | `%LOCALAPPDATA%\AtelierPhoto` |
  | macOS | `~/Library/Application Support/AtelierPhoto` |
  | Linux | `~/.local/share/atelier-photo` |

  La variable d'environnement `ATELIER_DATA_DIR` le remplace.
- **Contenu du dossier de données.**
  - `library.sqlite3` : la base.
  - `interface.ini` : palette, profil actif, largeur et visibilité des colonnes.
  - `application.lock` : verrou qui empêche d'ouvrir deux fois la même bibliothèque.
  - `profiles/<profil>/batches/<lot>/<photo>.png` : copie d'analyse, 1 280 px au plus.
  - `profiles/<profil>/batches/<lot>/<photo>.jpg` : vignette, 240 × 180 px au plus, qualité 85.
  - `profiles/<profil>/training/<reportage>/<échantillon>.npy` : échantillon couleur 48 px de large, float16.
  - `profiles/<profil>/references/<référence>.png` : copie d'analyse d'une référence.
- **Noms internes.** Les noms de fichiers internes sont des identifiants générés (UUID). Un nom de photo n'est jamais utilisé comme chemin interne, et tout chemin interne est vérifié comme étant à l'intérieur de `profiles/`.
- **Schéma de base.** Le schéma est versionné (`PRAGMA user_version = 8`, `store.py`). Une bibliothèque d'un autre schéma est refusée plutôt que convertie.
- **Démarrage.** Le verrou est pris. Les tâches restées « en cours » après un arrêt brutal passent à « suspendue » (`recover_interrupted_jobs`).
- **Windows.** Un mutex nommé (`AtelierPhoto.Application.03D9A7F4`) signale à l'installeur que l'application est ouverte.

### Tables de la base

| Table | Contenu |
| --- | --- |
| `profiles` | Nom, numéro de version (incrémenté à chaque changement d'apprentissage) et modèle appris (JSON) |
| `reportages`, `training` | Reportages d'apprentissage et, pour chaque photo, statistiques, vecteur, date et rôle (rush ou retenue) |
| `reference_groups`, `reference_members`, `refs` | Groupes de références, appartenance et données de chaque référence (dédoublonnée par empreinte) |
| `batches` | Lots importés, avec un **instantané figé** du profil au moment de l'import, la sélectivité et les interrupteurs « retouche du lot » et « recadrages du lot » |
| `photos` | Une ligne par photo d'un lot : chemin et données JSON (mesures, vecteur, décision, réglages, retouches) |
| `feedback` | Corrections validées qui servent à l'apprentissage à l'usage (§ 8) |
| `jobs` | Tâches avec type, contenu, curseur, état et erreur |
| `quarantine` | Photos mises à l'écart, résultat et erreur de récupération |

## 3. Formats et décodage (`imaging.decode`, `config.py`)

- **Extensions acceptées.**
  - RAW : `.arw .cr2 .cr3 .nef .nrw .dng .raf .orf .rw2 .pef .srw .3fr .iiq .rwl .x3f`.
  - Images : `.jpg .jpeg .png`.
- **Parcours d'un dossier.** Il est récursif. Les fichiers cachés (dont `._*` de macOS) et le sous-dossier `Photos corrompues` sont ignorés.
- **RAW** (LibRaw via `rawpy`).
  - Développement : `postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=16, output_color=sRGB, gamma=(2.4, 12.92))`, c'est-à-dire la balance du boîtier, aucune luminosité automatique, 16 bits par canal et la courbe sRGB.
  - Pour l'analyse, `half_size=True` donne une image demi-taille, réduite à 8 bits puis à 1 280 px au plus (Lanczos). L'export repart toujours du RAW en pleine définition, sur 16 bits.
- **JPEG et PNG.**
  - L'orientation EXIF est appliquée.
  - Un profil ICC intégré est converti en sRGB (LittleCMS via Pillow).
  - La transparence est composée sur fond blanc.
  - Pour l'analyse, un JPEG est décodé en mode brouillon à environ 1 600 px puis réduit à 1 280 px.
  - Les EXIF photographiques sont conservés pour l'export, sauf l'orientation, les dimensions et la vignette, qui décriraient l'image non tournée. L'espace couleur EXIF est forcé à sRGB.
- **Détection d'un fichier endommagé.** C'est la preuve positive d'une corruption, pas un simple échec de lecture.
  - LibRaw signale une erreur de données ou d'entrée-sortie.
  - Un CR2 a un bloc RAW dont la position ou la longueur sort du fichier, ou qui ne commence pas par un marqueur JPEG (`cr2.broken_raw_strip`).
  - Un JPEG ou un PNG a un en-tête valide mais des données illisibles.

  Un boîtier simplement non reconnu produit une erreur de lecture, sans déplacement du fichier.

## 4. Analyse d'une photo (`pipeline.prepare_photo`, `imaging.features`, `dino.py`)

Pour chaque photo importée :

1. **Empreinte** SHA-256 du fichier, pour l'intégrité et les doublons exacts.
2. **Date de prise de vue** : EXIF `DateTimeOriginal`, avec les sous-secondes, sinon `DateTime`, sinon la date du fichier. Elle sert uniquement à ordonner les photos et à découper les scènes.
3. **Mesures techniques**, calculées sur une copie de 512 px au plus.

   | Mesure | Calcul |
   | --- | --- |
   | `luma` | Médiane de la luminance |
   | `spread` | Écart entre les quantiles 90 % et 10 % de la luminance |
   | `saturation` | Saturation TSV moyenne |
   | `rgb` | Moyenne de chaque canal |
   | `sharpness` | Quantile 80 % des variances du laplacien sur une grille de 4 × 4 tuiles |
   | `peak` | Variance du laplacien de la tuile la plus nette |
   | `noise` | Médiane de l'écart à un filtre médian 3 × 3, sur les 35 % de pixels les plus plats |
   | `black` | Proportion de pixels sous 1,5 % de luminance |
   | `white` | Proportion de pixels au-dessus de 98,5 % de luminance |
   | `aspect` | Largeur divisée par la hauteur |

4. **Vecteur de contenu DINOv3.**
   - Modèle : DINOv3 ViT-S/16, dépôt `onnx-community/dinov3-vits16-pretrain-lvd1689m-ONNX`, format ONNX float32.
   - Entrée : l'image est redimensionnée en 448 × 448 (bilinéaire) et normalisée avec les moyennes et écarts-types ImageNet (0,485 0,456 0,406 / 0,229 0,224 0,225).
   - Sortie : `pooler_output`, un vecteur de 384 dimensions, normalisé à la norme 1.
   - Exécution : sur le processeur seul (`CPUExecutionProvider`), avec 2 fils intra-opération et 1 inter-opération, sans profilage.
   - **Comparaison :** la ressemblance entre deux photos est le produit scalaire de leurs vecteurs, entre −1 et 1.
   - **Intégrité :** `model_assets.verify_model` compare l'empreinte SHA-256 du graphe et des poids à celles du manifeste `model.json` avant tout chargement. La version de l'encodeur (nom, prétraitement, empreintes) est enregistrée avec chaque vecteur. Des vecteurs d'une autre version ne sont jamais mélangés : un lot créé avec un modèle exige ce modèle.
5. **Copies privées.** Atelier enregistre une copie d'analyse en PNG (compression rapide) et une vignette JPEG. Si le profil a une retouche apprise, il calcule aussi un échantillon couleur de 48 px de large (§ 7).

## 5. Proposition pour chaque photo (`analysis.propose`)

### 5.1 Verdict technique (`analysis.technical`)

La sélectivité `s` va de 0 (souple) à 1 (stricte) ; elle vaut 0,5 au centre.

| Verdict | Condition |
| --- | --- |
| Écartée | Image presque entièrement noire ou blanche : `black` > 0,97 ou `white` > 0,97 |
| Écartée | Image entièrement floue : `peak` < 0,00012 + 0,00018·s et `spread` > 0,12. Elle passe « à vérifier » si une photo proche (§ 5.2) avait été retenue. |
| À vérifier | Netteté incertaine : `sharpness` < 0,0003 + 0,0007·s |
| À vérifier | Ombres ou hautes lumières perdues : `black` > 0,35 ou `white` > 0,25 |
| À vérifier | Bruit visible : `noise` > 0,035 |
| À vérifier | Sans modèle de tri et avec des références : ressemblance moyenne aux 3 références les plus proches inférieure à 0,60 + 0,12·s (bonus de 0,04 si une photo proche avait été retenue) |
| À vérifier | Une correction passée sur une photo proche était « écartée » ou « à vérifier » |

### 5.2 Voisins et poids

- **Photo « proche ».** Une photo est proche d'une autre quand leur ressemblance DINOv3 dépasse **0,82**. On ne garde que les 8 plus proches.
- **Poids d'un voisin.** Quand plusieurs voisins proposent un réglage, chacun pèse sa ressemblance élevée à la puissance 6. Une photo à 0,95 pèse ainsi environ 1,8 fois plus qu'une photo à 0,85.

### 5.3 Rendu proposé (« style du lot »)

- **Cibles de rendu.**
  - Les références proches dont le rendu est connu : JPEG, PNG et RAW + XMP. Un RAW sans XMP ne compte pas.
  - Les paires original / retouche des reportages dont la ressemblance est d'au moins 0,82.
  - On garde au plus 3 cibles, à moins de 0,08 de la meilleure.
- **Écart relatif pour une paire ou un RAW + XMP.** La cible n'est pas l'image retouchée elle-même mais l'écart avant / après, appliqué à la photo : `cible = (photo + 0,05) × (après + 0,05) / (avant + 0,05) − 0,05` pour la luminance, l'étendue et la saturation, et `photo + après − avant` pour les canaux.
- **Calcul des curseurs,** à partir des médianes des cibles. Ils sont calculés après la table de couleurs apprise s'il y en a une, pour ne pas compter la retouche deux fois.

  | Curseur | Formule | Bornes |
  | --- | --- | --- |
  | Exposition | `log2((luma cible + 0,05) / (luma photo + 0,05))` | ±0,65 IL |
  | Température | `1,5 × (écart rouge − bleu de la cible − écart rouge − bleu de la photo)` | ±0,35 |
  | Contraste | `(étendue cible − étendue photo) / max(0,15 ; étendue photo)` | ±0,45 |
  | Saturation | Même formule. Si la cible est en noir et blanc (saturation < 0,015), elle vaut −1. | ±0,6 |

- **Retouche de couleur apprise.** Si le profil en a une (§ 7.3), sa courbe de tons est calculée pour cette photo.
- **Réglages proposés.** Ils partent des valeurs neutres. L'intensité du style vaut 0,65, ou 1 quand une retouche apprise ou des cibles existent. Chaque curseur est ensuite remplacé par la moyenne pondérée (poids s⁶) des corrections validées sur les photos proches (§ 8).
- **Retouches par consigne et outils avancés appris.** Voir § 10 et § 11.
- **Cadrage proposé.**
  - En priorité, les cadrages manuels validés, puis ceux des paires de reportage. On garde ceux d'une photo proche (≥ 0,82) au rapport largeur / hauteur voisin (écart de `log` < 0,18), et on prend la médiane des bords.
  - À défaut, le rapport médian des références proches de même orientation, centré (`framing.ratio_crop`). Il est ignoré s'il recadre moins de 2 %.

## 6. Tri par scène (`analysis.finalize`, `selection.py`)

1. **Ordre.** Les photos sont triées par date de prise de vue, puis par nom.
2. **Scènes.** Une nouvelle scène commence si plus de **20 s** séparent deux photos, ou si la ressemblance de la photo au barycentre de la scène en cours tombe sous **0,80**.
3. **Description de chaque photo** (`selection.design`). C'est un vecteur de 400 valeurs :
   - les 8 mesures techniques (`sharpness`, `peak` et `noise` passées au logarithme) ;
   - 8 valeurs de contexte dans sa scène : taille de la scène (logarithme), netteté relative à la meilleure, indicateur « la plus nette de la scène », rang de netteté, ressemblance au barycentre, pic relatif au meilleur, durée de la scène, écart à la netteté moyenne ;
   - les 384 valeurs du vecteur DINOv3.
4. **Score.**
   - **Avec un modèle de tri compatible** (même encodeur, même version de description) : régression logistique. Elle est entraînée par méthode de Newton (50 itérations au plus) avec une pénalité L2 de force C = 0,02, l'ordonnée à l'origine n'étant pas pénalisée, sur des valeurs centrées-réduites.
     - Le modèle **fourni** (`assets/default_profile.json`) a été appris sur des photos de mariages et retient environ 15,5 % des photos.
     - Un profil appris sur vos reportages le remplace (§ 7).
     - Si des références sont actives, on ajoute 2 × l'écart-type des scores × la ressemblance aux références.
   - **Sans modèle compatible** : `2 × netteté relative + 1,5 × « meilleure de la scène » + 3 × ressemblance au barycentre + 2 × ressemblance aux références`.
   - **Préférence** issue des photos proches retenues (+1) ou écartées (−1) : l'écart-type des scores × la moyenne de ces votes.
5. **Taux de rétention.**
   - `centre = 16 %` avec le modèle fourni, ou `1,25 × taux appris` avec un profil personnel.
   - `retenues = centre × 2^((0,5 − s) × 2)`, borné entre 3 % et 90 %.
   - `à vérifier = min(35 %, 1 − retenues)`.
6. **Décision** (`selection.decide`).
   - 70 % du budget de retenues sert à prendre **la meilleure photo de chaque scène**, en commençant par les meilleures scènes.
   - Le reste ajoute une autre photo d'une scène seulement si elle est **différente** de celles déjà retenues (ressemblance < 0,93).
   - « À vérifier » reçoit d'abord la meilleure photo des scènes sans retenue, puis les variantes.
   - Le reste est écarté.
   - Les échecs techniques restent écartés, et les photos « à vérifier » pour une raison technique ne sont jamais retenues automatiquement.
   - Les **doublons exacts**, de même empreinte, sont écartés sauf un.
7. **Raison affichée.** Chaque photo reçoit sa raison : meilleure image de la scène, variante, moment secondaire, doublon, remarques techniques, modèle de sélection utilisé.
8. **Changement de sélectivité.** Il relance seulement cette étape (`reselect`) à partir des mesures en cache. Les décisions manuelles et toutes les retouches sont conservées. La nouvelle sélectivité, les décisions et l'état de la tâche sont écrits ensemble dans une seule transaction.

## 7. Apprentissage du profil (`training.py`, `look.py`, `framing.py`, `pipeline.py`)

### 7.1 Reportages déjà triés

- **Contenu.** Un reportage est un dossier de rush complet plus un dossier de photos retenues, retouchées ou non. Un sous-dossier de retenues placé dans le rush est exclu du rush.
- **Exigences.** Le rush doit contenir des photos écartées. Pour apprendre le tri, il faut au moins **6 photos dont 2 retenues** ; un reportage complet de plusieurs centaines de photos est préférable.
- **Correspondance retenue → original** (`training.match`). On essaie, dans l'ordre :
  - le même chemin ;
  - le même nom, sans casse ni ponctuation (`DSC08947 N&B.jpg` → `DSC08947.JPG`) ;
  - un nom préfixe d'au moins 4 caractères qui n'est pas suivi d'un chiffre ;
  - sinon, la ressemblance visuelle, à condition qu'elle dépasse **0,90** et devance la deuxième candidate d'au moins **0,02**.
  - Faute de correspondance certaine, la photo est ignorée et signalée. Un reportage sans aucune correspondance est exclu, sinon il apprendrait à tout écarter.
- **Modèle de tri.** C'est la régression logistique décrite au § 6, apprise sur toutes les photos des reportages cochés (retenue = 1, écartée = 0). Son taux de rétention est mémorisé.

### 7.2 Recadrage appris (`framing.register_pair`)

- **Recherche de la zone.** Pour chaque paire, Atelier cherche dans l'original la zone visible dans la retouche. Il utilise la corrélation croisée normalisée centrée, calculée par FFT, pour toutes les largeurs de 25 % à 100 %.
- **Acceptation.** Le cadre est retenu si son score atteint **0,88** et qu'aucun autre emplacement presque aussi bon (à moins de 0,035) n'est éloigné de plus de 9 %. Cela évite d'apprendre un décalage arbitraire sur une texture répétitive.
- **Mesure de la retouche.** Elle est faite sur la zone commune, pour qu'un ciel recadré ne soit pas pris pour un changement d'exposition.

### 7.3 Retouche de couleur apprise (`look.py`)

- **Paires utilisables.** L'original et la retouche doivent avoir le même cadrage (corrélation des contours ≥ 0,9) et la retouche ne doit pas être en noir et blanc. Il en faut **au moins 5**.
- **Table de couleurs 3D.** Elle fait 9 × 9 × 9 nœuds, avec interpolation trilinéaire. Elle est ajustée par moindres carrés avec une régularisation laplacienne (lissage 0,05) qui la garde douce, et bornée entre −0,1 et 1,1.
- **Courbe de tons propre à chaque photo.** Elle a 9 points, prédits à partir des statistiques de tons de la photo par une régression ridge (pénalité 30) et bornés à ±0,25. Une église sombre et un jardin lumineux ne reçoivent donc pas la même correction.
- **Coût.** Tout est en forme fermée et l'apprentissage prend quelques secondes.
- **Profil fourni.** Il contient une table de couleurs et un modèle de tri. Un profil neuf l'utilise jusqu'à ce que ses propres reportages le remplacent.

### 7.4 Références (photos exemples sans rush)

| Type | Traitement | Effet sur le profil |
| --- | --- | --- |
| JPEG ou PNG | Analysé tel quel | Ressemblance, rendu (cible absolue) et format du cadre |
| RAW + XMP | Le XMP voisin (`photo.xmp`, `photo.nef.xmp` ou `.XMP`) est lu et appliqué au RAW (§ 14.2) | Ressemblance, rendu (écart avant / après) et cadre |
| RAW seul | Développement neutre | Ressemblance et cadre seulement : `render=False`, il n'est pas une cible de rendu |

- **Dédoublonnage.** Les références sont dédoublonnées par empreinte. Pour un RAW + XMP, l'empreinte combine celles du RAW et du XMP, donc un XMP modifié donne une nouvelle référence.
- **Partage entre groupes.** Une photo présente dans deux groupes n'est analysée qu'une fois.

### 7.5 Publication et figement

- **Publication.** Le modèle appris est publié en une seule transaction, avec l'état de la tâche ; le numéro de version du profil augmente.
- **Instantané figé.** Chaque lot conserve l'instantané du profil pris à son import. Un apprentissage ultérieur ne modifie donc jamais un lot déjà importé.

## 8. Apprentissage à l'usage : corrections validées (`store.validate`)

- **Quand.** Rien n'est appris pendant la retouche. À la **validation du lot**, par le bouton « Valider le lot » ou par l'export, qui exige la validation, chaque photo dont une correction est **explicite** enregistre une ligne de `feedback`. Cette ligne est rattachée à son vecteur DINOv3.
- **Qu'est-ce qui compte comme explicite.**

  | Correction explicite | Ce qui est enregistré |
  | --- | --- |
  | Décision manuelle (retenue, à vérifier, écartée) | La décision |
  | Curseur global modifié | L'écart à la proposition ; en mode « retouche du lot retirée », les réglages manuels complets |
  | Cadrage modifié | Le cadre et le rapport largeur / hauteur |
  | Retouches par consigne | Les retouches gardées et les propositions refusées (§ 11) |
  | Clarté, courbe ou TSL changées par rapport à la proposition | Les valeurs appliquées |

- **Revalidation.** Elle est idempotente. Une correction annulée puis revalidée retire la ligne correspondante.
- **Au prochain import.** Ces corrections influencent les photos dont la ressemblance dépasse 0,82, pondérées par s⁶.
- **Effacer.** « Effacer les corrections apprises » supprime toutes les lignes `feedback` du profil. Les reportages, les références et les lots restent.

## 9. Rendu (`imaging.render_pixels`)

### 9.1 Ordre des opérations

Le même code sert à l'aperçu, au JPEG, au PNG et au TIFF. Les opérations sont ponctuelles, ou s'appuient sur des cartes estimées sur une copie réduite, d'où le même résultat à toute définition. L'image est traitée par bandes de 128 lignes pour limiter la mémoire.

1. **Clarté** (§ 10.1).
2. **Retouche de couleur apprise.** La table de couleurs puis la courbe de tons de la photo, mélangées selon le curseur « Intensité du style ».
3. **Exposition** : multiplication par `2^IL`.
4. **Température** : rouge × (1 + 0,12·t), bleu × (1 − 0,12·t).
5. **Contraste** : `(x − 0,5) × (1 + c) + 0,5`.
6. **Courbe des tons** (§ 10.2).
7. **Saturation** : `luma + (x − luma) × (1 + s)`, avec une luminance Rec. 709 (0,2126 ; 0,7152 ; 0,0722). s = −1 donne du noir et blanc.
8. **TSL** (§ 10.3).
9. **Retouches par consigne** (§ 11).
10. **Écrêtage** à [0, 1] puis quantification en 8 bits (aperçu, JPEG, PNG) ou en 16 bits (TIFF).

### 9.2 Curseurs globaux

- **Valeur appliquée.** Chaque curseur vaut la valeur de l'utilisateur plus la proposition du profil multipliée par « Intensité du style ».
- **Bornes.**

  | Curseur | Bornes |
  | --- | --- |
  | Exposition | ±2 IL |
  | Contraste | ±0,5 |
  | Saturation | ±0,6 |
  | Intensité | 0 à 1 |

- **Température en kelvins.** Le curseur affiche une température de 4 000 à 20 000 K, le pas de la conversion étant de 25 K.
  - **Conversion.** Pour chaque température, le point blanc du lieu des lumières du jour CIE est converti en sRGB. Le rapport rouge / bleu, normalisé à 6 500 K, donne le gain équivalent.
  - **Sens.** 6 500 K conserve la balance de départ ; plus de kelvins réchauffe, comme dans Lightroom.

### 9.3 Les deux modes du lot

| Mode | Réglages appliqués |
| --- | --- |
| « Retouche du lot » active | La proposition et vos modifications |
| « Retouche du lot » retirée | Les réglages manuels seuls, partant de zéro ; les outils avancés sans la part proposée par le profil ; les retouches par consigne tapées (les propositions apprises sont masquées) |

Le cadrage s'applique dans les deux modes.

### 9.4 Aperçu

- **Source.** L'aperçu part de la copie d'analyse (1 280 px), réduite à 1 100 × 850 px au plus.
- **Réactivité.** Chaque déplacement de curseur relance un rendu 100 ms plus tard, et seule la dernière demande est rendue.
- **Comparaison.** « Voir l'original » affiche la copie d'analyse sans retouche ni cadrage.

## 10. Outils avancés : clarté, courbe, TSL (`tools.py`)

Les valeurs suivent l'échelle de Lightroom divisée par 100 (−1 à 1), ce qui rend l'échange par XMP direct.

### 10.1 Clarté

- **Luminance floutée.** Elle est calculée sur une copie de 768 px au plus, avec un flou de rayon égal à 1,2 % du grand côté (trois flous de boîte successifs, proches d'un flou gaussien). Le rayon étant relatif au cadre, l'aperçu et l'export reçoivent le même effet.
- **Détail local** : `d = luminance − luminance floutée`, la carte floutée étant agrandie par interpolation bilinéaire.
- **Effet** : `luminance' = luminance + 1,2 × clarté × d × 4·L·(1 − L)`. Le facteur `4·L·(1 − L)` limite l'effet aux tons moyens.
- **Application aux couleurs.** Les trois canaux sont multipliés par `luminance' / luminance`, ce qui préserve les teintes. La luminosité moyenne ne change pas.

### 10.2 Courbe des tons

- **Courbe paramétrique.** Quatre bosses lisses, `(1 − u²)²` de demi-largeur 0,25, sont centrées sur 0,125, 0,375, 0,625 et 0,875 (ombres, tons sombres, tons clairs, hautes lumières), avec une amplitude de 0,12 × la valeur.
- **Toujours croissante.** La courbe est forcée croissante (maximum cumulé) : aucun ton n'est inversé.
- **Courbe par points.** Si un XMP en fournit une, elle est interpolée par une cubique monotone (Fritsch-Carlson), sur le canal commun puis par canal rouge, vert et bleu.
- **Table.** La courbe est échantillonnée sur 4 096 valeurs, puis appliquée par interpolation linéaire, sans paliers même en 16 bits.

### 10.3 TSL (teinte, saturation, luminance)

- **Couleurs.** Il y a 8 couleurs aux centres de Lightroom : rouges 0°, oranges 30°, jaunes 60°, verts 120°, turquoises 180°, bleus 240°, violets 270°, magentas 300°.
- **Couleurs voisines.** Entre deux centres, le réglage est interpolé linéairement selon la teinte du pixel. Les huit poids forment donc une partition de l'unité, sans transition brutale.
- **Effet.**
  - La teinte tourne de `réglage × 30°`.
  - La chrominance est multipliée par `1 + saturation`, entre 0 et 2.
  - La valeur est multipliée par `1 + 0,5 × luminance × min(1 ; 2 × saturation du pixel)`. Les gris et les pixels peu saturés restent donc neutres.
- **Calcul.** Seuls les pixels des couleurs réglées sont recalculés. La conversion inverse est analytique : `f(n) = V − C·max(0, min(k, 4 − k, 1))`.

### 10.4 Utilisation et apprentissage

- **Interface.** Dans « Retoucher », le groupe « Clarté, courbe et TSL » agit sur toutes les photos sélectionnées. Un double-clic revient à la proposition, et « Remettre les outils à la proposition » réinitialise tout le groupe.
- **Apprentissage.** Ces réglages sont appris à la validation (§ 8) et proposés en moyenne pondérée (s⁶) aux photos proches. La courbe par points n'est pas moyennée.

## 11. Retouches par consigne (`prompt.py`, `local.py`)

La liste des formulations est dans l'onglet « Retouche par consigne » et dans `docs/RETOUCHE_PAR_CONSIGNE.md`. Voici le fonctionnement interne.

### 11.1 Compréhension de la consigne

Le texte est analysé par un vocabulaire fixe, sans modèle de langage.
- **Normalisation.** Le texte est mis en minuscules, les accents et apostrophes sont retirés.
- **Découpage en consignes** sur `; ! ?`, sur la virgule et le point hors nombres décimaux, et sur « et », « puis », « ensuite ». « noir et blanc » n'est pas coupé.
- **Lecture d'une consigne.** Les réglages sont reconnus avant les zones ; chaque motif reconnu est retiré du texte.
- **Dosage et valeurs exactes.**
  - « légèrement » donne ×0,5, « très » donne ×1,75.
  - « +0,7 IL » et « 20 % » sont repris tels quels.
  - L'exposition est bornée à ±2 IL.
- **Inversion.** « sauf » inverse la zone.
- **Reprise d'éléments.**
  - Une consigne sans zone reprend la zone précédente.
  - Une consigne sans réglage, et sans mot inconnu, reprend le réglage précédent.
- **Partie non reconnue.** Elle est affichée, jamais devinée.

### 11.2 Pas des réglages

| Réglage | Pas |
| --- | --- |
| Exposition | 0,4 IL |
| Température | 0,35 |
| Contraste | 0,15 |
| Saturation | 0,3 |
| Clarté | 0,3 |
| Teinte | 0,5, soit 15° |

### 11.3 Zones et masques

Les masques sont estimés sur une copie développée de 384 px au plus. Ils sont agrandis par interpolation bilinéaire, puis affinés pixel par pixel à pleine définition.

| Zone | Méthode |
| --- | --- |
| Couleurs | Distance de teinte au centre de la plage (douce entre la demi-largeur / 2 et la demi-largeur), pondérée par la saturation (0,06 à 0,2) et la valeur (0,03 à 0,1) |
| Tons | Luminance. Ombres : effet complet sous 0,12, nul au-dessus de 0,45. Hautes lumières : effet nul sous 0,55, complet au-dessus de 0,85. Tons moyens : écart à 0,5 inférieur à 0,15 pour l'effet complet, nul au-delà de 0,38. |
| Position | Dégradés analytiques relatifs au cadre affiché. Haut : complet en haut jusqu'à 10 %, nul à partir de 60 %. Centre et bords : selon le rayon normalisé (centre : effet nul au-delà de 0,95). |
| Ciel | Germes bleus (teinte 212° ± 50°) ou couvert clair (luminance > 0,62, peu saturé), peu texturés. Propagation depuis la première ligne, de proche en proche entre segments qui se touchent. Bord affiné pixel par pixel par ressemblance à la couleur moyenne du ciel (écart type 0,12). Aucun effet si le ciel détecté couvre moins de 1 % de l'image. |
| Peau | Ellipse dans l'espace YCbCr (Cb ≈ 0,40 ± 0,09 ; Cr ≈ 0,60 ± 0,075), luminance entre 0,1 et 0,95, sur des régions cohérentes |
| Sujet | Saillance : 55 % de distance de couleur aux 48 couleurs échantillonnées sur les bords et 45 % de netteté locale, pondérées par une gaussienne centrée (0,5 ; 0,55). Seuil d'Otsu, exclusion des couleurs de fond (distance < 0,2), fermeture douce, puis filtre guidé (He et al.) pour coller aux contours sans halo. |
| Fond | 1 − sujet |
| Combinaisons | Produit des masques ; « sauf » donne 1 − produit |

### 11.4 Réglages locaux

- **Opérations.** Exposition, température et saturation s'appliquent comme en § 9. Le contraste local pivote autour de la luminance moyenne de la zone, pour ne pas éclaircir ni assombrir la zone dans son ensemble. La clarté locale utilise la même carte de détail qu'au § 10.1. La teinte locale est une rotation de `valeur × 30°`.
- **Calcul.** Il n'est fait que sur les pixels du masque.
- **Intensité.** Chaque retouche a une intensité de 0 à 200 %.

### 11.5 Apprentissage des retouches par consigne

L'apprentissage n'a lieu qu'à la validation.

| À la validation | Ce que le profil retient |
| --- | --- |
| Retouche tapée et gardée | La retouche est apprise |
| Proposition gardée sans changement | Rien de nouveau |
| Proposition dont l'intensité a changé | La retouche avec sa nouvelle intensité |
| Proposition décochée ou retirée | Un refus |

- **Identité d'une retouche.** Deux retouches sont considérées comme identiques si elles ont la même zone, la même inversion et les mêmes sens de réglage.
- **Vote.** Chaque photo proche (> 0,82) vote pour ou contre, avec un poids s⁶. Une retouche n'est proposée que si les votes pour l'emportent. Ses valeurs sont alors la moyenne pondérée des exemples, et elle apparaît avec la mention « (appris) ».

## 12. Recadrage (`crop_dialog.py`, `framing.py`)

- **Coordonnées.** Un cadre est enregistré en coordonnées normalisées (gauche, haut, droite, bas) de la photo orientée et entière. Il s'applique de la même façon à l'aperçu et à l'export.
- **Repères d'affichage.** Règle des tiers, grille 4 × 4, nombre d'or et spirale d'or. Ils servent seulement à l'affichage.
- **Retrait.** « Retirer le recadrage » agit sur une photo ; « Retirer les recadrages du lot » agit sur toutes les photos du lot, y compris celles masquées par un filtre de la galerie. Une photo peut être rétablie individuellement pendant un retrait de lot.
- **Apprentissage.** Seul un cadrage modifié photo par photo est appris à la validation. Un retrait de lot est un choix d'affichage ou d'export.

## 13. Export (`pipeline.export_one`)

### 13.1 Conditions et sécurité

- **Ce qui est exporté.** Uniquement les photos **retenues** d'un lot **validé**, dont l'analyse et le tri sont terminés. Les photos « à vérifier » ne sont pas exportées.
- **Nom du fichier.** `<nom d'origine>_Atelier_001.<ext>`. Le nom est **réservé** par une création exclusive (`O_CREAT | O_EXCL`) : un fichier existant n'est jamais écrasé, même par deux exports simultanés.
- **Écriture.** Elle passe par un fichier temporaire du même dossier, forcé sur le disque (`fsync`), puis remplacé atomiquement (`os.replace`). Une interruption ne laisse jamais de fichier à moitié écrit sous le nom final.
- **Contrôles.** L'empreinte de l'original est revérifiée avant l'export. Une copie (RAW, JPEG intact, copie à l'identique) est relue et comparée à l'original.

### 13.1 bis Option « Remplacer les originaux » (`pipeline._replace_original`)

Seule exception volontaire au principe « les originaux ne sont jamais réécrits ». Elle sert à libérer de la place et n'est active qu'après une case cochée et une confirmation explicite.

| Situation | Effet sur le disque |
| --- | --- |
| Rendu dans le même format (JPEG → JPEG, PNG → PNG, TIFF → TIFF) | Le rendu est écrit dans un fichier temporaire du même dossier, `fsync`, puis `os.replace` remplace l'original sous **le même nom**, de façon atomique |
| Rendu dans un autre format (RAW → JPEG, JPEG → TIFF…) | Le nom `<nom>.<nouvelle ext>` est réservé par `O_CREAT \| O_EXCL`, le rendu y est publié, **puis** l'original est supprimé (`unlink`). Si ce nom existe déjà (par exemple le JPEG de boîtier d'une paire RAW + JPEG), le nom devient `<nom>_Atelier_001.<ext>` |
| RAW exporté en RAW + XMP | Le RAW n'est **pas** modifié. Seul `<nom>.xmp` est écrit (ou un `<nom>.XMP` existant, casse exacte conservée), et remplace un XMP précédent |
| Photo sans retouche, ou RAW sans réglage | Rien n'est écrit |
| Copie à l'identique | Refusée : elle ne peut rien remplacer |

- **Ordre des opérations.** L'original n'est supprimé qu'après l'écriture complète et forcée sur le disque du résultat. Si le rendu échoue, le fichier réservé est retiré et l'original reste intact. Une coupure laisse donc l'original, le résultat, ou les deux, jamais aucun.
- **Suppression définitive.** Elle ne passe pas par la corbeille, puisque le but est de libérer de la place. Le dossier de destination n'est pas demandé et n'est pas utilisé.
- **Après l'export.** Chaque photo dont le fichier a changé reçoit `replaced = <chemin du résultat>` dans la base. `export_job` refuse ensuite d'exporter ce lot : les retouches seraient appliquées une seconde fois. Les aperçus restent ceux de l'import, conservés dans la bibliothèque privée.
- **Reprise.** Si une coupure survient juste après un remplacement, avant l'enregistrement de la progression, la reprise trouve un original absent ou modifié. Elle le signale comme erreur pour cette photo et continue avec les suivantes.
- **Photos non concernées.** Les photos écartées et à vérifier ne sont jamais touchées.

### 13.2 Formats

| Format | Contenu |
| --- | --- |
| JPEG | Rendu complet, aux dimensions du cadrage, sans agrandissement. Profil sRGB intégré, EXIF photographiques conservés, sous-échantillonnage 4:4:4. Trois qualités, détaillées ci-dessous. |
| PNG | Rendu complet en sRGB 8 bits, compression sans perte des pixels rendus |
| TIFF 16 bits | Développement 16 bits complet, RVB non compressé (bandes de 128 lignes), profil sRGB ; pas de passage par 8 bits |
| RAW + XMP si nécessaire | RAW copié **à l'identique**. Un XMP est ajouté s'il y a une correction globale, un cadrage, un outil avancé ou une retouche par consigne (§ 14.1). Un JPEG ou un PNG source est exporté en JPEG. |
| Copie à l'identique | Octets de la source et XMP voisins copiés, sans aucune retouche |

Les trois qualités JPEG :
- **Maximale.** Qualité 100. Un JPEG source sans aucune retouche est copié intact.
- **Selon le JPEG source.** Reprend les tables de quantification et le sous-échantillonnage du JPEG d'origine.
- **Personnalisée.** De 1 à 100.

Le **filtre couleur du lot** (§ 7.3) est appliqué aux rendus JPEG, PNG et TIFF. Il ne peut pas être décrit dans un XMP.

## 14. XMP

### 14.1 XMP écrit à l'export RAW (`xmp.sidecar`, `lightroom.py`)

- **Réglages globaux.**

  | Champ | Valeur |
  | --- | --- |
  | `crs:Exposure2012` | En IL |
  | `crs:Contrast2012` | Contraste × 200 |
  | `crs:Saturation` | Saturation × 100 |
  | `crs:WhiteBalance` | « As Shot » : la balance du boîtier est conservée, car la température absolue n'est pas connue sans elle |

- **Recadrage.** `crs:HasCrop` et `crs:CropLeft`, `CropTop`, `CropRight`, `CropBottom`, convertis dans l'orientation du capteur selon l'indicateur de rotation LibRaw.
- **Outils avancés.**
  - `crs:Clarity2012`.
  - `crs:ParametricShadows`, `ParametricDarks`, `ParametricLights`, `ParametricHighlights`.
  - `crs:HueAdjustment…`, `SaturationAdjustment…` et `LuminanceAdjustment…` pour Red, Orange, Yellow, Green, Aqua, Blue, Purple et Magenta.
  - `crs:ToneCurvePV2012`, avec ses variantes Red, Green et Blue, s'il y a une courbe par points.
- **Retouches par consigne.** Elles deviennent `crs:MaskGroupBasedCorrections`, pour Lightroom 11 et Camera Raw 14 ou plus récents.

  | Zone | Masque Lightroom |
  | --- | --- |
  | Position | Dégradé linéaire, aux mêmes points |
  | Centre, bords | Dégradé radial (inversé pour les bords) |
  | Tons | Plage de luminance, aux mêmes seuils |
  | Couleurs, peau | Plage de couleurs, la couleur étant échantillonnée sur la photo développée |
  | Ciel, sujet | Masques IA de Lightroom, recalculés par Lightroom |
  | Fond | Masque IA du sujet, inversé |

  - **Plusieurs zones** : intersection. **« sauf »** : inversion ; pour plusieurs zones, réunion des zones inversées.
  - **Valeurs locales.** Exposition en quarts d'IL ; contraste / 0,5 ; température × 0,4 ; saturation, clarté et teinte inchangées.
- **Valeurs Atelier.** Les valeurs exactes d'Atelier sont aussi écrites dans un espace de noms propre (`atelier:`). Rien n'est perdu si un logiciel ignore `crs`.
- **Limite.** Adobe ne documente pas les masques. Le format suit des descriptions publiques et n'a pas été vérifié dans Lightroom : faites le premier essai sur une copie du catalogue. Lightroom refait le rendu avec son propre moteur.

### 14.2 XMP lu pour une référence (`xmp.read_settings`, `xmp.development`)

- **Lecture.** Les attributs et éléments `crs:` et `atelier:` de la description principale sont lus (16 Mio au plus). Les blocs imbriqués (profil « Look », masques, retouches) sont retirés avant lecture, pour qu'aucun réglage d'un masque ou d'un profil ne soit pris pour un réglage global.
- **Correspondances.**

  | Réglage du XMP | Effet dans Atelier |
  | --- | --- |
  | Exposition | `Exposure2012` en IL (ou `Exposure`) |
  | Contraste | `Contrast2012` / 200 |
  | Saturation | `Saturation` / 100 + `Vibrance` / 200 |
  | Noir et blanc | `ConvertToGrayscale` donne une saturation de −1 |
  | Température d'un JPEG | `IncrementalTemperature` / 40 |
  | Température d'un RAW | Calculée relativement à la balance du boîtier, voir ci-dessous |
  | Hautes lumières, ombres, blancs, noirs | Courbe de luminance approchée |
  | Clarté, courbes paramétriques et par points, TSL | Repris exactement par les outils du § 10 |
  | Recadrage | Ramené à l'orientation affichée |
  | XMP écrit par Atelier | Valeurs relues exactement |

- **Température d'un RAW.**
  1. La température de la balance du boîtier est estimée à partir des coefficients de balance et de la matrice couleur du boîtier fournis par LibRaw, puis de la chromaticité xy et de la formule de McCamy.
  2. On calcule l'écart en mireds entre la température Lightroom et celle du boîtier.
  3. Cet écart est appliqué à partir de 6 500 K, le neutre d'Atelier.
- **Réglages ignorés.** Texture, correction du voile, teinte (tint) et retouches locales sont signalés comme ignorés. L'historique d'un XMP darktable n'est pas lisible ; la photo compte alors comme RAW seul.

## 15. Tâches, pause et reprise

- **États.** Une tâche est « en attente », « en cours », « suspendue », « échouée », « terminée » ou « remplacée ».
- **Curseur.** Le curseur, c'est-à-dire l'index du prochain fichier, est enregistré après chaque fichier.
- **Suspension.** Elle termine le fichier en cours. La reprise repart du curseur, et ce qui est déjà analysé ou mis en cache est réutilisé.
- **Analyse interrompue.** Les photos déjà analysées sont triées provisoirement et le lot affiche « Import incomplet ».
- **Exclusions.** Tant qu'une analyse, un tri ou un export n'est pas terminé, il est impossible de valider le lot ou de changer sa sélectivité.
- **Erreurs disque.** Une erreur de disque ou de permission rend la tâche reprenable sans perte. Une photo illisible est notée en erreur sans arrêter la tâche.
- **Durée restante.** Elle est estimée sur les 30 derniers fichiers, après au moins 3 fichiers et 5 secondes.

## 16. Photos endommagées et récupération (`pipeline.quarantine`, `recovery.py`, `cr2.py`)

- **Mise à l'écart.** Un fichier endommagé (§ 3) est lu entièrement, pour distinguer un disque illisible, puis **déplacé** sur le même volume dans `Photos corrompues`, avec son XMP. Un nom existant n'est jamais écrasé. Si le dossier est en lecture seule, la photo est seulement exclue. Elle est retirée du reportage ou du groupe de références concerné, et la tâche continue.
- **Récupération.** « Tâches → Récupérer les photos corrompues » écrit des **copies** `<nom>-recuperee.<ext>` dans le dossier choisi.

  | Fichier | Méthode de récupération |
  | --- | --- |
  | RAW | Aperçu JPEG intégré par le boîtier, conservé octet pour octet. Pour un CR2, l'aperçu est lu dans sa structure. Sinon `extract_thumb` de LibRaw, sans décoder les données du capteur. |
  | JPEG tronqué | Ajout du marqueur de fin et relecture des lignes intactes |
  | PNG | Conservation des seuls blocs d'image dont le CRC est valide |

  Une copie identique déjà présente est réutilisée.

## 17. Données, confidentialité et suppression

- **Bibliothèque locale.** Les profils, lots, aperçus, vecteurs et corrections restent dans la bibliothèque locale. Les photos sources et les exports restent dans vos dossiers.
- **Supprimer un lot.** Son dossier de cache est renommé d'abord, pour qu'une erreur ne laisse pas d'enregistrement orphelin, puis il est supprimé. Les corrections déjà apprises sont conservées.
- **Supprimer un profil ou repartir de zéro.** Tous ses enregistrements et dossiers sont effacés. La base est compactée (`VACUUM`) et `secure_delete` réécrit les pages libérées.
- **Distribution.** La préparation d'une version (`scripts/distribution_assets.py`) refuse tout fichier non autorisé dans `atelier/assets`. Elle vérifie aussi que le profil fourni ne contient que des paramètres numériques, sans nom de fichier ni métadonnée d'apprentissage.

## 18. Autodiagnostic

`AtelierPhoto --self-test <rapport.json>` (`diagnostics.py`) crée des photos de test dans un dossier temporaire et exerce toute la chaîne avec les vrais processus :
- deux reportages, un groupe de références, une analyse, une correction validée et un export ;
- l'aperçu Qt et la suppression d'un lot.

Il vérifie que les originaux sont intacts et, sous Windows, que le moteur DINOv3 ne s'est pas inscrit à la télémétrie. Le rapport est écrit en JSON.

## 19. Dépendances et compilation

- **Versions.** Python 3.12 à 3.14. Versions exactes testées (`requirements-tested.txt`) :

  | Bibliothèque | Version |
  | --- | --- |
  | numpy | 2.5.3 |
  | Pillow | 12.3.0 |
  | tifffile | 2026.11.16 |
  | PySide6 | 6.11.2 |
  | rawpy (LibRaw) | 0.27.1 |
  | onnxruntime | 1.30.0 |

  Les licences sont dans `THIRD_PARTY_NOTICES.md` et `atelier/assets/`.
- **Compilation.** Elle produit une application autonome par pyside6-deploy et Nuitka (`scripts/build_release.py`), avec un installeur Inno Setup sous Windows et un `.app` signé ad hoc dans un DMG sous macOS.

## 20. Limites connues

- **Tri.** Il juge le contenu, la netteté, l'exposition et la scène. Il ne juge **pas** les expressions ni les yeux fermés.
- **Valeurs approchées.**
  - Les masques sujet, fond et peau sont des estimations par couleur, netteté et position, sans modèle de détourage.
  - Le développement d'un XMP de référence ne reproduit pas exactement Lightroom.
  - Le rendu d'un XMP avec masques dans Lightroom diffère de l'aperçu d'Atelier.
- **Temps de calcul.** Pour une photo de 24 Mpx sur un processeur de bureau, il faut compter environ 1,3 s pour le rendu de base, environ 8 s avec clarté, courbe et TSL, et 2 à 5 s par retouche par consigne.

## 21. Vérifier soi-même

- **Tests.** Ils couvrent le décodage, l'analyse, le tri, l'apprentissage, le rendu, chaque format d'export, le XMP, les masques, les retouches par consigne, la récupération, la confidentialité de la distribution et l'interface. Pour les lancer depuis le dossier du projet :

  ```
  python -m pytest
  ```

- **Seuils et formules.** Toutes les constantes citées dans ce document sont dans le code source, avec le nom du module indiqué dans chaque section.
"""
