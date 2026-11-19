# Retouche par consigne — fonctionnalités

Dans la vue agrandie, **Retoucher** : l'encadré **Retouche par consigne** est en tête du panneau, au-dessus des réglages globaux. On écrit en français ce qu'on veut changer. Atelier détecte la zone et y applique des réglages photographiques avec un bord progressif. Un texte sous le champ rappelle ce que fait la consigne.

**Aucun pixel n'est inventé.** Tout fonctionne sur le processeur, sans carte graphique ni connexion. L'aide intégrée (bouton **Exemples** et onglet **Retouche par consigne** de l'Aide) reprend cette liste.

**Qualité affichée.** Sous le champ, Atelier indique pour la photo affichée la définition exportée (par exemple « 6 000 × 4 000 px (24,0 Mpx), aucune réduction »), recadrage compris. Une consigne ne réduit jamais la photo : la zone est estimée sur une copie réduite, puis affinée à pleine résolution. La seule perte possible concerne un JPEG source exporté en JPEG : il est alors réencodé en qualité 100 au lieu d'être copié tel quel. Un avertissement le signale et propose PNG ou TIFF pour l'éviter. Un RAW exporté en RAW + XMP reste intact.

Code : `atelier/prompt.py` (compréhension des consignes) et `atelier/local.py` (zones et rendu). Tests : `tests/test_local_edits.py`.

## Zones

| Zone | Mots reconnus | Détection |
| --- | --- | --- |
| Ciel | ciel, nuages | Zone bleue ou claire, peu texturée, reliée au haut de l'image ; bord affiné pixel par pixel |
| Peau | peau, visage, teint, mains, bras, joues | Teintes chair (YCbCr), sur des régions cohérentes |
| Sujet (estimé) | sujet, personne, mariés, couple, enfant, bébé, premier plan | Couleur différente des bords, netteté, position centrale ; bord calé sur les contours (filtre guidé) |
| Fond (estimé) | fond, arrière-plan, décor | Inverse du sujet |
| Végétation | herbe, pelouse, feuillage, arbres, verdure, forêt | Plage des verts |
| Eau | mer, océan, lac, eau, rivière, piscine | Bleus et turquoises |
| Couleurs | les rouges, oranges, jaunes, verts, turquoises, bleus, violets, roses | Plage de teinte, pondérée par la saturation |
| Tons | ombres, zones sombres · tons moyens · hautes lumières, zones claires | Luminance |
| Position | en haut, en bas, à gauche, à droite, au centre, les bords, les coins | Dégradés doux, relatifs au cadre affiché |
| Toute l'image | image, photo, tout, partout, ou aucune zone | — |

- **Combinaison :** « débouche les ombres à gauche » agit sur ombres × côté gauche ; « peau moins rouge » sur peau × rouges.
- **Inversion :** « sauf » inverse la zone, par exemple « assombris tout sauf le sujet » ou « noir et blanc sauf la peau ».

## Réglages

| Réglage | Augmenter | Diminuer |
| --- | --- | --- |
| Lumière (±0,4 IL) | éclaircis, plus clair, lumineux, débouche, trop sombre, augmente l'exposition | assombris, fonce, plus sombre, trop clair, baisse les hautes lumières |
| Hautes lumières | — | trop blanc, brûlé, cramé, récupère les hautes lumières (limité automatiquement aux zones claires) |
| Température | réchauffe, plus chaud, trop froid, trop bleu | refroidis, plus froid, trop chaud, trop jaune, moins orange |
| Contraste (±15 %) | plus de contraste, plus de peps / relief, trop plat | moins de contraste, adoucis, plus doux, trop dur |
| Saturation (±30 %) | sature, plus vif, ravive, trop terne, fade | désature, moins vif, moins coloré, fluo, criard |
| Noir et blanc | — | noir et blanc, monochrome |
| Une couleur | plus vert, plus rose… | moins rouge, trop magenta… (cette couleur seulement) |
| Clarté (±30) | plus de clarté, plus de détails, plus net, fais ressortir les détails | lisse, adoucis la peau, peau douce, moins de détails |
| Teinte (±15°) | les verts vers le jaune, verts plus jaunes, ciel tirant sur le turquoise, peau vers le rouge | — (le sens dépend des deux couleurs) |

« adoucis » seul baisse le contraste. Suivi de la peau ou du visage, il lisse (clarté négative).

Le contraste local pivote autour de la luminosité moyenne de la zone, pour ne pas éclaircir ni assombrir la zone dans son ensemble.

## Dosage

- **Modérer :** « légèrement », « un peu », « un poil » donnent ×0,5.
- **Renforcer :** « très », « beaucoup », « nettement », « vraiment » donnent ×1,75.
- **Valeurs exactes :** « +0,7 IL sur le sujet », « assombris de 1,5 IL le ciel », « sature les verts de 20 % ». L'exposition est limitée à ±2 IL.
- **Après coup :** le curseur **Intensité** règle chaque retouche de 0 à 200 % (double-clic pour revenir à 100 %).

## Plusieurs consignes

- **Séparateurs :** virgule, point, « et », « puis », « ensuite ». Exemple : « ciel trop blanc, fond plus sombre ».
- **Consigne sans zone :** elle reprend la zone précédente. « éclaircis le visage et réchauffe-le » réchauffe la peau.
- **Consigne sans réglage :** elle reprend le réglage précédent. « assombris le ciel et les bords » assombrit les deux.
- **Partie non comprise :** elle est affichée sous le champ, jamais devinée.

## Gestion

- **Liste :** chaque consigne crée une ou plusieurs lignes qui décrivent la zone et le réglage compris, par exemple « Ciel × hautes lumières : exposition −0,40 IL ».
- **Désactiver ou supprimer :** décocher une ligne la désactive sans la perdre ; **Retirer** et **Tout retirer** la suppriment.
- **Plusieurs photos :** avec une sélection, la consigne s'applique à chaque photo et la zone est détectée photo par photo.
- **Indépendance :** les retouches locales s'appliquent après les réglages globaux et le style du profil. Les consignes saisies restent actives quand la retouche du lot est retirée ; les propositions apprises sont alors masquées.
- **Enregistrement :** les retouches sont enregistrées dans la bibliothèque, comme les curseurs, sans changement de schéma.

## Apprentissage par le profil

Le profil apprend les retouches locales **seulement à la validation du lot** (« Valider le lot », ou l'export, qui valide). Essayer, modifier ou retirer des consignes avant la validation n'apprend rien.

| À la validation | Ce que le profil retient |
| --- | --- |
| Consigne saisie et gardée | La retouche (zones et réglages, intensité incluse), associée à la photo |
| Proposition gardée telle quelle | Rien de nouveau |
| Proposition dont l'intensité a changé | La retouche avec sa nouvelle intensité |
| Proposition décochée ou retirée | Un refus de cette retouche pour les photos similaires |
| Retouche du lot retirée | Les propositions sont masquées, ni apprises ni refusées ; les consignes saisies restent apprises |

Au prochain import, Atelier cherche les photos validées qui ressemblent à chaque nouvelle photo, avec le même seuil de ressemblance que pour les curseurs globaux.

- **Vote :** chaque voisin vote pour les retouches qu'il a gardées et contre celles qu'il a refusées, avec un poids qui dépend de sa ressemblance.
- **Retouche proposée :** elle n'est proposée que si les votes pour l'emportent. Ses réglages sont la moyenne pondérée des exemples, et sa zone est recalculée sur la nouvelle photo.
- **Dans l'éditeur :** la proposition apparaît dans la liste avec la mention « (appris) ».
- **Lots existants :** les lots déjà importés gardent leurs propositions.
- **Oubli :** « Effacer les corrections apprises » oublie aussi les retouches locales.
- **Photos validées sans retouche locale :** elles ne votent pas contre. Pour faire oublier une retouche apprise, il faut la décocher ou la retirer sur les photos où elle est proposée.

Code : `local.lessons` et `local.suggest` ; enregistrement dans `Store.validate` ; proposition dans `analysis.learned_local_edits`.

## Export

| Format | Comportement |
| --- | --- |
| JPEG, PNG | Rendu avec les retouches locales |
| TIFF 16 bits | Rendu avec les retouches locales, sans réduction à 8 bits |
| RAW + XMP | RAW copié à l’identique ; chaque retouche cochée devient un masque Lightroom dans le XMP (voir ci-dessous) |
| Copie à l'identique | Fichier source inchangé, sans retouche |

Le masque est estimé sur une copie réduite de la photo développée, puis affiné à pleine résolution. L'aperçu et l'export donnent donc le même résultat.

### Masques Lightroom dans le XMP

En **RAW + XMP**, les retouches deviennent des corrections `crs:MaskGroupBasedCorrections`, lisibles par Lightroom 11 et Camera Raw 14 ou plus récents, et modifiables dans le panneau Masquage. Code : `atelier/lightroom.py`.

| Zone d'Atelier | Masque Lightroom |
| --- | --- |
| En haut, en bas, à gauche, à droite | Dégradé linéaire, mêmes points de départ et d'arrivée |
| Centre, bords et coins | Dégradé radial (inversé pour les bords) |
| Ombres, tons moyens, hautes lumières | Plage de luminance aux mêmes seuils |
| Couleurs, végétation, eau | Plage de couleurs, avec la couleur échantillonnée sur la photo |
| Peau | Plage de couleurs sur la teinte chair échantillonnée sur la photo |
| Ciel, sujet | Masques IA « Sélectionner le ciel » et « Sélectionner le sujet », calculés par Lightroom |
| Fond | Masque IA du sujet, inversé |
| Toute l'image | Dégradé couvrant toute la photo |

- **Plusieurs zones** (« ombres à gauche ») : les composants sont intersectés.
- **« sauf »** : inversion, et pour plusieurs zones la réunion des zones inversées.
- **Réglages :** exposition, contraste, température, saturation, clarté et teinte prennent les valeurs locales de Lightroom. L'exposition y est enregistrée en quarts d'IL.
- **Coordonnées :** elles tiennent compte du recadrage et de l'orientation du boîtier, comme le recadrage écrit dans le même XMP.

**À vérifier dans Lightroom.** Adobe ne documente pas ce format, et nous avons suivi des descriptions publiques sans pouvoir l'ouvrir dans Lightroom.
- **Masques IA :** ciel et sujet sont écrits sans leur image de masque. Lightroom doit les calculer, au besoin avec **Mettre à jour** dans le panneau Masquage.
- **Intersection :** le code d'intersection de deux composants n'est pas confirmé par une source testée.
- **Premier essai :** à faire sur une copie du catalogue.
- **Rendu :** Lightroom refait le rendu avec son propre moteur, proche de l'aperçu d'Atelier mais pas identique.

## Outils avancés : clarté, courbe et TSL

Dans **Retoucher**, le groupe repliable **Clarté, courbe et TSL** agit sur toute l'image des photos sélectionnées (code : `atelier/tools.py`).

| Outil | Effet | XMP |
| --- | --- | --- |
| Clarté | Contraste local des tons moyens, sans changer la luminosité moyenne ; négative, elle adoucit | `crs:Clarity2012` |
| Courbe des tons | Ombres, tons sombres, tons clairs et hautes lumières, sur une courbe toujours croissante | `crs:ParametricShadows`, `…Darks`, `…Lights`, `…Highlights` |
| Courbe par points | Lue dans le XMP d'une référence, appliquée et réécrite à l'identique | `crs:ToneCurvePV2012` (et Red, Green, Blue) |
| TSL | Teinte, saturation et luminance de 8 couleurs, voisines touchées en proportion, gris intacts | `crs:HueAdjustment…`, `SaturationAdjustment…`, `LuminanceAdjustment…` |

- **Ordre :** comme dans Lightroom, la clarté vient d'abord, puis la courbe après le contraste, puis la TSL après la saturation.
- **Aperçu et export :** même rendu ; le flou de la clarté est relatif au cadre.
- **Apprentissage :** ces réglages sont appris à la validation du lot, comme les curseurs, et proposés en moyenne pondérée aux photos similaires.
- **Retouche du lot retirée :** seuls vos changements par rapport à la proposition s'appliquent.

## Limites

- **Sujet et fond :** ils sont estimés, sans modèle de détourage. C'est fiable sur un sujet distinct de son fond, moins sur un fond chargé ou un sujet décentré.
- **Peau :** elle est reconnue par sa teinte, donc un mur beige, du bois ou du sable peuvent être touchés. Pour restreindre, ajoutez une position : « éclaircis la peau au centre ».
- **Ciel :** il doit toucher le haut de l'image ; un ciel vu par une fenêtre n'est pas détecté. Sans ciel détecté, la retouche ne change rien.
- **Supprimer, ajouter ou remplacer un objet, ou changer le décor :** ce n'est pas possible. Ces demandes sont signalées comme non comprises.
- **Validation :** les masques ont été validés sur des images de synthèse dans les tests. Il faut encore les vérifier sur de vrais reportages.
