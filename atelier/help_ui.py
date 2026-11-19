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
<h2>Du premier lot à l’export</h2>
<h3>1. Choisir son profil</h3><p>Dans la colonne de gauche, ouvrez <b>Gérer les profils…</b> pour créer
un profil (par exemple Mariages ou Portraits). Le profil actif reste visible au-dessus de ses lots.</p>
<h3>2. Ajouter ses exemples</h3><p>Ouvrez <b>Reportages et références…</b> sous le profil actif.
Un reportage associe le rush complet à vos photos retenues et apprend vos choix et vos retouches.
Les références sont des photos exemples sans leur rush : elles contribuent au classement par ressemblance,
au rendu et au cadrage. Cochez les groupes voulus, appliquez l’apprentissage et attendez le bilan avant l’import.</p>
<h3>3. Importer</h3><p>Ouvrez <b>Importer</b>. Choisissez votre profil et la sélectivité avant
de sélectionner un dossier ou des photos. Un dépôt depuis l’Explorateur ou le Finder ouvre la même étape.</p>
<h3>4. Examiner et décider</h3><p>Choisissez une vignette dans la galerie. Cliquez sur la photo ou sur
<b>Agrandir</b> pour l’examiner. Les flèches changent de photo et Échap ferme la vue agrandie.</p>
<p><b>1</b> retient, <b>2</b> marque à vérifier et <b>3</b> écarte.
Ctrl + clic (Cmd + clic sur Mac) sélectionne plusieurs vignettes. Une décision ou une retouche
s’applique alors à toute la sélection. Écarter conserve le fichier sur le disque.</p>
<h3>5. Exporter</h3><p>Ouvrez <b>Exporter</b>, choisissez le format et le dossier, puis validez.
Seules les photos retenues sont exportées. La validation mémorise vos corrections pour le profil.</p>
<h3>Organiser l’écran</h3><p>Faites glisser les séparations. Chaque colonne possède un bouton pour
la masquer. <b>Panneaux</b> permet de la rouvrir. Dans <b>Apparence</b>, choisissez une palette claire ou sombre.</p>
"""

ADVANCED = [
    ("Qualité, originaux et aperçus", """
    Le tri, les décisions et les curseurs sont enregistrés dans la bibliothèque locale. Atelier écrit
    les exports dans de nouveaux fichiers. L’aperçu et le zoom utilisent une image réduite pour
    rester rapides. L’export JPEG ou PNG relit le fichier source à sa résolution entière.
    Laissez donc les sources accessibles. Si le contenu a changé depuis l’analyse, réimportez la version modifiée.
    <p><b>Copie à l’identique</b> conserve les octets du fichier source, sa résolution, son profil couleur
    et ses métadonnées. Atelier vérifie la copie. Un XMP voisin reconnu est également copié.</p>
    <p><b>Remplacer les originaux au lieu de créer des copies</b> libère de la place sur un disque plein.
    Après une confirmation, chaque original retenu est remplacé dans son dossier par sa version
    retouchée, puis supprimé définitivement, sans passer par la corbeille. La version retouchée est
    entièrement écrite avant la suppression : une coupure laisse l’original ou le résultat, jamais aucun
    des deux. Un RAW exporté en RAW + XMP reste intact : seul son XMP voisin est écrit. Une photo sans
    retouche n’est pas touchée. Ce lot ne peut plus être exporté ensuite, car les retouches seraient
    appliquées deux fois.</p>
    <p><b>JPEG</b> propose trois qualités. <b>Maximale</b> conserve les JPEG intacts et encode les
    rendus en qualité 100. <b>Selon le JPEG source</b> conserve aussi les JPEG intacts et reprend
    les tables de compression et l’échantillonnage du JPEG RVB pour les retouches, si disponibles.
    Les autres rendus utilisent la qualité 100. <b>Personnalisée</b> réencode en qualité 1 à 100.
    Les dimensions correspondent aux pixels disponibles après recadrage. La compression JPEG peut
    modifier légèrement les pixels. <b>PNG</b> compresse sans perte les pixels du rendu sRGB
    8 bits. Le développement RAW, la conversion en sRGB et la réduction à 8 bits ont déjà eu lieu.
    La transparence des images rendues est composée sur fond blanc.</p>
    <p><b>RAW + XMP si nécessaire</b> copie le RAW à l’identique. Un cadrage, une correction globale,
    la clarté, la courbe, la TSL ou une retouche par consigne produit un XMP. Un RAW sans ces réglages est livré seul.
    Les retouches par consigne y deviennent des masques Lightroom (Lightroom 11 / Camera Raw 14 ou plus récent) :
    dégradés pour les positions, plages de luminance pour les tons, plages de couleur pour les couleurs et la peau,
    masques IA de Lightroom pour le ciel, le sujet et le fond.
    Le filtre couleur appris ne se retrouve pas dans cet XMP. La balance des blancs du boîtier y est conservée.
    Le rendu dépend du logiciel qui lit le fichier annexe. Dans un lot mixte, les JPEG et PNG sont
    exportés en JPEG avec ce choix.</p>"""),
    ("Clarté, courbe et TSL", """
    Dans <b>Retoucher</b>, dépliez <b>Clarté, courbe et TSL</b> sous les curseurs globaux.
    Les réglages s’appliquent à toutes les photos sélectionnées ; double-cliquer un curseur le remet à la proposition.
    <p><b>Clarté</b> : contraste local des tons moyens. Positive, elle donne du relief (feuillages, textures,
    architecture) sans changer la luminosité moyenne ; négative, elle adoucit (peau, brume).</p>
    <p><b>Courbe des tons</b> : quatre curseurs éclaircissent ou assombrissent les ombres, les tons sombres,
    les tons clairs et les hautes lumières. La courbe reste toujours croissante, sans inversion des tons.</p>
    <p><b>TSL</b> : choisissez une couleur (rouges, oranges, jaunes, verts, turquoises, bleus, violets, magentas),
    puis réglez sa teinte, sa saturation et sa luminance. Les couleurs voisines sont touchées en proportion,
    comme dans Lightroom, et les gris restent neutres.</p>
    <p>Ces outils sont rendus dans l’aperçu, le JPEG, le PNG et le TIFF, et écrits dans le XMP d’un export RAW
    (crs:Clarity2012, Parametric…, Hue/Saturation/LuminanceAdjustment…). Comme les curseurs, ils sont appris
    par le profil à la validation du lot et proposés aux photos similaires des prochains imports.
    Sans la retouche du lot, seules vos modifications par rapport à cette proposition s’appliquent.</p>"""),
    ("Exporter mes propres retouches", """
    <b>J’ai retouché la photo dans Atelier.</b> Ouvrez <b>Retoucher</b>. Pour démarrer avec des
    curseurs neutres, choisissez <b>Partir de zéro</b>, puis ajustez exposition, température,
    contraste et saturation. La température du rendu est exprimée en kelvins. À 6 500 K, le curseur
    conserve la balance de départ du rendu. Une valeur plus élevée le réchauffe.
    Validez et exportez en JPEG ou PNG pour obtenir votre rendu.
    <b>Rétablir la proposition</b> remet les valeurs initiales sur les photos sélectionnées.
    <p><b>J’ai déjà un JPEG ou un PNG retouché ailleurs.</b> Importez cette version finalisée,
    retenez-la et choisissez <b>Copie à l’identique</b>. Vous obtenez votre fichier retouché,
    sans nouvel encodage ni filtre supplémentaire.</p>
    <p><b>Je développe mes RAW dans un autre logiciel.</b> Pour conserver le RAW et ses propres
    instructions de retouche, choisissez <b>Copie à l’identique</b>. Atelier copie le XMP voisin de
    même nom (ou de type photo.ext.xmp). Un réglage uniquement enregistré dans un catalogue externe
    nécessite d’abord un export du XMP ou d’une image finalisée depuis cet autre logiciel.
    Atelier ne développe pas les instructions d’un XMP externe à l’export. En revanche, pour une photo de référence,
    il lit ce XMP pour apprendre votre rendu.</p>
    <p><b>Comparer ou désactiver.</b> Afficher l’original change uniquement l’aperçu.
    <b>Retirer la retouche sur tout le lot</b>, dans <b>Options du lot</b>, permet de partir de réglages
    neutres. Cliquez sur <b>Retoucher</b> dans la vue agrandie pour régler la sélection.
    Atelier mémorise ces réglages séparément. <b>Réappliquer la retouche sur tout le lot</b>
    retrouve vos réglages précédents. Le recadrage s’applique dans les deux modes.</p>
    <p><b>Recadrer</b> ouvre la photo entière. Tracez un cadre et déplacez ses coins avec le repère
    de votre choix. <b>Appliquer</b> enregistre le cadre sur la photo affichée. Rouvrez cet outil pour
    annuler un cadrage ou retrouver le cadre d’origine. Dans l’aperçu ou la vue agrandie, <b>Retirer le recadrage</b>
    affiche et exporte la photo entière. <b>Réappliquer le recadrage</b> récupère le cadre mémorisé.
    <b>Retirer les recadrages du lot</b> agit sur toutes les photos, y compris celles masquées par la galerie.
    Vous pouvez ensuite réactiver un cadre sur une seule photo. <b>Réappliquer les recadrages du lot</b>
    reprend les cadres actifs individuellement. Le JPEG et le PNG exportent la zone choisie.
    Pour un RAW, le format <b>RAW + XMP</b> inscrit le cadre dans le fichier XMP.</p>"""),
    ("Profils, apprentissage et références", """
    Un profil réunit les reportages d’apprentissage, les groupes de références, les corrections
    validées et les lots associés. Utilisez des profils distincts pour des styles de travail différents.
    Un nouveau profil peut trier immédiatement avec les paramètres fournis.
    <p>Dans <b>Reportages et références…</b>, sous le profil actif, associez un dossier d’originaux à votre
    sélection finale. La sélection nécessite au moins 6 originaux, dont 2 retenus et un écarté : ce minimum
    permet seulement de démarrer. Le tri s’affine avec chaque reportage complet ajouté, surtout s’ils sont variés.
    Pour les références, la variété compte plus que le nombre : quelques exemples de chaque type de scène
    suffisent, et des dizaines de photos presque identiques n’apportent rien de plus.
    Chaque paire associée fournit un exemple de rendu. Atelier cherche dans le rush la zone visible
    dans la retouche et mémorise le cadre si la correspondance est suffisamment précise.
    Le filtre couleur complet nécessite au moins 5 paires couleur correctement alignées.</p>
    <p><b>Ajouter des références</b> accepte des photos exemples sans leur rush associé : JPEG ou PNG,
    RAW + XMP, ou RAW seul. Pour un RAW, Atelier lit le XMP voisin (photo.xmp ou photo.nef.xmp, venant de Lightroom,
    Camera Raw ou Atelier). Il applique au RAW l’exposition, le contraste, la saturation, la balance des blancs,
    les hautes lumières et ombres, la clarté, les courbes (paramétrique et par points), la TSL et le recadrage,
    de façon approchée. Texture, correction du voile, teinte et masques sont ignorés.
    Un RAW seul guide la ressemblance et le cadre, mais pas le rendu : non développé, il ne montre pas votre retouche.
    Les références visuellement proches guident le rendu et le format du cadre. Avec une référence seule,
    le cadre proposé est centré. Vous pouvez le déplacer dans <b>Recadrer</b>. Activez les groupes voulus et attendez
    la fin de l’apprentissage avant l’import. Les lots déjà importés gardent leurs propositions.
    Valider le lot, y compris depuis l’export, mémorise les décisions, réglages et cadres explicitement corrigés.</p>"""),
    ("Sélectivité et limites du tri", """
    Réglez la sélectivité avant l’import. À gauche, Atelier retient davantage de photos. À droite,
    il est plus strict. Au centre, le profil fourni vise environ 16 % de retenues et jusqu’à 35 %
    à vérifier. Un profil appris conserve son propre taux. Les défauts, répétitions et doublons
    peuvent réduire les retenues. Le tri utilise le contenu, la netteté, l’exposition et les scènes.
    Vérifiez vous-même les expressions et les yeux fermés.
    <p>Après import, <b>Options du lot</b> permet de recalculer le tri du lot affiché.
    Les décisions manuelles et les retouches sont conservées. Validez de nouveau avant l’export.
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
    interrompu. Un export reprend son format et son dossier. Les noms de sortie sont réservés pour
    éviter d’écraser un fichier existant. Une interruption au moment précis de l’écriture peut
    laisser une copie supplémentaire à la reprise.
    <p>Les profils, aperçus et tâches restent sur cet ordinateur. Sélectionnez un lot dans <b>Profil et lots</b>,
    puis ouvrez <b>Options du lot → Supprimer ce lot</b> pour retirer son
    travail local et conserve les corrections déjà apprises. Supprimer un profil retire également
    ses lots et ses apprentissages. Les fichiers source et les exports restent dans leurs dossiers.</p>"""),
]


STEPS = (
    ("Profil", "Commencez par votre profil",
     "Votre profil rassemble vos choix de tri, vos références et vos retouches apprises. "
     "C’est lui qui personnalise les propositions d’Atelier Photo.", (
         ("Ouvrir les profils", "Dans la colonne de gauche, cliquez sur « Gérer les profils… », puis « Créer un profil »."),
         ("Nommer votre style", "Choisissez un nom parlant : Mariages, Portraits ou Paysages. Vous pouvez créer plusieurs profils."),
         ("Choisir le profil actif", "Son nom reste visible en haut de la colonne de gauche. Ses exemples et ses lots lui sont associés."),
     ), "Un profil neuf utilise les réglages fournis. Pour le personnaliser, donnez-lui vos exemples à l’étape suivante."),
    ("Références", "Montrez à Atelier ce que vous aimez",
     "Sous le profil actif, ouvrez « Reportages et références… ». Deux types d’exemples peuvent se compléter : "
     "un reportage déjà trié apprend vos choix ; des références seules contribuent au tri par ressemblance, au rendu et au cadrage.", (
         ("Ajouter vos exemples", "« Ajouter un reportage… » : associez le rush complet aux photos retenues, retouchées ou non. "
          "Pour apprendre le tri : au moins 6 originaux, dont 2 retenus et 1 écarté. C’est un minimum : "
          "plusieurs reportages complets donnent un tri bien plus fidèle. "
          "« Ajouter des références » : choisissez des photos exemples, sans leur rush, en variant les scènes "
          "(portraits, groupes, détails, intérieur, extérieur, nuit)."),
         ("Activer les bons groupes", "Chaque ajout apparaît dans la liste. Cochez les reportages et les groupes de références à utiliser pour ce profil. "
          "Décochez ceux à garder pour plus tard."),
         ("Lancer l’apprentissage", "Cliquez sur « Lancer l’apprentissage » ou « Appliquer et relancer l’apprentissage ». "
          "Attendez le bilan avant d’importer un nouveau lot."),
     ), "Les nouveaux exemples servent aux prochains imports. Les lots déjà importés conservent leurs propositions. "
        "Les références montrent ce que vous aimez ; un reportage trié montre aussi ce que vous écartez."),
    ("Import", "Confiez un nouveau lot à votre profil",
     "Un lot est une série de photos à trier. Importez un nouveau reportage après avoir préparé votre profil et ses exemples.", (
         ("Cliquer sur Importer…", "Le bouton est en haut de la fenêtre. Vous pouvez aussi déposer un dossier ou des photos dans la galerie."),
         ("Vérifier les réglages", "Choisissez le profil voulu. La sélectivité vers la gauche garde davantage de photos ; vers la droite, elle est plus stricte."),
         ("Choisir les photos", "Sélectionnez un dossier ou des fichiers RAW, JPEG ou PNG. Suivez l’analyse en bas de la fenêtre ; votre lot apparaît à gauche."),
     ), "Pour un premier essai d’import, un petit lot permet de vérifier vite les propositions. Attendez la fin de l’analyse avant de corriger le tri ou d’exporter."),
    ("Vérification", "Vous gardez le dernier mot",
     "La galerie affiche les propositions du profil. Examinez les photos, comparez les variantes et corrigez ce qui ne vous convient pas.", (
         ("Choisir et agrandir", "Cliquez sur une vignette à droite : la photo s’affiche au centre. « Agrandir » ouvre les détails ; les flèches passent à la photo suivante."),
         ("Décider sous la photo", "« Retenir » (1), « À vérifier » (2) ou « Écarter » (3). Le filtre de la galerie permet de retrouver les photos à examiner. "
          "Écarter ne supprime pas le fichier."),
         ("Ajuster si nécessaire", "« Retoucher… » règle le rendu ; « Recadrer… » ajuste le cadre. « Voir l’original » permet de comparer. "
          "Les réglages de tout le lot sont dans « Options du lot »."),
     ), "Ctrl + clic (Cmd + clic sur Mac) sélectionne plusieurs photos : les décisions et retouches s’appliquent alors à la sélection. "
        "Le recadrage concerne la photo affichée."),
    ("Export", "Exportez vos retenues et faites progresser le profil",
     "Une fois les propositions vérifiées, « Exporter… » en haut à droite permet de valider votre travail et d’enregistrer les photos retenues.", (
         ("Choisir le format", "JPEG ou PNG pour le rendu retouché ; « RAW + XMP si nécessaire » pour poursuivre le développement ; "
          "« Copie à l’identique » pour conserver le fichier source."),
         ("Choisir un dossier", "Cliquez sur « Parcourir… » et indiquez où enregistrer vos photos. Seules les retenues sont exportées ; vérifiez donc les photos encore « À vérifier »."),
         ("Valider et exporter", "Cliquez sur « Valider le lot et exporter ». La validation mémorise vos corrections pour le profil. "
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


PROMPT_HELP = """
<h2>Retouche par consigne</h2>
<p>Écrivez ce que vous voulez changer, en français, dans <b>Retoucher</b> puis <b>Retouche par consigne</b>.
Atelier détecte la zone et applique des réglages photographiques dans cette zone, avec un bord progressif.
<b>Aucun pixel n’est inventé</b> : la qualité de la photo est conservée. Tout fonctionne sur l’ordinateur,
sans connexion ni carte graphique.</p>

