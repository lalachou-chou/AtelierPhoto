# Version Windows 0.3.1

L’import et l’apprentissage préparent deux photos en parallèle (lecture,
caractéristiques et CLIP), avec une seule session du modèle. La file d’attente
est limitée : elle ne charge pas le reportage entier en mémoire. Les écritures
dans la bibliothèque et les curseurs restent dans l’ordre des fichiers pour
préserver la suspension, la reprise et le traitement des erreurs.

La recherche dans les dossiers évite aussi de vérifier à nouveau le dossier
parent pour chaque fichier et ignore les extensions incompatibles avant de
consulter les métadonnées du fichier.

Mesure locale du 14 octobre 2026, avec `scripts/benchmark_workflows.py`, sur
24 JPEG synthétiques de 2400 × 1600 pixels et 8 copies retouchées, modèle CLIP
réel sur CPU, même jeu de fichiers avant/après :

| Opération | Avant | Après |
| --- | ---: | ---: |
| Apprendre un reportage | 6,87 s | 4,11 s |
| Importer/analyser le lot | 5,73 s | 3,31 s |

Ces mesures comprennent le chargement du modèle et les écritures locales.
Elles représentent un essai synthétique, pas une garantie de gain sur des RAW,
un disque externe ou une autre machine. Aucun abaissement de la résolution
d’analyse ou remplacement du modèle n’a été effectué.

Le bouton de filtre est placé au-dessus de la galerie : il agit sur toutes les
photos du lot courant, y compris celles masquées par les catégories, pour
l’aperçu et les exports. Réappliquer restaure les réglages conservés du lot.
« Gérer les références » est supprimé de l’interface ; les anciennes données
restent compatibles. Les nouveaux apprentissages passent par un reportage trié.
