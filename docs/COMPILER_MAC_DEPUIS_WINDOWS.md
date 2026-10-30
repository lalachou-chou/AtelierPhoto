# Construire le DMG Mac depuis Windows avec GitHub Actions

Le dépôt contient les sources ; les dossiers `dist`, `.venv`, `deployment` et les
poids ONNX sont volontairement exclus de Git. Un téléchargement ZIP du dépôt
n’est donc pas un installateur et n’inclut pas le modèle.

1. Envoyer les sources sur GitHub, y compris `tests/`, `docs/` et
   `.github/workflows/`. Vérifier les fichiers
   proposés avant le commit ; ne pas utiliser `git add -f` pour les fichiers ignorés.
2. Dans le dépôt, ouvrir **Actions**. Si GitHub propose d’activer les workflows,
   les activer pour ce dépôt.
3. Vérifier le résultat de **Test desktop platforms** pour le commit envoyé.
   Une absence d’exécution n’est pas une validation des sources.
4. Sélectionner **Construire le DMG Mac de test**, puis **Run workflow** sur `main`.
   Laisser **Créer aussi le ZIP de l’application Mac** décoché pour obtenir
   seulement le DMG ; le cocher ajoute une archive de l’application autonome.
   Le workflow prépare les dépendances et télécharge les poids épinglés, vérifie
   leurs empreintes, exécute les tests puis compile et diagnostique l’application.
5. Après réussite, télécharger l’artefact **AtelierPhoto-Mac-test** au bas de
   l’exécution. Décompresser l’archive téléchargée pour récupérer le fichier DMG.
6. Envoyer le DMG au testeur avec [LIRE SUR MAC.md](../LIRE%20SUR%20MAC.md).

En cas d’échec, ouvrir l’étape rouge et consulter l’artefact
**AtelierPhoto-Mac-diagnostics**, s’il a été produit. Ne pas considérer un DMG
partiel ou issu d’une ancienne exécution comme le résultat du dernier commit.
Le workflow **Build desktop bundles** propose aussi des builds Windows et Mac.

Les workflows sont des compilations distantes explicites ; ils ne publient pas
automatiquement une Release. Les installateurs peuvent ensuite être ajoutés à
une Release GitHub. Aucun certificat Apple n’est nécessaire pour ce DMG de test,
mais l’installation et l’ouverture sur un vrai Mac restent à valider.