<h3>Zones reconnues</h3>
<table cellpadding="3">
<tr><td><b>Ciel</b></td><td>ciel, nuages : zone bleue ou claire reliée au haut de l’image.</td></tr>
<tr><td><b>Peau</b></td><td>peau, visage, teint, mains : teintes chair (le bois ou le sable peuvent être inclus).</td></tr>
<tr><td><b>Sujet</b> (estimé)</td><td>sujet, personne, mariés, couple, enfant, premier plan.</td></tr>
<tr><td><b>Fond</b> (estimé)</td><td>fond, arrière-plan, décor : l’inverse du sujet.</td></tr>
<tr><td><b>Végétation</b></td><td>herbe, pelouse, feuillage, arbres, verdure : les verts.</td></tr>
<tr><td><b>Eau</b></td><td>mer, lac, eau, piscine : bleus et turquoises.</td></tr>
<tr><td><b>Couleurs</b></td><td>les rouges, les oranges, les jaunes, les verts, les turquoises, les bleus, les violets, les roses.</td></tr>
<tr><td><b>Tons</b></td><td>ombres, zones sombres ; tons moyens ; hautes lumières, zones claires.</td></tr>
<tr><td><b>Position</b></td><td>en haut, en bas, à gauche, à droite, au centre, les bords ou les coins.</td></tr>
<tr><td><b>Toute l’image</b></td><td>image, photo, tout, partout, ou aucune zone indiquée.</td></tr>
</table>
<p>Les zones se combinent : « débouche les ombres à gauche » agit sur les ombres du côté gauche,
« peau moins rouge » sur les rouges de la peau. « sauf » inverse la zone : « assombris tout sauf le sujet ».</p>

