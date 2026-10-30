# Fabriquer le DMG depuis Windows, sans outils sur le Mac de test

La compilation utilise un serveur macOS Apple Silicon GitHub Actions. Vous pouvez
la déclencher depuis le navigateur de ce PC. Le Mac de test ne recevra que le DMG.
Il faut un compte GitHub ; le dépôt peut rester **privé**. Aucun certificat Apple,
aucun secret Apple et aucune notarisation ne sont utilisés. Vérifiez dans votre
compte que GitHub Actions et votre quota de compilation sont disponibles.

## Préparer le dépôt depuis le navigateur

1. Décompressez `AtelierPhoto-0.4.0-GitHub-sources.zip` sur le PC Windows.
   L'archive contient uniquement le code, les tests, les licences et les guides.
   Aucune photo, mémoire de profil, bibliothèque Windows ou cache n'est présent.
   Le modèle lourd est téléchargé et vérifié par empreinte sur le serveur de compilation.
2. Connectez-vous sur [GitHub](https://github.com), puis créez un dépôt **Private**
   avec un README initial. Choisissez par exemple `atelier-photo`.
3. Dans ce dépôt, choisissez **Add file → Upload files**. Depuis le dossier extrait
   `AtelierPhoto-GitHub`, glissez les dossiers `atelier`, `scripts`, `tests`, `docs`
   et `packaging`, ainsi que les fichiers `main.py`, `pyproject.toml`,
   `requirements-tested.txt`, `README.md`, `THIRD_PARTY_NOTICES.md` et `LIRE SUR MAC.md`.
   Le fichier `main.py` doit se trouver à la racine du dépôt, pas dans un sous-dossier
   `AtelierPhoto-GitHub`. Validez l'envoi avec **Commit changes** sur la branche principale.
   N'envoyez pas le ZIP entier : GitHub doit voir les fichiers décompressés.
4. Choisissez **Add file → Create new file**. Saisissez comme nom :
   `.github/workflows/macos-test.yml`.
5. Sur Windows, ouvrez `workflow-macos-test.yml` de l'archive avec Bloc-notes.
   Copiez tout son contenu et collez-le dans l'éditeur GitHub. Validez **Commit changes**
   sur la branche principale. Le nom avec `.github/workflows/` est nécessaire.

[Envoi de fichiers depuis le navigateur : documentation GitHub](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository).
Le modèle a été retiré de cette archive pour respecter la limite de 25 MiB par
fichier dans le navigateur. Si GitHub limite le nombre de fichiers par envoi,
envoyez les dossiers en plusieurs fois.

## Compiler et récupérer le DMG

1. Dans GitHub, ouvrez **Actions**. Activez les workflows si GitHub le demande.
2. Choisissez **Construire le DMG Mac de test** dans la colonne de gauche.
3. Cliquez **Run workflow**, sélectionnez la branche principale et confirmez.
4. Attendez la fin : installation des outils, tests, compilation, diagnostic du
   binaire et création du DMG. Le modèle est inclus dans l'application finale.
5. Quand la compilation est verte, ouvrez son résultat et téléchargez l'artifact
   **AtelierPhoto-Mac-test**. Décompressez le ZIP téléchargé : il contient un seul DMG.
6. Envoyez uniquement `AtelierPhoto-0.4.0-macOS-arm64-test.dmg` au Mac de test.
   Le guide d'installation par clics se trouve dans le DMG.

[Déclencher une compilation depuis Actions : documentation GitHub](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).

Une compilation en échec ne produit pas d'installateur. Les rapports disponibles
sont dans l'artifact distinct **AtelierPhoto-Mac-diagnostics**. Les tests des sources
et le diagnostic du binaire ne remplacent pas l'essai Finder avec la protection
macOS active, les dialogues natifs, les photos RAW et les exports sur le Mac réel.

## Si vous disposez plus tard d'un Mac de construction

L'archive `Mac-sources.zip` et `Construire Atelier Photo (Mac).command` permettent aussi
une compilation locale. Les dépendances de développement sont nécessaires uniquement
sur ce Mac de construction : Python 3.12 arm64 et outils de ligne de commande Xcode.
Voir `docs/MACOS.md` pour les commandes techniques. Ne demandez pas au testeur
d'installer ces outils pour lancer le DMG déjà compilé.
