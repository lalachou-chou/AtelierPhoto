"""Consignes de retouche en français, traduites en retouches locales (local.py).

L'analyse est volontairement simple et prévisible : un vocabulaire photographique
fixe, sans modèle de langage ni connexion. Chaque consigne produit une ou
plusieurs retouches visibles et modifiables dans l'éditeur ; une partie non
comprise est signalée telle quelle, jamais devinée.

Exemples : « éclaircis légèrement les visages », « ciel trop blanc »,
« fond plus sombre », « peau moins rouge », « herbe moins fluo et réchauffe le bas ».
"""
import re
import unicodedata
import uuid

from .local import COLORS, ZONE_LABELS

# Pas de base de chaque réglage (unités des curseurs globaux).
STEP = {"exposure": .4, "temperature": .35, "contrast": .15, "saturation": .3, "clarity": .3, "hue": .5}

_COLOR_WORDS = {
    "rouge": "rouges", "orange": "oranges", "jaune": "jaunes", "vert": "verts", "cyan": "cyans",
    "turquoise": "cyans", "bleu": "bleus", "violet": "violets", "mauve": "violets",
    "magenta": "magentas", "rose": "magentas",
}
_COLOR = r"(rouge|orange|jaune|vert|cyan|turquoise|bleu|violet|mauve|magenta|rose)(?:e|s|es)?"

# (motif, zone). L'ordre compte : le premier motif trouvé consomme son texte.
ZONE_PATTERNS = [
    (r"hautes? lumieres?|zones? claires?|parties? claires?|les blancs", "hautes_lumieres"),
    (r"tons? moyens?|demi tons?|tons? intermediaires?", "tons_moyens"),
    (r"ombres?|zones? sombres?|parties? sombres?|les noirs", "ombres"),
    (r"ciels?|nuages?", "ciel"),
    (r"peaux?|visages?|teints?|carnations?|joues?|mains?|bras|figures?|frimousses?", "peau"),
    (r"arriere plan|fond|decors?|derriere", "fond"),
    (r"sujets?|personnes?|personnages?|modeles?|maries?|mariee?s?|couples?|premier plan|enfants?|gens|bebes?",
     "sujet"),
    (r"herbes?|pelouses?|gazon|feuillages?|arbres?|vegetation|verdure|plantes?|feuilles?|foret", "verts"),
    (r"mer|ocean|lac|eau|riviere|piscine|vagues?", "eau"),
    (r"(?:les|des|tons?|teintes?|couleurs?) " + _COLOR, "color"),
    (r"(?:en|vers le|du|le|la|partie) haut(?:e)?|haut de", "haut"),
    (r"(?:en|vers le|du|le|la|partie) bas(?:se)?|bas de|\bsol\b", "bas"),
    (r"(?:a|cote|la|partie|sur la) gauche", "gauche"),
    (r"(?:a|cote|la|partie|sur la) droite", "droite"),
    (r"centre|milieu", "centre"),
    (r"bords?|coins?|contours?|peripherie|vignet\w*", "bords"),
    (r"image|photos?|tout|ensemble|globalement|partout", "image"),
]

# (motif, réglages, zone implicite). Une seule règle par réglage et par consigne.
_UP = r"(?:augment\w*|monte\w*|ajoute\w*|hausse\w*|remont\w*|plus de|pousse\w*)"
_DOWN = r"(?:baiss\w*|diminu\w*|redui\w*|reduis|moins de|enleve\w*|retire\w*|attenu\w*)"
_ARTICLE = r"(?: la| le| l| les| de| d| des| du)?"
_TONES_AHEAD = r"(?= (?:les |des )?(?:hautes lumieres|ombres|zones|parties|blancs|noirs|tons))"