<h3>Réglages reconnus</h3>
<table cellpadding="3">
<tr><td><b>Lumière</b></td><td>éclaircis, plus clair, lumineux, débouche, trop sombre ·
assombris, fonce, plus sombre, trop clair, trop blanc, brûlé, récupère les hautes lumières.</td></tr>
<tr><td><b>Température</b></td><td>réchauffe, plus chaud, trop froid, trop bleu ·
refroidis, plus froid, trop chaud, trop jaune, moins orange.</td></tr>
<tr><td><b>Contraste</b></td><td>plus de contraste, plus de peps, de relief, trop plat ·
moins de contraste, adoucis, plus doux, trop dur.</td></tr>
<tr><td><b>Saturation</b></td><td>sature, plus vif, ravive, trop terne, fade ·
désature, moins vif, moins coloré, fluo, criard · noir et blanc.</td></tr>
<tr><td><b>Une couleur</b></td><td>plus vert, moins rouge, moins rose… : renforce ou atténue cette couleur seulement.</td></tr>
<tr><td><b>Clarté</b></td><td>plus de clarté, plus de détails, plus net, fais ressortir les détails ·
lisse, adoucis la peau, peau douce, moins de détails.</td></tr>
<tr><td><b>Teinte</b></td><td>les verts vers le jaune, verts plus jaunes, ciel tirant sur le turquoise,
peau vers le rouge : décale la teinte de la zone d’environ 15°.</td></tr>
</table>
<p>« adoucis » seul baisse le contraste ; suivi de la peau ou du visage, il lisse (clarté négative).</p>

