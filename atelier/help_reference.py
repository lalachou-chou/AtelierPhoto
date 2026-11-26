"""Référence technique complète d'Atelier Photo (Markdown).

Affichée dans l'onglet « Aide avancée » et copiée à l'identique dans
``docs/FONCTIONNEMENT_DETAILLE.md`` (un test vérifie que les deux sont égaux).
Chaque valeur citée ici provient du code ; le nom du module est indiqué pour
permettre de la vérifier.
"""

REFERENCE = r"""# Atelier Photo — fonctionnement détaillé

Ce document décrit ce que fait Atelier Photo, comment et avec quelles valeurs. Il s'adresse à toute personne qui veut vérifier le logiciel plutôt que lui faire confiance. Les modules cités sont dans le dossier `atelier/` du code source, les tests dans `tests/`.

## 1. Principes et garanties

- **Atelier trie, il ne retouche pas.** Il propose pour chaque photo une décision : retenue, à vérifier ou écartée. Il ne modifie, ne recadre et ne réencode aucune image.
- **Tout est local.** L'analyse, l'apprentissage, le tri et l'export s'exécutent sur l'ordinateur. Aucune fonction de l'application n'envoie de photo, de vecteur, de réglage ou de statistique sur un réseau. Le seul téléchargement du projet est celui du modèle DINOv3, fait par `scripts/download_model.py` au moment de la préparation du logiciel, jamais à l'exécution.
- **Pas de télémétrie.** Avant d'initialiser le moteur ONNX Runtime 1.30.0, `local_runtime.py` positionne `ORT_DISABLE_TELEMETRY=1`. Sous Windows, il positionne aussi `ORT_RUNNING_UNIT_TESTS=1`, pour que le moteur ne s'inscrive pas au fournisseur de télémétrie `Microsoft.ML.ONNXRuntime`, puis il appelle `disable_telemetry_events()`. L'autodiagnostic (§ 13) vérifie sous Windows que le processus n'est pas inscrit.
- **Les originaux ne sont jamais réécrits.** L'export crée des copies identiques dans un autre dossier. Avant chaque copie, l'empreinte SHA-256 de la source est comparée à celle mesurée à l'analyse ; si elle diffère, l'export est refusé (« L'original a changé depuis son analyse »). Chaque copie est relue et son empreinte comparée à l'original.
  Exception : un fichier reconnu comme **endommagé** est **déplacé**, sans être modifié, dans un sous-dossier `Photos corrompues` à côté de lui (§ 11).
- **Déterminisme.** Pour un même fichier, un même profil et une même version du modèle, l'analyse donne le même résultat. Il n'y a pas de tirage aléatoire dans le tri.

## 2. Architecture et processus

- **Interface.** Elle utilise Qt (PySide6) et s'exécute dans le processus principal (`app.py`, `workspace_ui.py`, `training_dialog.py`, `task_dialog.py`, `recovery_dialog.py`, `help_ui.py`).
- **Tâches longues.** L'analyse, l'apprentissage, le tri, l'export et la récupération s'exécutent chacune dans **un processus séparé**, lancé en mode `spawn` (`pipeline.run_job`). L'interface reste fluide et une erreur du moteur ne peut pas la faire tomber. Une seule tâche tourne à la fois.
- **Préparation parallèle.** Dans ce processus, deux fils préparent les photos à l'avance (décodage, mesures, vecteur DINOv3), au plus deux photos devant la photo en cours. Les écritures en base restent ordonnées.
- **Aperçus.** L'aperçu et la vue agrandie affichent la copie d'analyse de la photo : aucun rendu n'est calculé.
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
  - `profiles/<profil>/batches/<lot>/<photo>.png` : copie d'analyse et d'aperçu, 1 280 px au plus.
  - `profiles/<profil>/batches/<lot>/<photo>.jpg` : vignette, 240 × 180 px au plus, qualité 85.
  - `profiles/<profil>/references/<référence>.png` : copie d'analyse d'une référence.
- **Noms internes.** Les noms de fichiers internes sont des identifiants générés (UUID). Un nom de photo n'est jamais utilisé comme chemin interne, et tout chemin interne est vérifié comme étant à l'intérieur de `profiles/`.
- **Schéma de base.** Le schéma est versionné (`PRAGMA user_version = 8`, `store.py`). Une bibliothèque d'un autre schéma est refusée plutôt que convertie. Une bibliothèque créée par une version qui retouchait s'ouvre : ses réglages de retouche et de cadrage sont ignorés.
- **Démarrage.** Le verrou est pris. Les tâches restées « en cours » après un arrêt brutal passent à « suspendue » (`recover_interrupted_jobs`).
- **Windows.** Un mutex nommé (`AtelierPhoto.Application.03D9A7F4`) signale à l'installeur que l'application est ouverte.

### Tables de la base

| Table | Contenu |
| --- | --- |
| `profiles` | Nom, numéro de version (incrémenté à chaque changement d'apprentissage) et modèle appris (JSON) |
| `reportages`, `training` | Reportages d'apprentissage et, pour chaque photo, statistiques, vecteur, date et rôle (rush ou retenue) |
| `reference_groups`, `reference_members`, `refs` | Groupes de références, appartenance et données de chaque référence (dédoublonnée par empreinte) |
| `batches` | Lots importés, avec un **instantané figé** du profil au moment de l'import, et la sélectivité |
| `photos` | Une ligne par photo d'un lot : chemin et données JSON (mesures, vecteur, score, scène, décision) |
| `feedback` | Décisions corrigées et validées, qui servent à l'apprentissage à l'usage (§ 8) |
| `jobs` | Tâches avec type, contenu, curseur, état et erreur |
| `quarantine` | Photos mises à l'écart, résultat et erreur de récupération |

## 3. Formats et décodage (`imaging.decode`, `config.py`)

Chaque photo, retenue d'un reportage ou référence est décodée une seule fois en **copie d'analyse** : 8 bits par canal, sRGB, orientée, 1 280 px au plus sur le grand côté (Lanczos). Le fichier d'origine n'est jamais décodé en pleine définition.

- **Extensions acceptées.**
  - RAW : `.arw .cr2 .cr3 .nef .nrw .dng .raf .orf .rw2 .pef .srw .3fr .iiq .rwl .x3f`.
  - Images : `.jpg .jpeg .png`.
- **Parcours d'un dossier.** Il est récursif. Les fichiers cachés (dont `._*` de macOS) et le sous-dossier `Photos corrompues` sont ignorés.
- **RAW** (LibRaw via `rawpy`).
  - Développement : `postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=16, output_color=sRGB, gamma=(2.4, 12.92))`, c'est-à-dire la balance du boîtier, aucune luminosité automatique, 16 bits par canal et la courbe sRGB.
  - `half_size=True` donne une image demi-taille, réduite ensuite à 8 bits puis à 1 280 px au plus.
- **JPEG et PNG.**
  - L'orientation EXIF est appliquée.
  - Un profil ICC intégré est converti en sRGB (LittleCMS via Pillow).
  - La transparence est composée sur fond blanc.
  - Un JPEG est décodé en mode brouillon à environ 1 600 px puis réduit à 1 280 px.
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
   | `sharpness` | Quantile 80 % des variances du laplacien sur une grille de 4 × 4 tuiles |
   | `peak` | Variance du laplacien de la tuile la plus nette |
   | `noise` | Médiane de l'écart à un filtre médian 3 × 3, sur les 35 % de pixels les plus plats |
   | `black` | Proportion de pixels sous 1,5 % de luminance |
   | `white` | Proportion de pixels au-dessus de 98,5 % de luminance |

4. **Vecteur de contenu DINOv3.**
   - Modèle : DINOv3 ViT-S/16, dépôt `onnx-community/dinov3-vits16-pretrain-lvd1689m-ONNX`, format ONNX float32.
   - Entrée : l'image est redimensionnée en 448 × 448 (bilinéaire) et normalisée avec les moyennes et écarts-types ImageNet (0,485 0,456 0,406 / 0,229 0,224 0,225).
   - Sortie : `pooler_output`, un vecteur de 384 dimensions, normalisé à la norme 1.
   - Exécution : sur le processeur seul (`CPUExecutionProvider`), avec 2 fils intra-opération et 1 inter-opération, sans profilage.
   - **Comparaison :** la ressemblance entre deux photos est le produit scalaire de leurs vecteurs, entre −1 et 1.
   - **Intégrité :** `model_assets.verify_model` compare l'empreinte SHA-256 du graphe et des poids à celles du manifeste `model.json` avant tout chargement. La version de l'encodeur (nom, prétraitement, empreintes) est enregistrée avec chaque vecteur. Des vecteurs d'une autre version ne sont jamais mélangés : un lot créé avec un modèle exige ce modèle.
5. **Copies privées.** Atelier enregistre une copie d'analyse en PNG (compression rapide), qui sert aussi d'aperçu, et une vignette JPEG.

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

### 5.2 Voisins

- **Photo « proche ».** Une photo est proche d'une autre quand leur ressemblance DINOv3 dépasse **0,82**. On ne garde que les 8 plus proches.
- **Ressemblance aux références.** C'est la moyenne des ressemblances aux 3 références actives les plus proches. Elle sert au § 5.1 et au score du § 6.
- **Préférence.** Les corrections validées sur des photos proches votent : +1 pour une photo retenue, −1 pour une photo écartée. La moyenne de ces votes entre dans le score du § 6.

## 6. Tri par scène (`analysis.finalize`, `selection.py`)

Ce tri est fait automatiquement à la fin de chaque import, sur tout le lot.

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
7. **Variantes.** Les photos d'une même scène forment un **groupe de variantes**, identifié par sa meilleure photo. La galerie permet d'isoler un groupe et d'y garder une seule photo.
8. **Raison affichée.** Chaque photo reçoit sa raison : meilleure image de la scène, variante, moment secondaire, doublon, remarques techniques, modèle de sélection utilisé. Avec des références actives, une photo dont la ressemblance atteint 0,82 est signalée « Proche de vos références ».
9. **Changement de sélectivité.** Il relance seulement cette étape (`reselect`) à partir des mesures en cache. Les décisions manuelles sont conservées. La nouvelle sélectivité, les décisions et l'état de la tâche sont écrits ensemble dans une seule transaction.

## 7. Apprentissage du profil (`training.py`, `pipeline.py`)

### 7.1 Reportages déjà triés

- **Contenu.** Un reportage est un dossier de rush complet plus un dossier de photos retenues, retouchées ou non (seule la correspondance compte). Un sous-dossier de retenues placé dans le rush est exclu du rush.
- **Exigences.** Le rush doit contenir des photos écartées. Pour apprendre le tri, il faut au moins **6 photos dont 2 retenues** ; un reportage complet de plusieurs centaines de photos est préférable.
- **Correspondance retenue → original** (`training.match`). On essaie, dans l'ordre :
  - le même chemin ;
  - le même nom, sans casse ni ponctuation (`DSC08947 N&B.jpg` → `DSC08947.JPG`) ;
  - un nom préfixe d'au moins 4 caractères qui n'est pas suivi d'un chiffre ;
  - sinon, la ressemblance visuelle, à condition qu'elle dépasse **0,90** et devance la deuxième candidate d'au moins **0,02**.
  - Faute de correspondance certaine, la photo est ignorée et signalée. Un reportage sans aucune correspondance est exclu, sinon il apprendrait à tout écarter.
- **Modèle de tri.** C'est la régression logistique décrite au § 6, apprise sur toutes les photos des reportages cochés (retenue = 1, écartée = 0). Son taux de rétention est mémorisé.

### 7.2 Références (photos exemples sans rush)

- **Rôle.** Une référence montre le type de photo que vous gardez. Atelier en mémorise le vecteur DINOv3 et les mesures techniques ; RAW, JPEG et PNG sont traités de la même façon et un XMP voisin n'est pas lu.
- **Effet sur le tri.** Voir § 5.1 (photo éloignée des références à vérifier, sans modèle appris) et § 6 (ressemblance ajoutée au score, y compris pour choisir la meilleure variante d'une scène).
- **Dédoublonnage.** Les références sont dédoublonnées par empreinte. Une photo présente dans deux groupes n'est analysée qu'une fois.
- **Profil fourni.** Il contient seulement un modèle de tri. Un profil neuf l'utilise jusqu'à ce que ses propres reportages le remplacent.

### 7.3 Publication et figement

- **Publication.** Le modèle appris est publié en une seule transaction, avec l'état de la tâche ; le numéro de version du profil augmente.
- **Instantané figé.** Chaque lot conserve l'instantané du profil pris à son import. Un apprentissage ultérieur ne modifie donc jamais un lot déjà importé.

## 8. Apprentissage à l'usage : corrections validées (`store.validate`)

- **Quand.** Rien n'est appris pendant le tri. À la **validation du lot**, par le bouton « Valider le lot » ou par l'export, qui exige la validation, chaque photo dont la décision a été **changée à la main** enregistre une ligne de `feedback` : la décision et le vecteur DINOv3. Accepter une proposition n'ajoute rien.
- **Revalidation.** Elle est idempotente. Une correction annulée puis revalidée retire la ligne correspondante.
- **Au prochain import.** Ces corrections influencent les photos dont la ressemblance dépasse 0,82 (§ 5.1 et § 5.2).
- **Effacer.** « Effacer les corrections apprises » supprime toutes les lignes `feedback` du profil. Les reportages, les références et les lots restent.

## 9. Export (`pipeline.export_one`)

- **Ce qui est exporté.** Uniquement les photos **retenues** d'un lot **validé**, dont l'analyse et le tri sont terminés. Les photos « à vérifier » et écartées ne sont pas copiées.
- **Contenu.** Une copie **à l'identique** des octets de la source, avec ses XMP voisins (`photo.xmp`, `photo.nef.xmp` ou `.XMP`), qui ne sont ni lus ni modifiés.
- **Nom du fichier.** Le nom d'origine ; s'il est pris dans le dossier, `<nom> (2).<ext>`, `<nom> (3).<ext>`… La photo et ses XMP gardent le même nom de base. Chaque nom est **réservé** par une création exclusive (`O_CREAT | O_EXCL`) : un fichier existant n'est jamais écrasé, même par deux exports simultanés.
- **Écriture.** Elle passe par un fichier temporaire du même dossier, forcé sur le disque (`fsync`), puis remplacé atomiquement (`os.replace`). Une interruption ne laisse jamais de fichier à moitié écrit sous le nom final.
- **Contrôles.** L'empreinte de l'original est revérifiée avant la copie, puis la copie est relue et comparée à l'original.

## 10. Tâches, pause et reprise

- **États.** Une tâche est « en attente », « en cours », « suspendue », « échouée », « terminée » ou « remplacée ».
- **Curseur.** Le curseur, c'est-à-dire l'index du prochain fichier, est enregistré après chaque fichier.
- **Suspension.** Elle termine le fichier en cours. La reprise repart du curseur, et ce qui est déjà analysé ou mis en cache est réutilisé.
- **Analyse interrompue.** Les photos déjà analysées sont triées provisoirement et le lot affiche « Import incomplet ».
- **Exclusions.** Tant qu'une analyse, un tri ou un export n'est pas terminé, il est impossible de valider le lot ou de changer sa sélectivité.
- **Erreurs disque.** Une erreur de disque ou de permission rend la tâche reprenable sans perte. Une photo illisible est notée en erreur sans arrêter la tâche.
- **Durée restante.** Elle est estimée sur les 30 derniers fichiers, après au moins 3 fichiers et 5 secondes.

## 11. Photos endommagées et récupération (`pipeline.quarantine`, `recovery.py`, `cr2.py`)

- **Mise à l'écart.** Un fichier endommagé (§ 3) est lu entièrement, pour distinguer un disque illisible, puis **déplacé** sur le même volume dans `Photos corrompues`, avec ses XMP (`photo.xmp`, `photo.nef.xmp`). Un nom existant n'est jamais écrasé. Si le dossier est en lecture seule, la photo est seulement exclue. Elle est retirée du reportage ou du groupe de références concerné, et la tâche continue.
- **Récupération.** « Tâches → Récupérer les photos corrompues » écrit des **copies** `<nom>-recuperee.<ext>` dans le dossier choisi.

  | Fichier | Méthode de récupération |
  | --- | --- |
  | RAW | Aperçu JPEG intégré par le boîtier, conservé octet pour octet. Pour un CR2, l'aperçu est lu dans sa structure. Sinon `extract_thumb` de LibRaw, sans décoder les données du capteur. |
  | JPEG tronqué | Ajout du marqueur de fin et relecture des lignes intactes |
  | PNG | Conservation des seuls blocs d'image dont le CRC est valide |

  Une copie identique déjà présente est réutilisée.

## 12. Données, confidentialité et suppression

- **Bibliothèque locale.** Les profils, lots, aperçus, vecteurs et corrections restent dans la bibliothèque locale. Les photos sources et les exports restent dans vos dossiers.
- **Supprimer un lot.** Son dossier de cache est renommé d'abord, pour qu'une erreur ne laisse pas d'enregistrement orphelin, puis il est supprimé. Les corrections déjà apprises sont conservées.
- **Supprimer un profil ou repartir de zéro.** Tous ses enregistrements et dossiers sont effacés. La base est compactée (`VACUUM`) et `secure_delete` réécrit les pages libérées.
- **Distribution.** La préparation d'une version (`scripts/distribution_assets.py`) refuse tout fichier non autorisé dans `atelier/assets`. Elle vérifie aussi que le profil fourni ne contient que des paramètres numériques, sans nom de fichier ni métadonnée d'apprentissage.

## 13. Autodiagnostic

`AtelierPhoto --self-test <rapport.json>` (`diagnostics.py`) crée des photos de test dans un dossier temporaire et exerce toute la chaîne avec les vrais processus :
- deux reportages, un groupe de références, une analyse avec tri automatique, une correction validée et un export ;
- l'aperçu Qt et la suppression d'un lot.

Il vérifie que les originaux sont intacts, que les copies exportées leur sont identiques et, sous Windows, que le moteur DINOv3 ne s'est pas inscrit à la télémétrie. Le rapport est écrit en JSON.

## 14. Dépendances et compilation

- **Versions.** Python 3.12 à 3.14. Versions exactes testées (`requirements-tested.txt`) :

  | Bibliothèque | Version |
  | --- | --- |
  | numpy | 2.5.3 |
  | Pillow | 12.3.0 |
  | PySide6 | 6.11.2 |
  | rawpy (LibRaw) | 0.27.1 |
  | onnxruntime | 1.30.0 |

  Les licences sont dans `THIRD_PARTY_NOTICES.md` et `atelier/assets/`.
- **Compilation.** Elle produit une application autonome par pyside6-deploy et Nuitka (`scripts/build_release.py`), avec un installeur Inno Setup sous Windows et un `.app` signé ad hoc dans un DMG sous macOS.

## 15. Limites connues

- **Tri.** Il juge le contenu, la netteté, l'exposition et la scène. Il ne juge **pas** les expressions ni les yeux fermés.
- **Scènes.** Le découpage repose sur la date de prise de vue. Sans EXIF, la date du fichier est utilisée ; des copies faites le même jour peuvent alors fusionner ou découper des scènes.
- **Références seules.** Sans reportage trié, les références montrent ce que vous aimez, pas ce que vous écartez. Elles ajustent le classement sans remplacer un modèle appris.

## 16. Vérifier soi-même

- **Tests.** Ils couvrent le décodage, l'analyse, le tri par scène et par variante, l'apprentissage, les références, l'export à l'identique, la récupération, la confidentialité de la distribution et l'interface. Pour les lancer depuis le dossier du projet :

  ```
  python -m pytest
  ```

- **Seuils et formules.** Toutes les constantes citées dans ce document sont dans le code source, avec le nom du module indiqué dans chaque section.
"""