ACTION_PATTERNS = [
    (r"noir et blanc|monochrome|n ?& ?b|sans couleurs?", {"saturation": -1 / STEP["saturation"]}, None),
    # Verbes explicites suivis du réglage nommé.
    (_UP + _ARTICLE + r" (?:saturation|couleurs?|vibrance)", {"saturation": 1}, None),
    (_DOWN + _ARTICLE + r" (?:saturation|couleurs?|vibrance)", {"saturation": -1}, None),
    (_UP + _ARTICLE + r" (?:clarte|details?|structure|nettete|piqu\w*)", {"clarity": 1}, None),
    (_DOWN + _ARTICLE + r" (?:clarte|details?|structure|nettete|piqu\w*)", {"clarity": -1}, None),
    (_UP + _ARTICLE + r" contraste", {"contrast": 1}, None),
    (_DOWN + _ARTICLE + r" contraste", {"contrast": -1}, None),
    (_UP + _ARTICLE + r" (?:exposition|luminosite|lumiere)", {"exposure": 1}, None),
    (_DOWN + _ARTICLE + r" (?:exposition|luminosite|lumiere)", {"exposure": -1}, None),
    (_UP + _ARTICLE + r" (?:chaleur|temperature)", {"temperature": 1}, None),
    (_DOWN + _ARTICLE + r" (?:chaleur|temperature)", {"temperature": -1}, None),
    (r"(?:baiss\w*|diminu\w*|redui\w*|reduis|attenu\w*)" + _TONES_AHEAD, {"exposure": -1}, None),
    (r"(?:monte\w*|augment\w*|remont\w*|pousse\w*)" + _TONES_AHEAD, {"exposure": 1}, None),
    # Teinte : « les verts vers le jaune », « tirant sur le rouge ».
    (r"(?:vers|tirant sur|tire\w* vers|decal\w* vers)(?: le| la| l| du)? " + _COLOR, "hue", None),
    # Dominantes de couleur.
    (r"(?:moins|trop) " + _COLOR, "color-", None),
    (r"plus " + _COLOR, "color+", None),
    # Lumière : formes « trop » et « moins » d'abord, pour ne pas inverser le sens.
    (r"trop (?:blanc|blanche|blancs|blanches|brule|brulee|brules|crame|cramee|cramees)|brule\w*|crame\w*|"
     r"recuper\w* (?:les |des )?(?:hautes lumieres|details|blancs)", {"exposure": -1}, "hautes_lumieres"),
    (r"trop (?:sombres?|foncee?s?|noire?s?|sous exposee?s?|obscure?s?)|moins (?:sombres?|foncee?s?)",
     {"exposure": 1}, None),
    (r"trop (?:claire?s?|clairs|lumineu\w*|exposee?s?)|moins (?:claire?s?|clairs|lumineu\w*)",
     {"exposure": -1}, None),
    (r"debouch\w*|recuper\w* (?:les |des )?ombres|sous expose\w*|eclairci\w*|eclaire\w*|illumin\w*|"
     r"lumineu\w*|plus (?:clair|claire|claires|clairs)|plus de lumiere|ensoleill\w*", {"exposure": 1}, None),
    (r"assombri\w*|fonce\w*|plus (?:sombres?|foncee?s?)|surexpose\w*|plus dense|densifi\w*",
     {"exposure": -1}, None),
    (r"rechauff\w*|plus chaude?s?|plus chauds|trop froide?s?|trop froids|trop bleue?s?|plus dore\w*|ambiance chaude",
     {"temperature": 1}, None),
    (r"refroidi\w*|plus froide?s?|plus froids|trop chaude?s?|trop chauds|trop jaunes?|trop oranges?|moins chaude?s?|"
     r"moins jaunes?|moins oranges?|ambiance froide", {"temperature": -1}, None),
    # Clarté (contraste local des tons moyens) : avant le contraste, pour « adoucis la peau ».
    (r"plus (?:de )?(?:clarte|details?|pique\w*|nets?|nettes?|structure\w*|croquant\w*)|clarifi\w*|"
     r"(?:accentu\w*|fais ressortir|renforc\w*) (?:les |des )?(?:details?|textures?)", {"clarity": 1}, None),
    (r"lisse\w*|adouci\w*(?= (?:la |le |les |l )?(?:peaux?|visages?|teints?|carnations?))|peau douce|effet doux|"
     r"moins (?:de )?(?:details?|nets?|nettes?|pique\w*|clarte)|flou\w* doux|glow", {"clarity": -1}, None),
    (r"moins contraste\w*|trop contraste\w*|trop dure?s?|adouci\w*|plus douce?s?|plus doux",
     {"contrast": -1}, None),
    (r"plus contraste\w*|contraste\w*|plus de (?:peps|punch|relief|pep)|trop plate?s?|trop mous?|"
     r"donne du (?:peps|punch|relief)", {"contrast": 1}, None),
    (r"desatur\w*|moins (?:sature\w*|vive?s?|vifs?|coloree?s?|intense\w*|fluo|flashy|pet\w*)|"
     r"trop (?:sature\w*|vive?s?|vifs?|fluo|flashy|criarde?s?|coloree?s?|pet\w*)|fluo|criard\w*|flashy",
     {"saturation": -1}, None),
    (r"satur\w*|plus (?:vive?s?|vifs|coloree?s?|intense\w*|eclatant\w*|pet\w*)|raviv\w*|"
     r"trop (?:terne|ternes|fade|fades|delave\w*|grise?s?)|ternes?|fades?|delave\w*", {"saturation": 1}, None),
]

