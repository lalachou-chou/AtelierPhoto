"""Build the report for the second DINOv3 experiment from measured results."""
import csv
import html
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.benchmark_dino_detail import OUTPUT, PREVIOUS, native_image, crops_preview
import numpy as np


def main():
    report=json.loads((OUTPUT/'results.json').read_text(encoding='utf8'))
    timing=json.loads((OUTPUT/'timing-isolated.json').read_text())
    m=report['models']; n=report['dataset']['photos']
    primary=['small_224','base_224','small_448','small_448_details','base_448','base_448_details']
    labels={'small_224':'Small 224, référence précédente','base_224':'Base 224, contrôle de taille',
            'small_448':'Small 448, vue globale seule','small_448_details':'Small 448 + deux vues détaillées',
            'base_448':'Base 448, vue globale seule','base_448_details':'Base 448 + deux vues détaillées'}
    rows=['# DINOv3 : résolution supérieure et vues détaillées','',
          f"Reportage Carla & Ndue : {n} originaux, {report['dataset']['kept']} retenus distincts. Les dossiers bonus et impression sont exclus.",'',
          'Les deux configurations avec détails ne dépassent pas Small 224 pour placer une variante livrée en première position dans ce test. Base avec détails fait mieux que Small avec détails, mais son coût de calcul est supérieur. Le contrôle avec régularisation choisie sur l’apprentissage ne renverse pas ce constat.', '',
          'Base avec détails améliore toutefois la présence d’une bonne variante parmi les deux premières propositions par rapport à Small 224. La haute résolution sans détails est plus intéressante à poursuivre : avec réglage interne, Small 448 obtient 41 bonnes variantes sur 101 et Base 448 en obtient 40. Ce sont des pistes exploratoires, pas une supériorité établie sur de nouveaux reportages.', '',
          '## Comparaison principale','',
          'La bonne variante est une photo effectivement livrée placée en tête de sa scène. Les 101 scènes informatives contiennent à la fois une photo retenue et une non retenue. La sélection globale utilise un budget identique de 20 % retenues et 20 % à vérifier.', '',
          '| Configuration | Bonne variante en tête | Dans les deux premières | Choix exacts / 232 propositions | Choix humains dans retenues + à vérifier | Encodage médian / photo |',
          '|---|---:|---:|---:|---:|---:|']
    for key in primary:
        a=m[key]; t=timing['steps'][key]['median']
        rows.append(f"| {labels[key]} | {a['variants']['top1_correct']}/101 ({a['variants']['top1']:.1%}) | {a['variants']['top2']:.1%} | {a['exact_matches']}/{a['selected']} | {a['kept_or_review_recall']:.1%} | {t*1000:.0f} ms |")
    rows+=['','Temps : nouveau chronométrage isolé sur 24 photos réparties dans le reportage, deux threads CPU par modèle, préchauffage exclu. La lecture des originaux est mesurée à part. Les deux modèles sont en float32. Les valeurs précédentes ne sont pas directement substituées à ce nouveau chronométrage.', '',
           '## Ce qui a été testé','',
           '- Small : DINOv3 ViT-S/16 ; Base : DINOv3 ViT-B/16. Poids gelés ; seuls les modèles de sélection sont appris.',
           '- Vue globale : image entière ramenée à 448 × 448, soit 784 patches de 16 × 16 contre 196 à 224 × 224. Comme dans le test initial, la vue globale est redimensionnée au carré.',
           '- Deux vues locales de 224 × 224, découpées dans l’original à sa résolution native, après orientation EXIF et conversion sRGB. Ce sont de nouveaux passages dans le modèle, pas de simples regroupements des descripteurs globaux.',
           '- Priorité aux deux plus grands visages disponibles. Sinon : premier visage ou haut de la personne principale, puis région centrée sur la personne. Sans détection : cadrage central et image entière. Les régions carrées peuvent exclure une partie du corps ; elles ne garantissent pas que tous les visages du groupe soient couverts.',
           '- Fusion principale : vecteur global et moyenne normalisée des deux vecteurs locaux, concaténés pour apprendre leur contribution. Une fusion conservant séparément les deux vues a aussi été testée.',
           '- Les cadrages utilisent uniquement les détections du premier benchmark, jamais les choix du photographe. Pas de reconnaissance de texte, pas de critère de retouche, pas de jugement esthétique imposé.', '',
           '## Protocole et limites','',
           '- Les mêmes 219 scènes et cinq blocs de test que précédemment sont réutilisés. Une scène entière reste dans un seul bloc ; une scène voisine est exclue de chaque côté du bloc test.',
           '- Normalisation et apprentissage se font uniquement sur les blocs d’entraînement. Régularisation C=0,02 dans le comparatif principal.',
           '- Contrôle supplémentaire : C choisi sur trois sous-blocs internes, sans consulter les choix du bloc test, dans 0,0001 ; 0,001 ; 0,01 ; 0,1 ; 1.',
           '- Le contrôle Small 224 réutilise les vecteurs du premier essai (aperçu normalisé). Les nouvelles vues sont issues des originaux natifs : la comparaison représente donc la nouvelle chaîne complète, pas une modification du seul nombre de pixels.',
           '- Il s’agit d’une poursuite exploratoire sur le même mariage déjà examiné, et non d’un nouveau test indépendant. L’examen de nombreuses configurations expose à choisir une amélioration due au hasard.',
           '- Les sous-groupes de visages/personnes proviennent de détecteurs imparfaits. La faible netteté ne distingue pas flou artistique et flou accidentel. Les choix livrés restent le seul indicateur de préférence artistique.', '',
           '## Contrôle par réglage interne de régularisation','',
           '| Configuration | Bonne variante en tête, C fixe | Bonne variante en tête, C choisi sur l’apprentissage |','|---|---:|---:|']
    for key in primary:
        rows.append(f"| {labels[key]} | {m[key]['variants']['top1']:.1%} | {m[key+'_nested']['variants']['top1']:.1%} |")
    rows+=['','## Sous-groupes : configuration principale avec détails','',
           '| Scènes contenant une retenue… | Small 224 | Small 448 + détails | Base 448 + détails |','|---|---:|---:|---:|']
    for group,label in [('faces_detected','avec visage détecté'),('multiple_people','avec plusieurs personnes détectées'),('off_center_person','avec personne principale décentrée'),('low_sharpness','dans le quartile de faible netteté')]:
        a=m['small_224']['subgroups'][group]
        values=[m[k]['subgroups'][group]['top1'] for k in ['small_224','small_448_details','base_448_details']]
        rows.append(f"| {label} ({a['scenes']} scènes) | {values[0]:.1%} | {values[1]:.1%} | {values[2]:.1%} |")
    rows+=['','Ces sous-groupes se recouvrent ; ce ne sont pas des mesures de précision de détection des yeux, des personnes ou de leur position.','',
           '## Incertitude face à Small 224','',
           'Bootstrap apparié de scènes, 5 000 tirages. Ces intervalles exploratoires ne corrigent pas les comparaisons multiples et ne mesurent pas la variabilité entre reportages.','',
           '| Configuration | Différence de bonne variante en tête | Intervalle exploratoire 95 % |','|---|---:|---:|']
    for key in primary:
        d=m[key]['delta_vs_small224']; lo,hi=d['ci95_points']
        rows.append(f"| {labels[key]} | {d['points']:+.1f} points | [{lo:+.1f} ; {hi:+.1f}] |")
    rows+=['','## Tous les essais secondaires','',
           '`pairwise` apprend les préférences entre photos de la même scène. `separate` garde distincts les deux vecteurs locaux. `nested` choisit C par validation interne. `clip_scenes` conserve les distributions de scores de CLIP et ne change que l’ordre des variantes.','',
           '| Configuration | Variante exacte | Top 2 | Choix exacts retenus | Retenues + à vérifier : rappel |','|---|---:|---:|---:|---:|']
    for key,a in m.items():
        rows.append(f"| {key} | {a['variants']['top1']:.1%} | {a['variants']['top2']:.1%} | {a['exact_matches']} | {a['kept_or_review_recall']:.1%} |")
    rows+=['','## Reproduction','',
           'Scripts : `scripts/prepare_selection_benchmark.py`, `scripts/benchmark_dino_detail.py`, `scripts/report_dino_detail.py`. Les révisions et empreintes des poids ainsi que la politique de cadrage sont enregistrées dans `protocol.json`. Les vecteurs sont mis en cache par image avec vérification de la source et de la configuration.','',
           '```powershell',
           '.\\.venv\\Scripts\\python.exe scripts/prepare_selection_benchmark.py',
           '.\\.venv\\Scripts\\python.exe scripts/benchmark_dino_detail.py extract',
           '.\\.venv\\Scripts\\python.exe scripts/benchmark_dino_detail.py evaluate',
           '.\\.venv\\Scripts\\python.exe scripts/benchmark_dino_detail.py timing',
           '.\\.venv\\Scripts\\python.exe scripts/report_dino_detail.py',
           '```','']
    (OUTPUT/'rapport.md').write_text('\n'.join(rows),encoding='utf8')
    with (OUTPUT/'comparison.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream); writer.writerow(['configuration','top1','top2','exact_matches','selected','kept_or_review_recall','delta_points','ci95_low','ci95_high'])
        for key,a in m.items():
            d=a['delta_vs_small224']
            writer.writerow([key,a['variants']['top1'],a['variants']['top2'],a['exact_matches'],a['selected'],a['kept_or_review_recall'],d['points'],*d['ci95_points']])
    examples(report)
    crops_preview()
    print('Reports saved to',OUTPUT)


def examples(report):
    info=json.loads((PREVIOUS/'dataset.json').read_text(encoding='utf8'))
    z=np.load(OUTPUT/'predictions.npz')
    order,truth,labels=z['order'],z['truth'],z['labels']
    names=['small_224','small_448_details','base_448_details']
    (OUTPUT/'review-images').mkdir(exist_ok=True)
    sections=[]
    for label in np.unique(labels):
        ix=np.where(labels==label)[0]
        if not truth[ix].any() or truth[ix].all(): continue
        leaders=[ix[np.argmax(z[k][ix])] for k in names]
        if len(set(leaders))==1: continue
        cards=[]
        indices=list(dict.fromkeys(leaders+list(ix[truth[ix]][:2])))
        for i in indices:
            source=Path(info['paths'][order[i]])
            target=OUTPUT/'review-images'/f'{order[i]:05}.jpg'
            if not target.exists():
                img=native_image(source); img.thumbnail((700,500)); img.save(target,quality=90)
            choices=', '.join(names[k] for k in range(3) if leaders[k]==i)
            caption=source.name+(' — RETENUE photographe' if truth[i] else ' — non retenue')+' — '+choices
            cards.append(f'<figure><img src="review-images/{target.name}"><figcaption>{html.escape(caption)}</figcaption></figure>')
        sections.append(f'<section><h2>Scène {int(label)} · {len(ix)} photos</h2><div>'+''.join(cards)+'</div></section>')
        if len(sections)>=30: break
    page='<!doctype html><html lang="fr"><meta charset="utf-8"><title>DINOv3 — haute résolution et détails</title><style>body{font:16px system-ui;background:#17191c;color:#eee;margin:32px}p{max-width:1000px;line-height:1.6}section{margin:30px 0}section div{display:flex;gap:16px;flex-wrap:wrap}figure{width:380px;margin:0}img{width:100%;height:280px;object-fit:contain;background:#080808}figcaption{padding:10px;font-size:14px}</style><h1>Small 224, Small 448 + détails, Base 448 + détails</h1><p>Les 30 premières scènes chronologiques où les choix des configurations principales diffèrent. Les réussites et les échecs sont montrés sans filtrage par résultat. Toutes les prédictions sont réalisées sur leur bloc de test, exclu de l’apprentissage correspondant.</p>'+''.join(sections)+'</html>'
    (OUTPUT/'variantes.html').write_text(page,encoding='utf8')


if __name__=='__main__': main()
