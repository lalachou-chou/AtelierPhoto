"""Evaluate the frozen local VLM experiment, including invalid answers and order effects."""
import csv
import html
import json
import math
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.benchmark_visual_comparator import OUT, OLD, DINO, assets, consensus, dump, native_image
import numpy as np


def wilson(correct,total):
    if not total: return [0.,1.]
    p=correct/total; z=1.959963984540054; d=1+z*z/total
    center=(p+z*z/(2*total))/d
    half=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/d
    return [center-half,center+half]


def main():
    protocol=json.loads((OUT/'protocol.json').read_text(encoding='utf8'))
    data,z=assets(); truth=set(data['truth_indices']); rows=[]
    baseline={int(original):float(score) for original,score in zip(z['order'],z['small_224'])}
    clipz=np.load(OLD/'predictions.npz')
    clip={int(original):float(score) for original,score in zip(clipz['order'],clipz['clip'])}
    masks={'faces_detected':{},'multiple_people':{},'off_center_person':{}}
    sharp={}
    for index in range(len(data['paths'])):
        with np.load(OLD/'cache'/f'{index:05}.npz') as cache:
            meta=json.loads(str(cache['metadata']))
            masks['faces_detected'][index]=bool(cache['face'][0]>0)
            person=cache['people']
            masks['multiple_people'][index]=bool(person[0]>=2)
            masks['off_center_person'][index]=bool(person[0]>0 and abs(person[1]+person[3]/2-.5)>.2)
            from atelier import selection
            sharp[index]=float(selection.tech_vector(meta['stats'])[3])
    cutoff=float(np.quantile(list(sharp.values()),.25))
    masks['low_sharpness']={i:v<=cutoff for i,v in sharp.items()}
    for scene in protocol['scenes']:
        label=scene['scene']; indices=scene['indices']
        def response(stage,required=True):
            path=OUT/'responses'/f'{label:03}-{stage}.json'
            if not path.exists():
                if required: raise RuntimeError(f'Incomplete benchmark: scene {label}, {stage}')
                return {'valid':False,'ranking':[],'seconds':0.}
            return json.loads(path.read_text(encoding='utf8'))
        f=response('forward'); r=response('reverse'); d=response('detail',f['valid'] and r['valid'])
        combined=consensus(f['ranking'],r['ranking']) if f['valid'] and r['valid'] else []
        detailed=d['ranking']+[i for i in combined if i not in d['ranking']] if d['valid'] else []
        rankings={'dino_small224':sorted(indices,key=lambda i:-baseline[i]),
                  'clip':sorted(indices,key=lambda i:-clip[i]),
                  'qwen_forward':f['ranking'],'qwen_reverse':r['ranking'],
                  'qwen_consensus':combined,'qwen_detail':detailed}
        row={'scene':label,'n':len(indices),'indices':indices,'retained':[i for i in indices if i in truth],
             'rankings':rankings,
             'top1':{k:bool(v and v[0] in truth) for k,v in rankings.items()},
             'top2':{k:bool(set(v[:2])&truth) for k,v in rankings.items()},
             'top3':{k:bool(set(v[:3])&truth) for k,v in rankings.items()},
             'valid':{k:bool(v) for k,v in rankings.items()},
             'agreement':bool(f['valid'] and r['valid'] and f['ranking'][0]==r['ranking'][0]),
             'group_type':f.get('answer',{}).get('group_type'),
             'group_type_finalists_only':bool(f.get('rounds')),
             'uncertain':f.get('answer',{}).get('uncertain'),
             'reason_forward':f.get('answer',{}).get('reason'),
             'reason_detail':d.get('answer',{}).get('reason'),
             'seconds':{'qwen_forward':f['seconds'],'qwen_reverse':r['seconds'],
                        'qwen_consensus':f['seconds']+r['seconds'],
                        'qwen_detail':f['seconds']+r['seconds']+d['seconds']},
             'subgroups':{k:any(mask[i] for i in indices if i in truth) for k,mask in masks.items()}}
        rows.append(row)
    assert len(rows)==101
    names=list(rows[0]['rankings']); models={}
    for name in names:
        correct=sum(r['top1'][name] for r in rows)
        diff=np.array([int(r['top1'][name])-int(r['top1']['dino_small224']) for r in rows])
        rng=np.random.default_rng(20261030)
        boot=diff[rng.integers(0,len(rows),(5000,len(rows)))].mean(1)
        models[name]={'top1_correct':correct,'top1':correct/len(rows),
            'top2':sum(r['top2'][name] for r in rows)/len(rows),
            'top3':sum(r['top3'][name] for r in rows)/len(rows),
            'valid':sum(r['valid'][name] for r in rows),
            'wilson95':wilson(correct,len(rows)),
            'delta_vs_dino_points':float(diff.mean()*100),
            'paired_bootstrap_ci95_points':(100*np.quantile(boot,[.025,.975])).tolist(),
            'above75_observed':correct/len(rows)>.75,
            'subgroups':{k:{'scenes':sum(r['subgroups'][k] for r in rows),
                            'correct':sum(r['top1'][name] for r in rows if r['subgroups'][k])} for k in masks},
            'by_size':{title:{'scenes':sum(lo<=r['n']<=hi for r in rows),
                             'correct':sum(r['top1'][name] for r in rows if lo<=r['n']<=hi)}
                       for title,lo,hi in [('2-4',2,4),('5-10',5,10),('11+',11,1000)]}}
        if name.startswith('qwen'):
            times=[r['seconds'][name] for r in rows]
            models[name]['timing_seconds']={'median_per_scene':float(np.median(times)),'sum':float(sum(times))}
    agree=[r for r in rows if r['agreement']]
    stable={'scenes':len(agree),'coverage':len(agree)/len(rows),
            'correct':sum(r['top1']['qwen_forward'] for r in agree),
            'accuracy':sum(r['top1']['qwen_forward'] for r in agree)/max(1,len(agree))}
    calls=[json.loads(p.read_text(encoding='utf8')) for p in (OUT/'responses').glob('*.json')]
    actual=[c for c in calls if 'raw' in c]
    sanity=json.loads((OUT/'sanity-multi-image.json').read_text(encoding='utf8'))
    sanity_ok=all([[item['color'],item['shape']] for item in json.loads(s['raw']['message']['content'])['images']]==s['expected'] for s in sanity)
    direct=[row for row in rows if row['n']<=8]
    result={'scenes':len(rows),'evaluated_photos':len(set(i for r in rows for i in r['indices'])),
            'models':models,'order_agreement':stable,'scene_results':rows,
            'diagnostics':{'random_top1_expectation':float(np.mean([len(row['retained'])/row['n'] for row in rows])),
                'multi_image_sanity_passed':sanity_ok,
                'direct_comparison_scenes':len(direct),'direct_order_agreement':sum(row['agreement'] for row in direct),
                'first_presented_candidate_chosen':sum(c['valid'] and c['answer']['ranking'][0]==1 for c in actual),
                'uniform_first_position_expectation':sum(1/len(c['indices']) for c in actual)},
            'calls':{'count':len(actual),'invalid':sum(not c['valid'] for c in actual),
                     'max_prompt_tokens':max(c['raw'].get('prompt_eval_count',0) for c in actual),
                     'total_inference_seconds':sum(c['seconds'] for c in actual)},
            'audit':json.loads((OUT/'audit/observations.json').read_text(encoding='utf8')),
            'protocol':protocol,'runtime':json.loads((OUT/'runtime.json').read_text(encoding='utf8'))}
    assert models['dino_small224']['top1_correct']==40
    assert models['clip']['top1_correct']==32
    dump(OUT/'results.json',result)
    with (OUT/'comparison.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream); writer.writerow(['model','top1_correct','scenes','top1','top2','top3','valid','delta_vs_dino_points'])
        for key,m in models.items(): writer.writerow([key,m['top1_correct'],len(rows),m['top1'],m['top2'],m['top3'],m['valid'],m['delta_vs_dino_points']])
    report(result); examples(result,data)
    print(json.dumps({'models':{k:{j:v for j,v in m.items() if j in ['top1_correct','top2','top3','valid']} for k,m in models.items()},'stability':stable},indent=2))


LABELS={'dino_small224':'DINOv3 Small 224, référence','clip':'CLIP, référence',
        'qwen_forward':'Qwen, premier ordre (principal)','qwen_reverse':'Qwen, ordre inversé',
        'qwen_consensus':'Qwen, combinaison des deux classements','qwen_detail':'Qwen, combinaison puis détails des trois finalistes'}


def report(r):
    models=r['models']; stable=r['order_agreement']
    lines=['# Comparaison visuelle des variantes avec Qwen3-VL','',
        f"{r['scenes']} scènes historiques inchangées, {r['evaluated_photos']} photos examinées. Objectif : plus de 75 % de bonnes variantes en tête, soit au moins 76 scènes sur 101.",'',
        f"L’objectif n’est pas atteint : le comparateur principal retrouve {models['qwen_forward']['top1_correct']} choix livrés en tête, contre {models['dino_small224']['top1_correct']} pour DINOv3. La combinaison puis les détails en retrouvent {models['qwen_detail']['top1_correct']}. Cette configuration ne justifie pas une intégration comme arbitre automatique.",'',
        'Qwen3-VL 8B Instruct Q4_K_M, exécuté localement avec Ollama sur RTX 4080 SUPER. Les choix du photographe, les noms de fichiers et les scores des anciens modèles ne sont pas présentés à Qwen. Aucune photo envoyée à un service externe.','',
        '| Méthode | Bonne variante en tête | Dans les deux premières | Dans les trois premières | Réponses valides |',
        '|---|---:|---:|---:|---:|']
    for key,m in models.items():
        lines.append(f"| {LABELS[key]} | {m['top1_correct']}/101 ({m['top1']:.1%}) | {m['top2']:.1%} | {m['top3']:.1%} | {m['valid']}/101 |")
    lines+=['','## Protocole','',
        '- Ordre initial aléatoire fixé avant les résultats ; second passage en ordre inverse. À chaque appel, les identifiants des candidats sont renumérotés et les réponses sont remappées vers les fichiers originaux.',
        '- Vues globales jusqu’à 1 280 pixels de grand côté, proportions conservées. Maximum huit candidats par appel. Pour les groupes plus grands, les deux premiers de chaque lot passent au tour suivant, jusqu’à une finale de huit candidats ou moins. Aucun candidat n’est présélectionné par DINOv3.',
        '- La combinaison additionne les positions dans les deux classements ; une égalité est départagée par le premier passage. L’ordre de présentation influence aussi la composition des lots des grands groupes.',
        '- Le passage détaillé réexamine les trois premiers de cette combinaison, dans un ordre à nouveau mélangé : vues globales jusqu’à 1 600 pixels et planches de quatre visages détectés au maximum. Sans visage détecté, seule la vue globale est fournie.',
        '- Les réponses invalides comptent comme des échecs. Aucune exclusion de scène en fonction des résultats. Aucun ajustement de prompt ou de réglage à partir des choix du photographe.',
        '- Les groupes sans photo livrée ou ne contenant que des livrées ne sont pas testés : cet essai mesure le classement de variantes, pas une sélection autonome complète de toutes les photos du rush.',
        '- Le prétest technique v1 sur deux images est conservé séparément ; il a motivé des lots limités à huit candidats et des images plus grandes. Les résultats v2 utilisent tous le même protocole.','',
        '## Stabilité et présélection','',
        f"Le premier choix reste identique entre les deux ordres dans {stable['scenes']}/101 scènes ({stable['coverage']:.1%}). Sur ce sous-ensemble seulement, {stable['correct']} choix correspondent aux livrées ({stable['accuracy']:.1%}). Cette précision conditionnelle ne remplace pas l’objectif sur toutes les scènes.",'',
        f"Même parmi les {r['diagnostics']['direct_comparison_scenes']} groupes de huit candidats ou moins (sans tournoi), seuls {r['diagnostics']['direct_order_agreement']} premiers choix restent identiques. L’instabilité ne s’explique donc pas uniquement par les lots des grands groupes.",'',
        f"Le modèle place le premier candidat présenté en tête dans {r['diagnostics']['first_presented_candidate_chosen']}/{r['calls']['count']} appels, contre une espérance de {r['diagnostics']['uniform_first_position_expectation']:.1f} avec un choix uniforme par appel. Ces appels sont dépendants ; c’est un diagnostic descriptif de sensibilité à la position, pas un test statistique indépendant.",'',
        f"Le contrôle technique avec trois formes colorées distinctes est réussi dans les deux ordres : {r['diagnostics']['multi_image_sanity_passed']}. Il vérifie la transmission multi-image élémentaire, pas la fiabilité de l’analyse de photographies complexes. La réussite attendue d’un choix uniforme dans chaque scène est de {r['diagnostics']['random_top1_expectation']:.1%}.",'',
        f"La liste des trois finalistes contient une photo livrée dans {models['qwen_consensus']['top3']:.1%} des scènes. Ce taux est le plafond du passage détaillé avec cette présélection ; un examen plus fin ne peut récupérer une photo déjà écartée.",'',
        '## Sous-groupes','',
        '| Scènes contenant une retenue… | DINO Small 224 | Qwen principal | Qwen avec détails |','|---|---:|---:|---:|']
    for group,label in [('faces_detected','avec visage détecté'),('multiple_people','avec plusieurs personnes'),('off_center_person','avec personne décentrée'),('low_sharpness','dans le quartile de faible netteté')]:
        cells=[]
        for key in ['dino_small224','qwen_forward','qwen_detail']:
            a=models[key]['subgroups'][group]; cells.append(f"{a['correct']}/{a['scenes']}")
        lines.append(f"| {label} | "+' | '.join(cells)+' |')
    lines+=['','Sous-groupes issus des détecteurs précédents, imparfaits et recouvrants. La faible netteté n’est pas une annotation du flou artistique.','',
            '## Incertitude','',
            '| Méthode | Intervalle Wilson 95 % du taux | Écart avec DINO | Intervalle apparié exploratoire 95 % |','|---|---:|---:|---:|']
    for key,m in models.items():
        a,b=m['wilson95']; c,d=m['paired_bootstrap_ci95_points']
        lines.append(f"| {LABELS[key]} | [{a:.1%} ; {b:.1%}] | {m['delta_vs_dino_points']:+.1f} points | [{c:+.1f} ; {d:+.1f}] |")
    lines+=['','Bootstrap apparié de scènes, 5 000 tirages. Ces intervalles ne corrigent ni les comparaisons multiples, ni la dépendance entre scènes du même mariage. Ce reportage a déjà servi à plusieurs explorations ; une confirmation sur un autre reportage reste nécessaire.','',
            '## Audit des groupes','',r['audit']['conclusion'],'',
            'Cet audit décrit les cadrages et les moments ; il ne fournit pas une vérité terrain des goûts du photographe. L’échantillon est stratifié par taille et inclut le plus grand groupe. Il ne permet pas d’estimer la proportion de groupes problématiques dans l’ensemble du rush.','',
            '| Scène | Lecture visuelle | Observation |','|---|---|---|']
    for a in r['audit']['observations']: lines.append(f"| {a['scene']} | {a['type']} | {a['note']} |")
    lines+=['','## Temps et reproductibilité','',
            f"{r['calls']['count']} appels locaux, {r['calls']['invalid']} réponses invalides ; {r['calls']['total_inference_seconds']/60:.1f} minutes cumulées dans les appels (chargement éventuel du modèle inclus, préparation des images exclue). Maximum observé : {r['calls']['max_prompt_tokens']} tokens d’entrée pour un contexte de 16 384.",'',
            '| Méthode | Temps médian par scène |','|---|---:|']
    for key,m in models.items():
        if 'timing_seconds' in m: lines.append(f"| {LABELS[key]} | {m['timing_seconds']['median_per_scene']:.1f} s |")
    lines+=['','Ces temps GPU par scène ne sont pas comparables directement aux anciens temps CPU par image. La combinaison nécessite les deux passages ; le résultat détaillé inclut les trois étapes.','',
            'Le modèle fournit des justifications, mais celles-ci peuvent contenir des détails inventés ou des affirmations trop certaines. Seule la concordance mesurée avec les choix livrés constitue le résultat du test. Le modèle reste généraliste : aucun profil personnalisé n’a été appris dans cet essai.','',
            'Fichiers : `protocol.json`, `runtime.json` (empreinte des poids), `responses/` (réponses brutes et ordres), `results.json`, `comparison.csv`, `audit/observations.json`, `comparaison.html`.','',
            '```powershell',
            '.\\.venv\\Scripts\\python.exe scripts/benchmark_visual_comparator.py prepare',
            '.\\.venv\\Scripts\\python.exe scripts/benchmark_visual_comparator.py run',
            '.\\.venv\\Scripts\\python.exe scripts/report_visual_comparator.py',
            '```','']
    (OUT/'rapport.md').write_text('\n'.join(lines),encoding='utf8')


def examples(r,data):
    directory=OUT/'review-images'; directory.mkdir(exist_ok=True)
    sections=[]
    for row in r['scene_results']:
        keys=['dino_small224','qwen_forward','qwen_detail']
        heads={k:row['rankings'][k][0] if row['rankings'][k] else None for k in keys}
        indices=list(dict.fromkeys([i for i in heads.values() if i is not None]+row['retained']))
        cards=[]
        for index in indices:
            path=directory/f'{index:05}.jpg'
            if not path.exists():
                image=native_image(data['paths'][index]); image.thumbnail((900,700)); image.save(path,quality=92)
            who=', '.join(LABELS[k] for k,v in heads.items() if v==index)
            title=Path(data['paths'][index]).name+(' — LIVRÉE' if index in row['retained'] else ' — non livrée')
            cards.append(f'<figure><img loading="lazy" src="review-images/{path.name}"><figcaption>{html.escape(title)}<br>{html.escape(who)}</figcaption></figure>')
        reasons=html.escape(row.get('reason_forward') or '')
        sections.append(f'<section><h2>Scène {row["scene"]} · {row["n"]} photos</h2><div>'+''.join(cards)+f'</div><p>Justification Qwen (non vérifiée) : {reasons}</p></section>')
    page='<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Comparaison visuelle des variantes</title><style>body{font:16px system-ui;background:#181a1d;color:#eee;margin:30px}p{max-width:1100px;line-height:1.6}section{margin:38px 0;border-top:1px solid #444}section div{display:flex;flex-wrap:wrap;gap:16px}figure{margin:0;width:360px}img{width:100%;height:290px;object-fit:contain;background:#090909}figcaption{padding:10px;font-size:14px}</style><h1>DINOv3 et Qwen3-VL : les 101 scènes</h1><p>Toutes les scènes évaluées, sans filtrage par réussite. Chaque scène montre les premiers choix des trois méthodes et toutes les photos effectivement livrées dans cette scène. Les justifications sont des sorties du modèle, pas des observations validées.</p>'+''.join(sections)+'</html>'
    (OUT/'comparaison.html').write_text(page,encoding='utf8')


if __name__=='__main__': main()
