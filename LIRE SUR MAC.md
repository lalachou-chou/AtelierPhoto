# Installer Atelier Photo sur le Mac de test

Pour **macOS 15 ou supérieur sur Apple Silicon (M1, M2, M3…)**.
Vérifiez dans le menu Apple → À propos de ce Mac.

Le Mac de test reçoit uniquement le **DMG compilé**, avec Python, les bibliothèques
et le modèle d'analyse intégrés. **Aucune installation de Python, Homebrew ou Xcode,
aucun Terminal et aucun compte développeur Apple n'est nécessaire.**
L'archive `Mac-sources.zip` contient du code à compiler : ce n'est pas l'installateur
à envoyer au testeur. Le DMG n'a pas encore été produit depuis cet hôte Windows.

## Installation par clics

1. Double-cliquez sur `AtelierPhoto-0.4.0-macOS-arm64-test.dmg`.
2. Dans la fenêtre ouverte, glissez **AtelierPhoto.app** sur **Applications**.
   Attendez la fin de la copie. Fermez une éventuelle version déjà ouverte.
3. Éjectez le disque « Atelier Photo » depuis Finder.
4. Dans **Applications**, double-cliquez sur **AtelierPhoto**.

## Autoriser le premier lancement si macOS le bloque

Cette version n'utilise aucun certificat Developer ID ni notarisation Apple.
Après une première tentative d'ouverture, si le développeur ne peut pas être vérifié :

1. Ouvrez **Réglages Système → Confidentialité et sécurité**.
2. Cliquez sur **Ouvrir quand même** pour **AtelierPhoto**.
3. Confirmez avec le mot de passe du Mac ou Touch ID si demandé, puis **Ouvrir**.

Les fois suivantes, un double-clic suffit. Ne désactivez pas Gatekeeper.
Si l'app est déclarée endommagée ou si l'autorisation n'est pas disponible, conservez
le message pour la personne qui vous a fourni le DMG. Un Mac géré peut restreindre
cette autorisation. [Procédure Apple](https://support.apple.com/fr-fr/102445).

## Utilisation

Créez un profil, ajoutez les références, puis importez un nouveau lot. Vérifiez
les décisions et retouches avant validation et export. Les originaux restent intacts.
Les profils et lots Windows ne sont pas inclus dans le programme.

La mémoire est conservée dans `~/Library/Application Support/AtelierPhoto`,
séparément du programme. Remplacer l'application n'efface pas les profils.
Le traitement et le modèle fonctionnent hors ligne, sans compte ni serveur.

## Fabrication du DMG

Sur Windows, sans autre Mac de construction, le guide
**docs/COMPILER_MAC_DEPUIS_WINDOWS.md** explique la compilation GitHub Actions,
depuis un navigateur. Les outils sont installés sur le serveur, pas chez le testeur.
Un compte GitHub et un dépôt contenant les sources sont nécessaires.
Aucune publication de code ou compilation distante n'a été faite automatiquement.

La seule empreinte technique conservée à la compilation est la signature locale
ad hoc obligatoire pour les exécutables Apple Silicon. Elle n'utilise aucune identité,
clé privée ou démarche Apple et n'est pas une validation Apple du programme.
[Explication Apple, section sécurité du code](https://help.apple.com/pdf/security/en_US/apple-platform-security-guide.pdf).
La compilation et l'ouverture réelle depuis Finder restent à tester.
