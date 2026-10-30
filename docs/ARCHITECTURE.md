# Architecture

`atelier.app` gère l’interface Qt, un modèle de galerie à chargement différé et un
cache de 160 icônes maximum. L’état visible vient de SQLite ; les fichiers sources
ne sont jamais utilisés comme emplacement de sauvegarde d’une retouche.

`atelier.store` conserve profils, références, lots, photos, corrections et tâches.
Les instantanés de profil sont figés à la création du lot. Les corrections explicites
sont indexées par profil et photo, ce qui rend la validation répétée idempotente.
La bibliothèque possède un verrou d’instance au démarrage de l’application.

`atelier.pipeline` traite les tâches dans un processus `spawn` : une photo à la
fois, checkpoint après chaque fichier. La suspension est coopérative. Le moteur
de preview utilise un autre processus et ignore les requêtes obsolètes. Qt n’attend
pas le décodage ou l’inférence dans son thread principal.

`atelier.imaging` gère le développement RAW, l’orientation, les profils sRGB, les
mesures techniques et le rendu par bandes. Une recette et des statistiques de
style fixes produisent la même transformation ponctuelle à toute résolution.

`atelier.dino` vérifie le graphe ONNX et ses poids externes via `atelier.model_assets`
et exécute DINOv3 Small ViT-S/16 sur CPU. L’image RGB entière est redimensionnée
en 448 × 448 par interpolation bilinéaire, normalisée avec les statistiques
ImageNet ; `pooler_output` fournit le CLS de 384 dimensions, ensuite normalisé L2.
La version de l’encodeur inclut la résolution, le prétraitement et les deux empreintes.
Les corrections mémorisées sont filtrées par cette version ; les modèles de sélection
incompatibles sont ignorés et les lots interrompus incompatibles refusés. Le runtime
ne contient aucune logique de téléchargement. `atelier.analysis` fait la proposition
par photo (verdict technique, corrections passées, courbe du filtre) puis, en fin de
lot, la décision par scène (`finalize`).

`atelier.selection` découpe le rush en scènes et entraîne / applique le modèle de
sélection (régression logistique numpy). `atelier.look` apprend et applique le
filtre (table couleur 3D + courbe de tonalité par photo). `atelier.training` relie
les photos livrées à leur original et construit le modèle du profil à partir des
reportages triés (table SQLite `training`, échantillons 48 px dans le dossier privé
du profil). Voir `docs/SELECTION.md`.

## État d’une photo

- Empreinte source, caractéristiques techniques et embedding DINOv3 normalisé.
- Proposition initiale, décision utilisateur, motifs et groupe de variantes.
- Recette initiale, recette courante, statistiques de style et marque de validation.
- Ou erreur de lecture explicite ; une erreur ne peut pas être exportée.

## Garanties d’export

L’export exige une validation, vérifie que l’original n’a pas changé, réserve un
nom par création exclusive, écrit un fichier temporaire sur le même volume puis
le publie par remplacement atomique de sa propre réservation. Le source n’est
jamais ouvert en écriture. Les erreurs d’espace et de permission laissent la tâche
reprenable. Après coupure au moment précis du checkpoint, une copie supplémentaire
peut être créée, mais jamais un écrasement de fichier existant.

## Reproduction

`pytest` vérifie les invariants avec images synthétiques et doubles d’encodeur.
Le test DINOv3 et `scripts/smoke_desktop.py` utilisent le vrai modèle.
`scripts/benchmark_local.py` mesure 200 références / 1 000 images synthétiques.
`--self-test rapport.json` teste aussi les processus et Qt dans le binaire compilé.
`scripts/check_raw_sample.py chemin.raw` vérifie développement et export d’un RAW.