<h3>Doser l’effet</h3>
<p>« légèrement », « un peu » divisent l’effet par deux. « très », « beaucoup », « nettement » le renforcent.
Une valeur précise est reprise telle quelle : « +0,7 IL sur le sujet », « sature les verts de 20 % ».
Après coup, le curseur <b>Intensité</b> règle chaque retouche entre 0 et 200 %.</p>

<h3>Plusieurs consignes à la fois</h3>
<p>Séparez-les par une virgule, « et » ou « puis » : « ciel trop blanc, fond plus sombre ».
Une consigne sans zone reprend la zone précédente : « éclaircis le visage et réchauffe-le ».
Une consigne sans réglage reprend le réglage précédent : « assombris le ciel et les bords ».</p>

<h3>Exemples</h3>
<ul>
<li>éclaircis légèrement les visages</li>
<li>ciel trop blanc</li>
<li>fond plus sombre pour faire ressortir le sujet</li>
<li>peau moins rouge</li>
<li>herbe moins fluo et réchauffe le bas</li>
<li>débouche les ombres à gauche</li>
<li>noir et blanc sauf la peau</li>
<li>assombris les bords</li>
</ul>

<h3>Gérer les retouches</h3>
<p>Chaque consigne crée une ou plusieurs lignes dans la liste, avec la zone et le réglage compris.
Décochez une ligne pour la désactiver, <b>Retirer</b> la supprime. Avec plusieurs photos sélectionnées,
la consigne s’applique à chacune et la zone est détectée sur chaque photo.
L’aperçu, le JPEG, le PNG et le TIFF 16 bits contiennent les retouches locales.
En <b>RAW + XMP</b>, le RAW est copié tel quel et chaque retouche cochée devient un masque Lightroom dans le XMP,
modifiable ensuite dans Lightroom ou Camera Raw. Le ciel, le sujet et le fond sont des masques IA que
Lightroom calcule lui-même (au besoin, <i>Mettre à jour</i> dans le panneau Masquage). Lightroom refait le rendu
avec son moteur : le résultat est proche de l’aperçu d’Atelier, pas identique.</p>

