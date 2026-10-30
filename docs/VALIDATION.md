# Qualification avant diffusion

## Résultats locaux du 5 octobre 2026

- 30 tests automatisés passés sur Windows / Python 3.12 pour la version 0.2.
- Parcours Qt réel testé avec processus `spawn`, vrai CLIP, correction, validation,
  export et aperçu ; mise en page contrôlée sur capture hors écran.
- Exécutable Windows autonome construit avec pyside6-deploy/Nuitka, puis diagnostic
  réussi directement dans le binaire : 3 références, 3 analyses, 3 exports,
  processus de traitement et d’aperçu fonctionnels, originaux inchangés,
  suppression du lot et conservation de l’apprentissage vérifiées.
- Installateur Windows généré avec succès par Inno Setup (taille de la version
  0.2 consignée dans `AUDIT.md`).
  L’exécutable et l’installateur ne sont pas signés avec un certificat éditeur.
  Le programme d’installation n’a pas été installé dans le profil utilisateur
  pendant les tests ; le bundle qu’il contient a été testé directement.
- Mesure avec vrai CLIP CPU : 200 références en 8,90 s, analyse de 1 000 images en
  47,95 s, pic mémoire du processus 214,1 Mio, aucune erreur. Images JPEG
  synthétiques de 128 × 96 pixels : ces chiffres ne sont pas extrapolables à des
  RAW ou à des photos pleine résolution et n’évaluent pas la qualité du tri.
- Développement et export JPEG vérifiés sur le fichier Canon 40D sRAW
  `RAW_CANON_40D_SRAW_V103.CR2` du jeu de test public rawpy : sortie 1 944 × 1 296,
  profil sRGB présent, original inchangé. Le fichier de test reste hors distribution.
- Pas de validation sur Mac réel ni sur un corpus représentatif de plusieurs
  boîtiers à ce stade.

Les tests automatisés vérifient persistance, isolement et effacement des profils,
référence dupliquée, annulation/reprise, erreurs de fichiers, doubles exports,
source modifiée, disque plein, orientation, recettes déterministes, corrections
idempotentes et invariance des instantanés. Le test de volume utilise 200 références
et 1 000 petites images synthétiques avec un encodeur de test. Le test CLIP dédié
utilise les vrais poids et interdit les connexions réseau Python.

## Essai photographique

Constituer des références finales avec plusieurs luminosités et sujets. Réserver
un lot distinct d’au moins 200 photos avec les catégories suivantes : portraits,
paysages, action, faible lumière, contre-jour, faible profondeur de champ, flou
artistique, ratés, rafales et doublons. Inclure des RAW de chaque boîtier visé.

Annoter manuellement la sélection souhaitée avant de consulter la proposition.
Mesurer : bonnes photos écartées, photos incertaines, variantes mal regroupées,
retouches corrigées et temps de validation. Objectif initial : moins de 1 % de
bonnes photos écartées automatiquement, tous rejets récupérables et 100 % des
originaux inchangés. Cet objectif n’est pas encore validé sur un corpus réel.

Comparer les exports aux aperçus sur un écran géré en couleur, notamment les
teintes de peau, ombres et hautes lumières. Consigner les préférences de l’utilisateur
et ajuster les seuils uniquement à partir d’un lot d’entraînement séparé du lot test.

## Volume et plateformes

Sur Windows 11 x64 puis macOS 15+ arm64, 16 Go de RAM : analyser 1 000 photos de
résolutions usuelles, mesurer durée et pic mémoire, tester suspension et fermeture
forcée puis reprise. Vérifier l’absence de croissance mémoire proportionnelle aux
pixels de toutes les photos. L’export doit conserver résolution et orientation.

Couper le réseau après installation et refaire le parcours complet. Tester les
permissions de dossier, source déplacée, média externe déconnecté et disque plein.
Installer le bundle sur une machine sans Python. Vérifier la désinstallation sans
effacement des originaux. Sur Mac de test, ne préinstaller ni Python, Homebrew
ni Xcode : ouvrir le DMG, glisser l'application dans Applications, autoriser son
premier lancement dans les réglages si nécessaire, puis lancer par double-clic.
La version de test ne demande aucun certificat Developer ID ni notarisation.
