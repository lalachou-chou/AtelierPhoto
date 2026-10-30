"""Summarize the local benchmark and make reviewable photographic comparisons."""
import csv
import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.compare_selection_models import load_data, ASSETS
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

OUTPUT = ROOT / 'test-output' / 'selection-comparison'


def overview():
    """Visual sanity check on detections; deliberately not an accuracy benchmark."""
    paths = sorted((OUTPUT / 'cache').glob('*.npz'))
    rows = []
    for path in paths:
        with np.load(path) as z:
            meta = json.loads(str(z['metadata']))
        if meta['detail']['faces']:
            rows.append(meta)
    if not rows:
        return
    selected = [rows[i] for i in np.linspace(0, len(rows)-1, min(12,len(rows)), dtype=int)]
    board = Image.new('RGB', (1200, 300*((len(selected)+2)//3)), '#191919')
    draw = ImageDraw.Draw(board)
    for i, row in enumerate(selected):
        with Image.open(row['stamp'][0]) as source:
            img = ImageOps.exif_transpose(source).convert('RGB')
            img.thumbnail((390, 250))
        x,y = (i%3)*400, (i//3)*300
        board.paste(img,(x,y))
        for f in row['detail']['faces']:
            bx,by,bw,bh = f['box']
            draw.rectangle((x+bx*img.width,y+by*img.height,x+(bx+bw)*img.width,y+(by+bh)*img.height),outline='#50e1af',width=2)
        draw.text((x+5,y+255),Path(row['stamp'][0]).name,fill='white')
        draw.text((x+5,y+273),f"faces={len(row['detail']['faces'])}, people={len(row['detail']['people'])}",fill='white')
    board.save(OUTPUT/'detection-check.jpg',quality=92)


def interval(candidate, baseline):
    c = {r['scene']:r['top1'] for r in candidate}
    b = {r['scene']:r['top1'] for r in baseline}
    keys = sorted(set(c)&set(b))
    diff = np.array([int(c[k])-int(b[k]) for k in keys])
    rng = np.random.default_rng(20261029)
    boot = diff[rng.integers(0,len(diff),(5000,len(diff)))].mean(1)
    return {'difference':float(diff.mean()), 'ci95':np.quantile(boot,[.025,.975]).tolist(), 'scenes':len(keys)}


def main():
    report = json.loads((OUTPUT/'results.json').read_text(encoding='utf-8'))
    models=report['models']
    baseline=models['clip']['scene_results']
    for name, model in models.items():
        model['top1_delta_vs_clip'] = interval(model['scene_results'],baseline)
    (OUTPUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    fields=['model','selected','exact_matches','precision','recall','kept_or_review_recall','missed_kept','variant_scenes','variant_top1','variant_top2','pair_accuracy','top1_delta','ci95_low','ci95_high']
    with (OUTPUT/'comparison.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        for name,m in models.items():
            row={k:m[k] for k in fields if k in m}
            row.update(model=name,variant_scenes=m['variants']['scenes'],variant_top1=m['variants']['top1'],variant_top2=m['variants']['top2'],pair_accuracy=m['variants']['pair_accuracy'],top1_delta=m['top1_delta_vs_clip']['difference'],ci95_low=m['top1_delta_vs_clip']['ci95'][0],ci95_high=m['top1_delta_vs_clip']['ci95'][1])
            writer.writerow(row)
    selected=['clip','siglip2','dinov3','clip_pairwise','clip_photo','siglip2_photo','dinov3_photo','clip_photo_pairwise','siglip2_photo_pairwise','dinov3_photo_pairwise','dinov3_spatial_photo_pairwise','siglip2_spatial_photo_pairwise']
    selected += [k for k in ['clip_dino_rerank','clip_photo_dino_rerank'] if k in models]
    selected += [k for k in ['clip_nested','siglip2_nested','dinov3_nested'] if k in models]
    lines=['# Comparaison locale des modèles de sélection','',
           'Reportage Carla & Ndue. Résultats exploratoires sur un seul mariage ; aucune modification des profils ou du logiciel livré.','',
           '## Lecture des résultats','',
           f"- Variante exacte en tête : CLIP {models['clip']['variants']['top1']:.1%}, SigLIP 2 {models['siglip2']['variants']['top1']:.1%}, DINOv3 {models['dinov3']['variants']['top1']:.1%}.",
           f"- CLIP avec apprentissage comparatif : {models['clip_pairwise']['variants']['top1']:.1%}. Les deux premières propositions contiennent une retenue dans {models['clip_pairwise']['variants']['top2']:.1%} des scènes, contre {models['clip']['variants']['top2']:.1%} pour CLIP initial.",
           f"- Correspondances exactes dans la sélection globale : CLIP {models['clip']['exact_matches']}/{models['clip']['selected']}, DINOv3 {models['dinov3']['exact_matches']}/{models['dinov3']['selected']}. Le choix des scènes et celui des variantes doivent être évalués séparément.",
           '- Les combinaisons et réglages secondaires figurent dans le tableau ci-dessous. Les hypothèses ajoutées après le comparatif initial sont identifiées comme exploratoires.',
           '- Ces résultats ne suffisent pas à démontrer un gagnant universel : il faut confirmer le choix sur plusieurs reportages indépendants.', '',
           '## Protocole','',
           f"- {report['dataset']['photos']} originaux, {report['dataset']['kept']} retenus, {report['dataset']['scenes']} scènes fixes.",
           '- Vérité terrain : noms des exports livrés, sans association dépendant du modèle évalué. Couleur et noir et blanc du même original comptent une fois.',
           '- Cinq blocs chronologiques ; aucune scène partagée entre apprentissage et test ; une scène supplémentaire exclue de chaque côté du bloc test.',
           '- Normalisation, régression et classement comparatif appris uniquement sur les blocs d’entraînement. C=0,02 fixé dans le comparatif principal. Les variantes `nested` règlent C sur trois sous-blocs internes uniquement (0,0001 ; 0,001 ; 0,01 ; 0,1 ; 1).',
           '- Scènes, contexte, filtre de redondance et quota identiques pour tous, définis avec le CLIP actuel. Ce test isole la représentation et le classement ; il ne compare pas des segmentations de scènes propres à chaque modèle.',
           '- Budget 20 % retenues + 20 % à vérifier. Les rejets techniques bloquants actuels restent actifs ; les autres avertissements ne rétrogradent pas les propositions dans ce banc contrôlé.',
           '- Le classement comparatif permute les scores au sein de chaque scène, sans modifier sa distribution de scores ni son importance globale.',
           '- Pas de texte, pas de retouche, pas de modèle esthétique générique. Les choix artistiques sont représentés uniquement par les choix livrés du photographe.',
           '', '## Résultats', '',
           '« Variante exacte » : dans les scènes contenant à la fois une retenue et une non-retenue, la photo classée première appartient aux choix du photographe. Cette mesure suppose la scène examinée et précède les quotas/rejets.', '',
           '| Configuration | Variante exacte | Dans les 2 premières | Retenues exactes / proposées | Retenues humaines disponibles (retenues + à vérifier) |',
           '|---|---:|---:|---:|---:|']
    for name in selected:
        m=models[name]
        lines.append(f"| {name} | {m['variants']['top1']:.1%} | {m['variants']['top2']:.1%} | {m['exact_matches']} / {m['selected']} | {m['kept_or_review_recall']:.1%} |")
    lines+=['','`photo` = visages/expressions + personnes/cadrage + grille de netteté/luminosité. `pairwise` = apprentissage du choix entre variantes. `spatial` = descripteurs du modèle regroupés par quadrants. `dino_rerank` = choix des scènes par CLIP et ordre de leurs variantes par DINOv3 ; cette combinaison a été ajoutée après examen des premiers résultats, elle est donc exploratoire. `nested` = réglage de régularisation par validation imbriquée. Tous les tests d’ablation sont dans comparison.csv.','',
            '## Visages, personnes, flou et choix artistiques','',
            f"MediaPipe Face Landmarker a détecté au moins un visage sur {report['dataset']['faces_detected_photos']}/{report['dataset']['photos']} photos. EfficientDet-Lite0 a détecté au moins une personne sur {report['dataset']['people_detected_photos']}/{report['dataset']['photos']}. Ces proportions sont une couverture, pas une précision mesurée : les visages et boîtes n’ont pas été annotés manuellement.", '',
            '| Sous-groupe (scènes informatives) | CLIP : variante exacte | SigLIP 2 | DINOv3 |','|---|---:|---:|---:|']
    for group,title in [('faces_detected','Au moins une retenue avec visage détecté'),('multiple_people','Au moins une retenue avec plusieurs personnes détectées'),('off_center_person','Au moins une retenue avec personne principale décentrée'),('low_sharpness','Au moins une retenue dans le quartile de faible netteté')]:
        a=models['clip']['subgroups'][group]
        lines.append(f"| {title} ({a['scenes']}) | {a['top1_correct']}/{a['scenes']} ({a['top1']:.1%}) | {models['siglip2']['subgroups'][group]['top1']:.1%} | {models['dinov3']['subgroups'][group]['top1']:.1%} |")
    lines += ['',
            'Les sous-groupes se recouvrent. Une réussite signifie choisir une photo livrée dans la scène ; elle ne prouve pas que le modèle reconnaît les yeux fermés, comprend une interaction entre personnes ou distingue le flou voulu du flou accidentel. Les descripteurs spatiaux par quadrants et les mesures spécialisées n’apportent pas de gain systématique dans cette expérience.',
            f"La simple règle « choisir la plus nette » atteint {report['reference_baselines']['sharpest_top1']['top1']:.1%} de variantes exactes ; le hasard uniforme dans chaque scène attendrait {report['reference_baselines']['random_top1_expected']:.1%}. Ces points de comparaison permettent d’évaluer le gain des modèles appris.", '',
            '## Incertitude et portée','',
            '- Les résultats de toutes les configurations ont été examinés : il manque un reportage indépendant pour confirmer le gagnant. Les intervalles ci-dessous ne corrigent pas cette sélection multiple.',
            '- Les intervalles sont un bootstrap apparié de scènes, pas une estimation de la variabilité entre photographes ou entre reportages.',
            '- Yeux, visages et personnes n’ont pas d’annotations manuelles exhaustives ; leur précision de détection ne peut pas être déduite de ce test. Leur utilité est mesurée indirectement par l’accord avec les photos livrées.',
            '- « Faible netteté » signifie quartile inférieur de la mesure technique. Ce groupe ne distingue pas flou artistique, mouvement voulu et mise au point manquée.',
            '- La position des personnes désigne leur position et leur taille dans l’image ; aucune reconstruction 3D ni identification des personnes.', '',
            '| Configuration | Gain de variante exacte face à CLIP | Intervalle exploratoire 95 % |','|---|---:|---:|']
    for name in selected:
        d=models[name]['top1_delta_vs_clip']
        lines.append(f"| {name} | {100*d['difference']:+.1f} points | [{100*d['ci95'][0]:+.1f} ; {100*d['ci95'][1]:+.1f}] |")
    lines+=['','## Temps CPU mesurés','', '| Étape | Médiane par photo | Cumul sur le reportage |','|---|---:|---:|']
    for name,t in report['timing_seconds_per_photo'].items():
        lines.append(f"| {name} | {1000*t['median']:.0f} ms | {t['total']:.1f} s |")
    lines+=['','CLIP et SigLIP sont quantifiés int8 ; DINOv3 est en float32. ONNX utilise deux threads par modèle. Les temps sont séquentiels dans le même processus et incluent le prétraitement propre à chaque encodeur. Le chargement initial des modèles est exclu.','',
            '## Reproduction','',
            'Les poids publics et leurs révisions/empreintes sont sous ../selection-models/. Les dépendances sont isolées dans ../selection-models/deps/. Les photos ne sont pas téléversées.', '',
            '```powershell',
            '.\\.venv\\Scripts\\python.exe -m pip install --target test-output/selection-models/deps -r scripts/requirements-selection-benchmark.txt',
            '.\\.venv\\Scripts\\python.exe scripts/prepare_selection_benchmark.py',
            '.\\.venv\\Scripts\\python.exe scripts/compare_selection_models.py extract --rush "CHEMIN_RUSH" --kept "CHEMIN_RETENUES"',
            '.\\.venv\\Scripts\\python.exe scripts/compare_selection_models.py evaluate',
            '.\\.venv\\Scripts\\python.exe scripts/compare_selection_models.py hybrids',
            '.\\.venv\\Scripts\\python.exe scripts/compare_selection_models.py tuned',
            '.\\.venv\\Scripts\\python.exe scripts/selection_benchmark_report.py',
            '```','']
    (OUTPUT/'rapport.md').write_text('\n'.join(lines),encoding='utf-8')
    overview()
    # Actual disagreements for review, chosen deterministically across scenes.
    info, records, vectors, truth, order = load_data(OUTPUT)
    z=np.load(OUTPUT/'predictions.npz')
    labels=z['labels']
    winner=max(models,key=lambda k:models[k]['variants']['top1'])
    scenes=[]
    for label in np.unique(labels):
        ix=np.where(labels==label)[0]
        if not truth[ix].any() or truth[ix].all(): continue
        a=ix[np.argmax(z['clip'][ix])]; b=ix[np.argmax(z[winner][ix])]
        if a!=b: scenes.append((int(label),ix,a,b))
    (OUTPUT/'review-images').mkdir(exist_ok=True)
    cards=[]
    for label,ix,a,b in scenes[:30]:
        entries=[]
        chosen=list(dict.fromkeys([a,b]+list(ix[truth[ix]][:2])))
        for i in chosen:
            path=Path(info['paths'][order[i]])
            thumbnail=OUTPUT/'review-images'/f'{order[i]:05}.jpg'
            if not thumbnail.exists():
                with Image.open(path) as src:
                    image=ImageOps.exif_transpose(src).convert('RGB')
                    image.thumbnail((700,500)); image.save(thumbnail,quality=90)
            caption=path.name+(' — retenue photographe' if truth[i] else ' — non retenue')+(' — choix CLIP' if i==a else '')+(' — choix candidat' if i==b else '')
            entries.append(f'<figure><img src="review-images/{thumbnail.name}"><figcaption>{html.escape(caption)}</figcaption></figure>')
        cards.append(f'<section><h2>Scène {label} · {len(ix)} photos</h2><div>'+''.join(entries)+'</div></section>')
    page='<!doctype html><html lang="fr"><meta charset="utf-8"><title>Comparaison des variantes</title><style>body{font:16px system-ui;background:#141719;color:#eee;margin:32px}section{margin:35px 0}section div{display:flex;flex-wrap:wrap;gap:16px}figure{margin:0;width:420px}img{max-width:100%;height:290px;object-fit:contain;background:#080808}figcaption{padding:10px;font-size:14px}p{max-width:1000px;line-height:1.6}</style><h1>Choix des variantes : exemples réels</h1><p>Candidat ayant le meilleur taux de variante exacte dans ce test exploratoire : '+html.escape(winner)+'. Les 30 premières scènes où il diffère de CLIP sont montrées dans l’ordre chronologique, sans sélectionner uniquement ses réussites. Aucune de ces scènes n’a servi à entraîner le modèle qui l’a évaluée. Cela ne constitue pas une validation sur un autre reportage.</p>'+''.join(cards)+'</html>'
    (OUTPUT/'variantes.html').write_text(page,encoding='utf-8')
    # Balanced illustration of disagreements, separate from chronological HTML review.
    chosen_scenes=[]
    for outcome in [(False,True),(True,False),(False,False)]:
        chosen_scenes += [s for s in scenes if (bool(truth[s[2]]),bool(truth[s[3]]))==outcome][:2]
    board=Image.new('RGB',(1200,310*len(chosen_scenes)), '#17191c')
    draw=ImageDraw.Draw(board)
    for row,(label,ix,a,b) in enumerate(chosen_scenes):
        for col,i in enumerate([a,b,ix[truth[ix]][0]]):
            path=Path(info['paths'][order[i]])
            with Image.open(path) as src:
                image=ImageOps.exif_transpose(src).convert('RGB'); image.thumbnail((390,265))
            board.paste(image,(col*400,row*310))
            role=['CLIP',winner,'Photographe'][col]
            draw.text((col*400+4,row*310+270),f"Scene {label} - {role}: {path.name}",fill='white')
            draw.text((col*400+4,row*310+287),'Retenue' if truth[i] else 'Non retenue',fill='#71e0af' if truth[i] else '#ff9797')
    board.save(OUTPUT/'comparaison-variantes.jpg',quality=92)
    print('Written rapport.md, comparison.csv, variantes.html. Candidate:',winner)


if __name__=='__main__':
    if '--overview' in sys.argv: overview()
    else: main()
