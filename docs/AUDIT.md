# Vérifications de la version 0.2 — 5 octobre 2026

## Lots et apprentissage

Le bouton **Supprimer le lot sélectionné** retire le lot, ses photos internes,
ses tâches et ses aperçus après confirmation. Il ne supprime ni les fichiers
sources ni les exports. Les corrections validées appartiennent au profil et
survivent à la suppression du lot ; les corrections non validées sont perdues.
Une tâche active doit être suspendue avant suppression.

La migration SQLite v1 → v2 détache la mémoire des photos transitoires, relie les
tâches aux lots et ajoute des index. Elle est transactionnelle. Une copie de la
bibliothèque utilisateur a été migrée avec conservation des 659 références,
2 lots, 38 photos, 2 corrections et 4 tâches ; contrôle des clés étrangères réussi.
La bibliothèque originale n’a pas été modifiée par ce contrôle.

La validation vérifie que le lot appartient au profil sélectionné. Elle mémorise
les changements explicites de décision et de retouche, puis augmente la version
du profil si la mémoire change. Les lots suivants en bénéficient pour les images
visuellement proches ; les instantanés précédents restent intacts. Valider une
proposition sans modification ne la transforme pas en référence. Le compteur
du profil et le message de validation rendent ce comportement visible.

## Vérifications du code

- 30 tests passés : suppression, confirmation et annulation dans l’interface,
  migration, profils indépendants, apprentissage persistant, effets sur les lots
  suivants, revalidation idempotente, absence d’auto-apprentissage, caches verrouillés,
  erreurs d’import/export, disque plein et conservation des originaux.
- Analyse Ruff réussie (imports, erreurs Python, pièges courants et exceptions).
- Audit `pip-audit` des 10 dépendances d’exécution épinglées dans
  `requirements-tested.txt` : aucune vulnérabilité connue signalée à cette date.
  Rapport : `test-output/dependency-audit.json`. Ce contrôle n’est pas une garantie
  d’absence de défauts dans le code ou les bibliothèques natives.
- Erreurs SQLite de suppression et validation affichées dans l’interface.
  Reprise des traitements interrompus après acquisition du verrou d’application.
- Diagnostic réussi directement dans le binaire Windows 0.2 : vrai CLIP local,
  3 références, 3 analyses, 3 exports, processus `spawn`, aperçu Qt, originaux
  inchangés, suppression du lot et conservation des corrections validées.
  Rapport : `test-output/packaged-0.2.0.json`.

## Allègement

Les modifications multi-sélection sont enregistrées en une seule transaction.
L’affichage du profil ne charge plus les vecteurs CLIP des références. Le dialogue
des références conserve des vignettes réduites. Les tâches d’export ne dupliquent
plus les caractéristiques et embeddings de chaque photo ; les checkpoints
d’analyse n’enregistrent plus la liste complète des chemins à chaque fichier.
SQLite réutilise ses pages libres sans `VACUUM` à chaque suppression de lot.

La distribution exclut les outils ONNX de conversion/quantification, les tests
Python et les plugins Qt de clavier virtuel et TLS inutilisés. Les DLL nécessaires
et le modèle CLIP quantifié de 89 Mo sont conservés pour le fonctionnement local.

Mesures Windows, notices incluses :

| Distribution | Version 0.1 | Version 0.2 |
| --- | ---: | ---: |
| Dossier portable | 320 706 189 octets | 273 309 398 octets |
| Installateur | 124 798 369 octets | 114 758 548 octets |

Réduction du dossier portable : 14,78 %. Installateur final :
`dist/AtelierPhoto-0.2.0-Windows-x64-Setup.exe`. SHA-256 :
`3fd6f782e224d3986ae87d5b09ed041e8696fe3ca708f97a0149a6fecf156dee`.
Ces mesures concernent une nouvelle distribution ; une installation précédente
peut encore contenir des bibliothèques devenues inutiles.

## Licences et distribution

Les textes LGPLv3/GPLv3 et les notices des paquets, de Python, de LibRaw et de CLIP
sont fournis avec la distribution. Les bibliothèques Qt restent partagées et
remplaçables. Les références officielles et les sources correspondant à Qt/PySide6
6.11.2 figurent dans `THIRD_PARTY_NOTICES.md`.

Références consultées : [licences Qt for Python](https://doc.qt.io/qtforpython-6/licenses.html),
[obligations LGPL/GPL décrites par Qt](https://www.qt.io/development/open-source-lgpl-obligations),
[licence commerciale du compilateur Inno Setup](https://jrsoftware.org/isorder.php).
Le compilateur Inno préparé ici utilise son régime non commercial.

La version Windows est compilée et testée localement. Les binaires ne disposent
pas d’une signature éditeur. La compilation et l'installation par DMG sur un Mac
réel restent à vérifier ; les scripts et la CI sont fournis. La signature Developer ID
et la notarisation Mac ont été retirées à la demande de l'utilisateur ; seule
l'empreinte ad hoc requise pour exécuter du code arm64 est conservée automatiquement.
La qualité photographique doit encore être mesurée sur un corpus annoté distinct
des références, comme expliqué dans `VALIDATION.md`.

La vérification Mac complémentaire figure dans `MACOS.md` : cible corrigée en
macOS 15+ Apple Silicon après inspection des dépendances natives ; scripts de
distribution corrigés et 40 tests réussis, 1 ignoré sur Windows. Les essais sur
Mac réel restent à effectuer.
