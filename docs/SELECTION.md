# Sélection et filtre appris — version 0.3 (14 octobre 2026)

## Pourquoi la version 0.2 n’était pas performante

Mesure faite sur le mariage Carla & Ndue (29 novembre 2025) : 1 157 photos de rush
(Sony ILCE-6700), 184 photos livrées dont 179 issues du rush (5 en noir et blanc),
retouchées dans Luminar Neo. Le photographe garde 15,5 % du rush.

Avec les photos livrées comme références, la version 0.2 proposait **949 photos
« retenues » sur 1 157 (82 %)** et le reste « à vérifier » : aucune photo n’était
écartée. Sa précision (17 %) était celle du hasard. Elle jugeait chaque photo
isolément (netteté + ressemblance aux références), alors que le photographe garde
**une image par moment** : 156 des 367 rafales contiennent une photo gardée, presque
toujours une seule.

Son filtre (statistiques des références) éloignait la couleur de la retouche réelle :
ΔE moyen 7,81 contre 7,64 sans aucune retouche.

## Ce qui change

1. **Scènes.** Les photos sont triées par heure EXIF (au 1/1000 s) et découpées en
   moments : nouvelle scène après 20 s sans photo ou quand le contenu DINOv3 s’éloigne
   du centre de la scène (similarité < 0,80).
2. **Modèle de sélection appris.** Pour chaque photo : 8 mesures techniques, 8 mesures
   de contexte (taille de la scène, netteté relative à la plus nette de la scène,
   rang, centralité, durée) et les 384 dimensions DINOv3 Small en 448 × 448. Régression logistique L2
   (C = 0,02) entraînée sur les reportages triés du profil, en numpy pur.
3. **Décision par scène.** 70 % du budget : la meilleure photo des meilleures scènes ;
   le reste : d’autres photos bien notées seulement si elles diffèrent (cosinus DINOv3 < 0,93) de
   celles déjà retenues dans la scène. « À vérifier » : d’abord les meilleurs moments
   sans photo retenue, puis les variantes. Le budget suit le taux appris × 1,25 à 50 %
   de sélectivité (×2 en « Prudente », ×0,5 en « Exigeante »).
4. **Filtre appris.** Table couleur 3D 9×9×9 lissée, ajustée par moindres carrés sur
   les paires original / retouche de même cadrage, puis courbe de luminance à 9 points
   prédite pour chaque photo à partir de ses quantiles de tonalité (régression ridge).
   Les recadrages (corrélation des contours < 0,9) et le noir et blanc sont exclus.
5. Le profil par défaut (`atelier/assets/default_profile.json`) contient le modèle et
   le filtre appris sur ce mariage ; tout profil qui apprend ses propres reportages
   le remplace. Le sélecteur a été réentraîné avec le moteur DINOv3 448 ; le filtre
   couleur est conservé. Pour reproduire cet entraînement :
   `python scripts/train_default_selector.py chemin/dataset.json`
   (`paths` : originaux, `truth_indices` : indices des originaux retenus).

## Mesures

Les mesures ci-dessous sont historiques, obtenues avec CLIP avant la migration.
Elles ne mesurent pas la qualité de DINOv3 448. Les seuils de scène et de diversité
restent inchangés ; leur calibration avec DINOv3 exige une validation distincte.

Validation croisée par blocs chronologiques (5 blocs consécutifs) : le bloc évalué
n’est jamais vu pendant l’apprentissage. C’est l’estimation honnête du comportement
sur **un nouveau reportage**. Commande :
`python scripts/evaluate_profile.py RUSH RETENUES --cache features.npz`.

| Sélectivité 50 % | 0.2 | 0.3 (nouveau reportage) | Hasard, même volume |
| --- | ---: | ---: | ---: |
| Photos « retenues » | 949 (82 %) | 217 (19 %) | 217 |
| … identiques à celles du photographe | 159 | 51 | ≈ 34 |
| … ou image quasi identique du même moment¹ | — | 90 (50 % des 179) | ≈ 73 |
| Retenues + à vérifier | 1 157 | 450 | — |
| Couleur, ΔE moyen (plus bas = plus fidèle)² | 7,81 | **5,77** | 7,62 sans retouche |

¹ même scène, ≤ 15 s d’écart, similarité CLIP ≥ 0,92 (une autre image de la même rafale).
² 167 paires de même cadrage, rendu évalué sur des photos absentes de l’apprentissage.

Profil appris sur ce mariage puis appliqué à ce même rush (ce que l’on obtient en
repassant un reportage déjà appris) : 215 retenues, dont **122 identiques** (68 % des
photos gardées) et 142 du même moment (79 %) ; retenues + à vérifier contiennent
87 % des photos gardées.

## Limites et pistes

- Avec un seul reportage d’apprentissage, le modèle généralise modestement : la
  validation croisée retrouve la moitié des moments gardés, mais l’image exacte dans
  une rafale seulement une fois sur quatre. Chaque reportage trié ajouté au profil
  améliore la généralisation (contenus et lumières variés).
- Le choix entre images d’une rafale dépend surtout des expressions (yeux, sourires,
  regards). Un détecteur de visages / d’yeux ONNX embarqué serait l’amélioration
  suivante la plus utile ; aucun modèle sous licence compatible n’était disponible
  hors ligne pour cette version.
- Les retouches locales de Luminar (ciel, peau, structure) ne sont pas reproduites ;
  le filtre reproduit la couleur et la tonalité globales.
