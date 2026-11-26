"""French walkthrough and the reference for the desktop tools."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

QUICK = """
<h2>Du rush au tri</h2>
<h3>1. Choisir son profil</h3><p>Dans la colonne de gauche, ouvrez <b>Gérer les profils…</b> pour créer
un profil (par exemple Mariages ou Portraits). Le profil actif reste visible au-dessus de ses lots.</p>
<h3>2. Ajouter ses exemples</h3><p>Ouvrez <b>Reportages et références…</b> sous le profil actif.
Un reportage associe le rush complet à vos photos retenues : Atelier apprend ce que vous gardez et ce que vous écartez.
Les références sont des photos que vous aimez, sans leur rush : les photos qui leur ressemblent montent
dans le classement, y compris pour départager les variantes d’une même scène.
Cochez les groupes voulus, appliquez l’apprentissage et attendez le bilan avant l’import.</p>
<h3>3. Importer</h3><p>Ouvrez <b>Importer</b>. Choisissez votre profil et la sélectivité avant
de sélectionner un dossier ou des photos. Un dépôt depuis l’Explorateur ou le Finder ouvre la même étape.
À la fin de l’analyse, le lot est trié automatiquement : chaque scène est regroupée avec ses variantes
et la meilleure image est retenue.</p>
<h3>4. Vérifier le tri</h3><p>Choisissez une vignette dans la galerie. Cliquez sur la photo ou sur
<b>Agrandir</b> pour l’examiner. Les flèches changent de photo et Échap ferme la vue agrandie.</p>
<p><b>1</b> retient, <b>2</b> marque à vérifier et <b>3</b> écarte, aussi dans la vue agrandie.
Ctrl + clic (Cmd + clic sur Mac) sélectionne plusieurs vignettes : la décision s’applique alors à toute
la sélection. <b>Groupes de variantes</b> isole une scène ; <b>Garder uniquement celle-ci</b> retient la
photo affichée et écarte ses variantes. Écarter conserve le fichier sur le disque.</p>
<h3>5. Exporter</h3><p>Ouvrez <b>Exporter</b> et choisissez un dossier. Les retenues y sont copiées à
l’identique, avec leurs XMP. La validation mémorise vos corrections de tri pour le profil.</p>
<h3>Organiser l’écran</h3><p>Faites glisser les séparations. Chaque colonne possède un bouton pour
la masquer. <b>Panneaux</b> permet de la rouvrir. Dans <b>Apparence</b>, choisissez une palette claire ou sombre.</p>
"""

ADVANCED = [
    ("Originaux, aperçus et export", """
    Atelier ne modifie jamais vos photos : il les trie. Le tri et les décisions sont enregistrés dans la
    bibliothèque locale. L’aperçu et le zoom utilisent la copie d’analyse (1 280 px au plus).
    <p><b>Exporter</b> copie les photos retenues à l’identique : mêmes octets, même résolution, mêmes
    métadonnées. Les XMP voisins (photo.xmp ou photo.nef.xmp) sont copiés avec elles. Le nom d’origine
    est conservé ; s’il existe déjà dans le dossier, « (2) », « (3) »… est ajouté. Aucun fichier n’est
    écrasé. Chaque copie est relue et comparée à l’original ; si l’original a changé depuis l’import,
    l’export est refusé : réimportez-le.</p>"""),
    ("Profils, apprentissage et références", """
    Un profil réunit les reportages d’apprentissage, les groupes de références, les corrections de tri
    validées et les lots associés. Utilisez des profils distincts pour des styles de travail différents.
    Un nouveau profil peut trier immédiatement avec le modèle fourni.
    <p>Dans <b>Reportages et références…</b>, sous le profil actif, associez un dossier d’originaux à votre
    sélection finale. L’apprentissage nécessite au moins 6 originaux, dont 2 retenus et un écarté : ce minimum
    permet seulement de démarrer. Le tri s’affine avec chaque reportage complet ajouté, surtout s’ils sont variés.</p>
    <p><b>Ajouter des références</b> accepte des photos exemples sans leur rush associé : RAW, JPEG ou PNG.
    Leur contenu est comparé à chaque photo importée. La ressemblance s’ajoute au score du modèle de
    sélection : entre deux variantes d’une scène, la plus proche de vos références est favorisée.
    Sans reportage appris, une photo éloignée de toutes les références passe « à vérifier » au lieu
    d’être retenue d’office. Pour les références, la variété compte plus que le nombre : quelques exemples
    de chaque type de scène suffisent. Activez les groupes voulus et attendez la fin de l’apprentissage
    avant l’import. Les lots déjà importés gardent leurs propositions.</p>
    <p>Valider le lot, y compris depuis l’export, mémorise les décisions que vous avez changées.
    Au prochain import, une photo très proche d’une photo corrigée en tient compte.</p>"""),
    ("Sélectivité, scènes et variantes", """
    Réglez la sélectivité avant l’import. À gauche, Atelier retient davantage de photos. À droite,
    il est plus strict. Au centre, le modèle fourni vise environ 16 % de retenues et jusqu’à 35 %
    à vérifier. Un profil appris conserve son propre taux. Les défauts, répétitions et doublons
    peuvent réduire les retenues. Le tri utilise le contenu, la netteté, l’exposition et les scènes.
    Vérifiez vous-même les expressions et les yeux fermés.
    <p>Les photos sont rangées par heure de prise de vue, puis regroupées en scènes : moins de 20 secondes
    d’écart et un contenu proche. Dans chaque scène, la meilleure image est retenue ; une seconde ne l’est
    que si elle apporte une image vraiment différente. Les autres variantes passent à vérifier ou sont écartées.</p>
    <p>Après import, <b>Options du lot</b> permet de recalculer le tri du lot affiché.
    Les décisions manuelles sont conservées. Validez de nouveau avant l’export.
    Dans la galerie, <b>Groupes de variantes</b> liste les scènes détectées. <b>Isoler ses variantes</b>
    affiche toutes les photos de la scène sélectionnée. <b>Garder uniquement celle-ci</b> retient la
    photo affichée et écarte les autres variantes. <b>Revenir au lot</b> affiche toutes les photos du lot.</p>"""),
    ("Récupérer des photos corrompues", """
    Pendant un import ou un apprentissage, un fichier reconnu comme endommagé peut être déplacé
    avec son XMP dans <b>Photos corrompues</b>, à côté de son emplacement initial. Ce dossier est
    ignoré lors d’un nouvel import du dossier parent. Un boîtier non reconnu peut simplement
    produire une erreur de lecture et rester à sa place.
    <p>Choisissez le profil concerné, puis <b>Tâches → Récupérer les photos corrompues</b>.
    Cochez les fichiers et choisissez un dossier pour les copies. Pour un RAW, Atelier tente
    d’extraire l’aperçu intégré du boîtier, dont la résolution peut être inférieure à celle
    du capteur. Il peut aussi relire certains JPEG tronqués ou isoler des pixels PNG intacts.</p>
    <p>Consultez le résultat de chaque tentative dans la même fenêtre. Vérifiez visuellement
    chaque copie avant de la réimporter. Des données de pixels détruites peuvent rendre
    la récupération impossible ou produire une image partielle.</p>"""),
    ("Pause, reprise et données locales", """
    Une suspension termine le fichier en cours. <b>Tâches</b> permet de reprendre un traitement
    interrompu. Un export reprend dans son dossier. Les noms de sortie sont réservés pour
    éviter d’écraser un fichier existant. Une interruption au moment précis de l’écriture peut
    laisser une copie supplémentaire à la reprise.
    <p>Les profils, aperçus et tâches restent sur cet ordinateur. Sélectionnez un lot dans <b>Profil et lots</b>,
    puis ouvrez <b>Options du lot → Supprimer ce lot</b> pour retirer son
    travail local ; les corrections déjà apprises sont conservées. Supprimer un profil retire également
    ses lots et ses apprentissages. Les fichiers source et les exports restent dans leurs dossiers.</p>"""),
]


STEPS = (
    ("Profil", "Commencez par votre profil",
     "Votre profil rassemble vos choix de tri et vos références. "
     "C’est lui qui personnalise les propositions d’Atelier Photo.", (
         ("Ouvrir les profils", "Dans la colonne de gauche, cliquez sur « Gérer les profils… », puis « Créer un profil »."),
         ("Nommer votre style", "Choisissez un nom parlant : Mariages, Portraits ou Paysages. Vous pouvez créer plusieurs profils."),
         ("Choisir le profil actif", "Son nom reste visible en haut de la colonne de gauche. Ses exemples et ses lots lui sont associés."),
     ), "Un profil neuf trie avec le modèle fourni. Pour le personnaliser, donnez-lui vos exemples à l’étape suivante."),
    ("Références", "Montrez à Atelier ce que vous gardez",
     "Sous le profil actif, ouvrez « Reportages et références… ». Deux types d’exemples peuvent se compléter : "
     "un reportage déjà trié apprend vos choix ; des références seules font monter les photos qui leur ressemblent.", (
         ("Ajouter vos exemples", "« Ajouter un reportage… » : associez le rush complet aux photos retenues. "
          "Pour apprendre le tri : au moins 6 originaux, dont 2 retenus et 1 écarté. C’est un minimum : "
          "plusieurs reportages complets donnent un tri bien plus fidèle. "
          "« Ajouter des références » : choisissez des photos que vous aimez, sans leur rush, en variant les scènes "
          "(portraits, groupes, détails, intérieur, extérieur, nuit)."),
         ("Activer les bons groupes", "Chaque ajout apparaît dans la liste. Cochez les reportages et les groupes de références à utiliser pour ce profil. "
          "Décochez ceux à garder pour plus tard."),
         ("Lancer l’apprentissage", "Cliquez sur « Lancer l’apprentissage » ou « Appliquer et relancer l’apprentissage ». "
          "Attendez le bilan avant d’importer un nouveau lot."),
     ), "Les nouveaux exemples servent aux prochains imports. Les lots déjà importés conservent leurs propositions. "
        "Les références montrent ce que vous aimez ; un reportage trié montre aussi ce que vous écartez."),
    ("Import", "Confiez un rush à votre profil",
     "Un lot est une série de photos à trier. À la fin de l’analyse, Atelier regroupe les variantes de chaque scène "
     "et fait sa sélection automatiquement.", (
         ("Cliquer sur Importer…", "Le bouton est en haut de la fenêtre. Vous pouvez aussi déposer un dossier ou des photos dans la galerie."),
         ("Vérifier les réglages", "Choisissez le profil voulu. La sélectivité vers la gauche garde davantage de photos ; vers la droite, elle est plus stricte."),
         ("Choisir les photos", "Sélectionnez un dossier ou des fichiers RAW, JPEG ou PNG. Suivez l’analyse en bas de la fenêtre ; votre lot apparaît à gauche."),
     ), "Pour un premier essai, un petit lot permet de vérifier vite les propositions. Attendez la fin de l’analyse avant de corriger le tri ou d’exporter."),
    ("Vérification", "Vous gardez le dernier mot",
     "La galerie affiche la sélection du profil : retenues, à vérifier, écartées. Comparez les variantes et corrigez ce qui ne vous convient pas.", (
         ("Choisir et agrandir", "Cliquez sur une vignette à droite : la photo s’affiche au centre. « Agrandir » ouvre la vue plein écran ; les flèches passent à la photo suivante."),
         ("Décider", "« Retenir » (1), « À vérifier » (2) ou « Écarter » (3), sous la photo ou dans la vue agrandie. "
          "Le filtre de la galerie permet de retrouver les photos à examiner. Écarter ne supprime pas le fichier."),
         ("Comparer les variantes", "« Groupes de variantes » isole une scène. « Garder uniquement celle-ci » retient la photo affichée et écarte les autres."),
     ), "Ctrl + clic (Cmd + clic sur Mac) sélectionne plusieurs photos : la décision s’applique alors à toute la sélection."),
    ("Export", "Récupérez vos retenues et faites progresser le profil",
     "Une fois le tri vérifié, « Exporter… » en haut à droite valide votre travail et copie les photos retenues.", (
         ("Choisir un dossier", "Cliquez sur « Parcourir… » et indiquez où copier vos photos. Seules les retenues sont copiées ; vérifiez donc les photos encore « À vérifier »."),
         ("Copie à l’identique", "Les fichiers et leurs XMP sont copiés sans aucune modification, sous leur nom d’origine. Rien n’est écrasé."),
         ("Valider et exporter", "Cliquez sur « Valider le lot et exporter ». La validation mémorise vos corrections de tri pour le profil. "
          "Suivez l’export en bas de la fenêtre."),
     ), "Pour vos prochains lots : choisissez le bon profil, enrichissez ses références si nécessaire, puis importez. "
        "Ce guide reste accessible dans « Aide »."),
)


def guide_label(text, name=None):
    item = QLabel(text)
    item.setWordWrap(True)
    if name:
        item.setObjectName(name)
    return item


class GuideDialog(QDialog):
    """A navigable workflow: arrows connect actual consecutive user actions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Premiers pas — Atelier Photo")
        self.setMinimumSize(620, 460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        layout.addWidget(guide_label("BIENVENUE DANS ATELIER PHOTO", "eyebrow"))
        layout.addWidget(guide_label("Votre regard, votre profil, vos photos.", "guideTitle"))
        rail = QHBoxLayout()
        rail.setSpacing(6)
        self.steps = []
        for index, (name, *_) in enumerate(STEPS):
            if index:
                rail.addWidget(guide_label("→", "flowArrow"))
            step = QPushButton(f"{index + 1} · {name}")
            step.setCheckable(True)
            step.setAutoDefault(False)
            step.setAccessibleName(f"Étape {index + 1} : {name}")
            step.clicked.connect(lambda checked=False, i=index: self.show_step(i))
            rail.addWidget(step, 1)
            self.steps.append(step)
        layout.addLayout(rail)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body = QWidget()
        self.body.setObjectName("workspace")
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)
        self.title = guide_label("", "heading")
        self.intro = guide_label("")
        body.addWidget(self.title)
        body.addWidget(self.intro)
        flow = QHBoxLayout()
        flow.setSpacing(10)
        self.cards = []
        for i in range(3):
            if i:
                arrow = guide_label("→", "flowArrow")
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                flow.addWidget(arrow)
            card = QFrame()
            card.setObjectName("guideCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 16, 16, 16)
            card_layout.setSpacing(12)
            card_layout.addWidget(guide_label(f"0{i + 1}", "eyebrow"))
            title = guide_label("", "cardTitle")
            text = guide_label("")
            card_layout.addWidget(title)
            card_layout.addWidget(text)
            card_layout.addStretch()
            flow.addWidget(card, 1)
            self.cards.append((title, text))
        body.addLayout(flow, 1)
        self.tip = guide_label("", "guideTip")
        body.addWidget(self.tip)
        scroll.setWidget(self.body)
        layout.addWidget(scroll, 1)
        footer = QHBoxLayout()
        later = QPushButton("Plus tard")
        later.clicked.connect(self.reject)
        footer.addWidget(later)
        self.position = guide_label("", "muted")
        footer.addWidget(self.position)
        footer.addStretch()
        self.previous = QPushButton("← Précédent")
        self.previous.clicked.connect(lambda: self.show_step(self.index - 1))
        footer.addWidget(self.previous)
        self.next = QPushButton()
        self.next.setObjectName("primary")
        self.next.setDefault(True)
        self.next.clicked.connect(self.advance)
        footer.addWidget(self.next)
        layout.addLayout(footer)
        self.show_step(0)
        available = self.screen().availableGeometry().size()
        self.resize(min(980, available.width() - 40), min(680, available.height() - 70))

    def show_step(self, index):
        self.index = max(0, min(index, len(STEPS) - 1))
        _, title, intro, cards, tip = STEPS[self.index]
        self.title.setText(title)
        self.intro.setText(intro)
        for (heading, body), (caption, text) in zip(self.cards, cards, strict=True):
            heading.setText(caption)
            body.setText(text)
        self.tip.setText("À retenir · " + tip)
        self.position.setText(f"{self.index + 1} / {len(STEPS)}")
        self.previous.setEnabled(self.index > 0)
        self.next.setText("Ouvrir les profils →" if self.index == len(STEPS) - 1 else "Suivant →")
        for i, step in enumerate(self.steps):
            step.setChecked(i == self.index)

    def advance(self):
        if self.index == len(STEPS) - 1:
            self.accept()
        else:
            self.show_step(self.index + 1)


def guide(parent):
    dialog = GuideDialog(parent)
    result = dialog.exec()
    dialog.deleteLater()
    return result == QDialog.DialogCode.Accepted


def reference_html():
    """La référence technique (Markdown) convertie en fragment HTML pour l'aide."""
    import re

    from PySide6.QtGui import QTextDocument

    from .help_reference import REFERENCE
    document = QTextDocument()
    document.setMarkdown(REFERENCE)
    html = document.toHtml()
    body = re.search(r"<body[^>]*>(.*)</body>", html, re.S)
    return body.group(1) if body else html


def show_help(parent):
    dialog = QDialog(parent)
    dialog.setWindowTitle("Aide — Atelier Photo")
    layout = QVBoxLayout(dialog)
    tabs = QTabWidget()
    quick = QTextBrowser()
    quick.setHtml(QUICK)
    tabs.addTab(quick, "Prise en main")
    advanced = QTextBrowser()
    advanced.setObjectName("advancedHelp")
    links = " &nbsp;·&nbsp; ".join(f'<a href="#s{i}">{title}</a>' for i, (title, _) in enumerate(ADVANCED))
    links += ' &nbsp;·&nbsp; <a href="#reference"><b>Fonctionnement détaillé</b></a>'
    sections = "".join(f'<h3><a name="s{i}"></a>{title}</h3><p>{body}</p>' for i, (title, body) in enumerate(ADVANCED))
    advanced.setHtml(f"<h2>Aide avancée</h2><p>{links}</p>{sections}"
                     f'<hr><a name="reference"></a>{reference_html()}')
    tabs.addTab(advanced, "Aide avancée")
    layout.addWidget(tabs)
    replay = QPushButton("Revoir le tutoriel")
    def replay_guide():
        if guide(dialog):
            dialog.accept()

    replay.clicked.connect(replay_guide)
    close = QPushButton("Fermer")
    close.clicked.connect(dialog.reject)
    footer = QHBoxLayout()
    footer.addWidget(replay)
    footer.addStretch()
    footer.addWidget(close)
    layout.addLayout(footer)
    dialog.resize(650, 565)
    result = dialog.exec()
    dialog.deleteLater()
    return result == QDialog.DialogCode.Accepted