WEAKER = r"\b(?:legerement|un peu|un poil|un tantinet|un brin|subtilement|doucement|legere?|leger)\b"
STRONGER = r"\b(?:beaucoup|nettement|fortement|vraiment|tres|franchement|bien|encore|nettement plus|carrement)\b"
_EV = r"([+-]?\d+(?:[.,]\d+)?)\s*(?:il|ev|stops?|diaph\w*)\b"
_PERCENT = r"([+-]?\d+(?:[.,]\d+)?)\s*%"
_EXCEPT = r"\b(?:sauf|excepte|hors|a part|sans toucher(?: a)?)\b"


def normalize(text):
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[’'`\-_/]", " ", text)
    return " " + re.sub(r"\s+", " ", text).strip() + " "


def _consume(text, pattern):
    match = re.search(r"(?<![a-z])(?:" + pattern + r")(?![a-z])", text)
    if not match:
        return text, None
    return text[:match.start()] + " " * (match.end() - match.start()) + text[match.end():], match


def _zones(text):
    found = []
    for pattern, zone in ZONE_PATTERNS:
        while True:
            text, match = _consume(text, pattern)
            if not match:
                break
            name = _COLOR_WORDS[match.group(1)] if zone == "color" else zone
            if name not in found:
                found.append(name)
    return text, found


def _number(value):
    return float(value.replace(",", "."))


def _clause(text):
    """Une consigne simple : (réglages, zones, inversion, texte restant)."""
    # « les verts plus jaunes » : deux couleurs différentes, c'est un glissement de teinte.
    pair = re.search(r"(?<![a-z])" + _COLOR + r" plus " + _COLOR + r"(?![a-z])", text)
    if pair and _COLOR_WORDS[pair.group(1)] != _COLOR_WORDS[pair.group(2)]:
        text = text[:pair.start()] + f"les {pair.group(1)} vers le {pair.group(2)}" + text[pair.end():]
    text, ev = _consume(text, _EV)
    text, percent = _consume(text, _PERCENT)
    factor = 1.
    text, weak = _consume(text, WEAKER)
    text, strong = _consume(text, STRONGER)
    if weak:
        factor = .5
    elif strong:
        factor = 1.75
    values, implicit, hue_target = {}, [], None
    for pattern, effect, zone in ACTION_PATTERNS:
        text, match = _consume(text, pattern)
        if not match:
            continue
        if effect == "hue":
            hue_target = _COLOR_WORDS[match.group(1)]
            continue
        if isinstance(effect, str):
            color = _COLOR_WORDS[match.group(1)]
            if color in ("jaunes", "oranges", "bleus") and effect == "color-":
                # « moins jaune », « trop bleu » : une dominante, corrigée par la température.
                sign = -1 if color in ("jaunes", "oranges") else 1
                values.setdefault("temperature", sign)
                continue
            implicit.append(color)
            values.setdefault("saturation", -1 if effect == "color-" else 1)
            continue
        for key, sign in effect.items():
            values.setdefault(key, sign)
        if zone:
            implicit.append(zone)
    amounts = {key: sign * STEP[key] * factor for key, sign in values.items()}
    if ev and "exposure" in amounts:
        amount = abs(_number(ev.group(1)))
        amounts["exposure"] = amount if amounts["exposure"] > 0 else -amount
    elif ev:
        amounts["exposure"] = _number(ev.group(1))
    if percent:
        amount = abs(_number(percent.group(1))) / 100
        for key in ("saturation", "contrast"):
            if key in amounts:
                amounts[key] = amount if amounts[key] > 0 else -amount
    before, after = text, ""
    exception = re.search(_EXCEPT, text)
    if exception:
        before, after = text[:exception.start()], text[exception.end():]
    rest, zones = _zones(before)
    invert = False
    if after:
        after, excluded = _zones(after)
        rest += after
        excluded = [z for z in excluded if z != "image"]
        if excluded:
            zones, invert = excluded, True
    for zone in implicit:
        if zone not in zones:
            zones.append(zone)
    if hue_target:
        # Sens de rotation : de la couleur de la zone vers la couleur demandée.
        regions = {"peau": "oranges", "ciel": "bleus", "eau": "eau"}
        source = next((z for z in zones if z in COLORS), None) or next(
            (regions[z] for z in zones if z in regions), None)
        if source and source != hue_target:
            turn = (COLORS[hue_target][0] - COLORS[source][0] + 180) % 360 - 180
            amounts["hue"] = (1. if turn > 0 else -1.) * STEP["hue"] * factor
        elif not amounts:
            rest += " " + hue_target
    return amounts, zones, invert, rest


_FILLER = re.compile(r"\b(?:le|la|les|l|un|une|des|du|de|d|au|aux|a|en|et|sur|dans|que|qui|plus|moins|trop|un peu|"
                     r"peu|stp|svp|s il te plait|s il vous plait|merci|rends?|rendre|mets?|mettre|fais|faire|"
                     r"je|veux|voudrais|aimerais|il|elle|ils|elles|est|sont|soit|soient|me|moi|nous|vous|ton|ta|"
                     r"tes|son|sa|ses|cette|ce|ces|cet|y|lui|leur|leurs|tout|toute|toutes|tous|un|pour|avec|"
                     r"par|ajoute|ajouter|augmente|augmenter|diminue|diminuer|baisse|baisser|reduis|reduire|"
                     r"monte|monter|ok|oui|pas|ne|n|c|ca|cela|on|peux|tu|pourrais|ressortir|valeur|afin|davantage|couleurs?|teintes?|tons?)\b")


def describe(edit):
    zones = " × ".join(ZONE_LABELS.get(z, z) for z in edit.get("zones") or ["image"])
    if edit.get("invert"):
        zones = "tout sauf " + zones
    parts = []
    if edit.get("exposure"):
        parts.append(f"exposition {edit['exposure']:+.2f}\u00a0IL".replace(".", ","))
    if edit.get("temperature"):
        parts.append("plus chaud" if edit["temperature"] > 0 else "plus froid")
    if edit.get("contrast"):
        parts.append(f"contraste {edit['contrast'] * 100:+.0f}\u00a0%")
    if edit.get("saturation"):
        parts.append("noir et blanc" if edit["saturation"] <= -.999 else f"saturation {edit['saturation'] * 100:+.0f}\u00a0%")
    if edit.get("clarity"):
        parts.append(f"clarté {edit['clarity'] * 100:+.0f}")
    if edit.get("hue"):
        parts.append(f"teinte {edit['hue'] * 30:+.0f}°")
    return f"{zones[:1].upper()}{zones[1:]} : " + ", ".join(parts)


def parse(prompt):
    """Retourne (retouches, parties non comprises)."""
    text = normalize(prompt)
    if not text.strip():
        return [], []
    clauses = [c for c in re.split(r"[;!?]|(?<!\d)[,.]|[,.](?!\d)|\bpuis\b|\bensuite\b|(?<!noir )\bet\b(?! blanc)", text) if c.strip()]
    edits, unknown = [], []
    previous_zones, previous_amounts, previous_invert = None, None, False
    for raw in clauses:
        amounts, zones, invert, rest = _clause(" " + raw + " ")
        leftover = _FILLER.sub(" ", rest).strip()
        if not amounts and zones and previous_amounts and not leftover:
            # « assombris le ciel et les bords » : même réglage, nouvelle zone.
            # Jamais quand un verbe inconnu reste (« change le décor »).
            amounts = dict(previous_amounts)
        if amounts and not zones and previous_zones is not None:
            # « éclaircis le visage et réchauffe-le » : même zone, nouveau réglage.
            zones, invert = list(previous_zones), previous_invert
        if not amounts:
            unknown.append(raw.strip())
            continue
        if leftover:
            unknown.append(leftover)
        zones = zones or ["image"]
        if "image" in zones and len(zones) > 1:
            zones.remove("image")
        if "sujet" in zones and "fond" in zones:
            # « fond plus sombre pour faire ressortir le sujet » : la zone citée en premier.
            zones.remove("fond" if zones.index("sujet") < zones.index("fond") else "sujet")
        edit = {"id": uuid.uuid4().hex, "prompt": raw.strip(), "zones": zones, "invert": invert,
                "exposure": 0., "temperature": 0., "contrast": 0., "saturation": 0., "clarity": 0., "hue": 0.,
                "strength": 1., "enabled": True}
        edit.update({k: max(-2., min(2., v)) for k, v in amounts.items()})
        edit["label"] = describe(edit)
        edits.append(edit)
        previous_zones, previous_amounts, previous_invert = zones, amounts, invert
    return edits, unknown