<h3>Apprentissage par le profil</h3>
<p>Le profil apprend vos retouches locales <b>uniquement quand le lot est validé</b>
(<b>Valider le lot</b> ou l’export). Rien n’est appris pendant que vous essayez des consignes.
Au prochain import, une photo proche d’une photo validée reçoit la même retouche, marquée « (appris) ».
La zone est recalculée sur la nouvelle photo.</p>
<p>Gardée telle quelle, une proposition n’ajoute rien. Si vous changez son intensité, la nouvelle valeur
est apprise. Si vous la décochez ou la retirez, ce refus est appris et peut l’emporter sur les exemples.
<b>Retirer la retouche sur tout le lot</b> masque aussi ces propositions, sans les compter comme refusées.
Vos propres consignes restent appliquées dans les deux modes. Les lots déjà importés gardent leurs propositions.
<b>Effacer les corrections apprises</b> oublie aussi les retouches locales.</p>

<h3>Limites</h3>
<ul>
<li>Le sujet et le fond sont <b>estimés</b> d’après les couleurs, la netteté et la position. Vérifiez l’aperçu,
surtout quand le fond est chargé ou le sujet décentré.</li>
<li>La peau est reconnue par sa teinte. Un mur beige, du bois ou du sable peuvent être touchés.
Ajoutez une position pour restreindre : « éclaircis la peau au centre ».</li>
<li>Le ciel doit toucher le haut de l’image. Un ciel vu par une fenêtre n’est pas détecté.</li>
<li>Supprimer, ajouter ou remplacer un objet (« enlève le poteau », « change le décor ») n’est pas possible :
ces consignes sont signalées comme non comprises.</li>
</ul>
"""


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


def show_prompt_help(parent):
    dialog = QDialog(parent)
    dialog.setWindowTitle("Retouche par consigne — Atelier Photo")
    layout = QVBoxLayout(dialog)
    text = QTextBrowser()
    text.setHtml(PROMPT_HELP)
    layout.addWidget(text)
    close = QPushButton("Fermer")
    close.clicked.connect(dialog.reject)
    footer = QHBoxLayout()
    footer.addStretch()
    footer.addWidget(close)
    layout.addLayout(footer)
    dialog.resize(620, 640)
    dialog.exec()
    dialog.deleteLater()


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
    prompt = QTextBrowser()
    prompt.setHtml(PROMPT_HELP)
    tabs.addTab(prompt, "Retouche par consigne")
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
