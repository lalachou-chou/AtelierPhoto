"""Controlled DINOv3 Small 224 vs448: same native RGB pixels, frozen evaluation.

No network, no original edits, no production profile changes. All photo sources
are restricted to the existing benchmark's RUSH; delivery labels are unchanged.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.benchmark_dino_detail import Dino, native_image, PREVIOUS, OUTPUT as PRIOR, metrics
from scripts.compare_selection_models import ASSETS, load_data, split_fold, chronological_folds, variant_results
from atelier import selection
from atelier.analysis import technical
import numpy as np

OUT=ROOT/'test-output/selection-resolution-controlled'
GRID=[.0001,.001,.01,.1,1.]


def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf8'); temp.replace(path)


def protocol():
    spec={'version':1,'model':'DINOv3 ViT-S/16, float32, frozen',
          'weights':json.loads((ASSETS/'dinov3/manifest.json').read_text()),
          'preprocessor':json.loads((ASSETS/'dinov3/preprocessor_config.json').read_text()),
          'dataset_sha256':hashlib.sha256((PREVIOUS/'dataset.json').read_bytes()).hexdigest(),
          'reference_predictions_sha256':hashlib.sha256((PREVIOUS/'predictions.npz').read_bytes()).hexdigest(),
          'preparation':'Decode original once, EXIF transpose, RGB, ICC->sRGB if present. The SAME native PIL image is independently bilinearly resized directly to224x224 and448x448. Same RGB normalization and global pooler output; no crop, no extra view. Square stretching retained in both conditions to change only resolution.',
          'primary':'Separately tuned regularization: five outer scene-disjoint chronological blocks, adjacent scene purged; three inner blocks, identical C grid, maximize inner top1. Fit all scalers on training only.',
          'grid':GRID,'secondary':'Fixed C=.02 on both resolutions; previous preview224 re-evaluated to isolate preprocessing effects.',
          'features':'Same technical/context16 features +384-dimensional global embedding for every condition.',
          'timing':'Two ONNX CPU threads. Separate isolated timing on24 evenly spaced originals; alternating resolution order; warmup excluded.',
          'limitations':'Same previously explored wedding, not independent reportage validation. No manual artistic-blur labels. Results conditional on this square global pooling pipeline.'}
    signature=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
    path=OUT/'protocol.json'
    if path.exists(): assert json.loads(path.read_text(encoding='utf8'))==spec
    else: save(path,spec)
    return spec,signature


def extract(args):
    _,key=protocol(); (OUT/'cache').mkdir(exist_ok=True)
    data=json.loads((PREVIOUS/'dataset.json').read_text(encoding='utf8'))
    encoder=Dino('small'); done=0; begin=time.perf_counter()
    for i,source in enumerate(data['paths']):
        if i<args.start or (args.end is not None and i>=args.end): continue
        path=Path(source); stat=path.stat(); stamp=[str(path),stat.st_size,stat.st_mtime_ns]
        target=OUT/'cache'/f'{i:05}.npz'
        if target.exists():
            with np.load(target) as z: m=json.loads(str(z['metadata']))
            assert m['signature']==key and m['stamp']==stamp
            continue
        with np.load(PREVIOUS/'cache'/f'{i:05}.npz') as z: old=json.loads(str(z['metadata']))
        assert old['stamp']==stamp, f'Source changed: {path}'
        start=time.perf_counter(); image=native_image(path); decode=time.perf_counter()-start
        pixels_sha=hashlib.sha256(image.tobytes()).hexdigest()
        vectors={}; seconds={}
        for size in ([224,448] if i%2==0 else [448,224]):
            start=time.perf_counter(); vectors[f'native_{size}']=encoder.encode(image,size)
            seconds[str(size)]=time.perf_counter()-start
        with np.load(PRIOR/'cache'/f'{i:05}.npz') as previous:
            pm=json.loads(str(previous['metadata'])); assert pm['stamp']==stamp
            repeated448=float(np.max(np.abs(previous['small_448']-vectors['native_448'])))
        meta={'stamp':stamp,'signature':key,'native_size':list(image.size),
              'prepared_pixels_sha256':pixels_sha,'decode_seconds':decode,'seconds':seconds,
              'max_abs_delta_previous448':repeated448}
        temp=target.with_suffix('.tmp')
        with temp.open('wb') as f: np.savez_compressed(f,metadata=json.dumps(meta),**vectors)
        temp.replace(target); image.close(); done+=1
        if done%40==0 or i==len(data['paths'])-1:
            print(f'index {i+1}/{len(data["paths"])} | new {done} | {(time.perf_counter()-begin)/done:.2f}s/photo',flush=True)
        if args.limit and done>=args.limit: break


def fit_scores(x,truth,labels,folds):
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    fixed=np.zeros(len(truth)); tuned=fixed.copy(); logs=[]
    def model(c): return LogisticRegression(C=c,solver='lbfgs',max_iter=700,tol=1e-7)
    for fold in range(5):
        train,test=split_fold(labels,folds,fold)
        scaler=StandardScaler().fit(x[train]); z=scaler.transform(x)
        fixed[test]=model(.02).fit(z[train],truth[train]).decision_function(z[test])
        train_ix=np.where(train)[0]; inner=chronological_folds(labels[train],3)
        accuracy=[]
        for c in GRID:
            checks=[]
            for inner_fold in range(3):
                fit,val=split_fold(labels[train],inner,inner_fold)
                fi,vi=train_ix[fit],train_ix[val]
                assert not np.intersect1d(vi,np.where(test)[0]).size
                sc=StandardScaler().fit(x[fi])
                pred=model(c).fit(sc.transform(x[fi]),truth[fi]).decision_function(sc.transform(x[vi]))
                checks.extend(row['top1'] for row in variant_results(pred,truth[vi],labels[vi]))
            accuracy.append(float(np.mean(checks)))
        c=GRID[int(np.argmax(accuracy))]
        tuned[test]=model(c).fit(z[train],truth[train]).decision_function(z[test])
        logs.append({'fold':fold,'train':int(train.sum()),'test':int(test.sum()),'C':c,'inner_top1':accuracy})
    return fixed,tuned,logs


def evaluate(args):
    from threadpoolctl import threadpool_limits
    threadpool_limits(limits=2)
    _,key=protocol(); info,records,old,truth,order=load_data(PREVIOUS)
    native={224:[],448:[]}; metadata=[]
    for i in order:
        with np.load(OUT/'cache'/f'{i:05}.npz') as z:
            m=json.loads(str(z['metadata'])); assert m['signature']==key
            metadata.append(m)
            for size in native: native[size].append(z[f'native_{size}'])
    native={s:np.asarray(v) for s,v in native.items()}
    with np.load(PREVIOUS/'predictions.npz') as z:
        labels,folds=z['labels'],z['folds']
        assert np.array_equal(order,z['order']) and np.array_equal(truth,z['truth'])
    tech=np.array([selection.tech_vector(r['stats']) for r in records])
    common=np.c_[tech,selection.context(tech,[r['time'] for r in records],old['clip'],labels)]
    blocked=np.array([technical(r['stats'],.5,False)[0]=='reject' for r in records])
    masks={'faces_detected':old['face'][:,0]>0,'multiple_people':old['people'][:,0]>=2,
           'off_center_person':(old['people'][:,0]>0)&(np.abs(old['people'][:,1]+old['people'][:,3]/2-.5)>.2),
           'low_sharpness':tech[:,3]<=np.quantile(tech[:,3],.25)}
    saved={'order':order,'truth':truth,'labels':labels,'folds':folds}; results={}
    for name,embedding in [('preview224',old['dinov3']),('native224',native[224]),('native448',native[448])]:
        fixed,tuned,logs=fit_scores(np.c_[common,embedding],truth,labels,folds)
        for kind,score in [('fixed',fixed),('tuned',tuned)]:
            model=name+'_'+kind; saved[model]=score
            results[model]=metrics(score,truth,labels,folds,old['clip'],blocked,masks)
            if kind=='tuned': results[model]['tuning']=logs
            print(model,'top1',results[model]['variants']['top1_correct'],'exact',results[model]['exact_matches'],flush=True)
    comparisons={}
    for name,a,b in [('resolution_tuned','native448_tuned','native224_tuned'),
                     ('resolution_fixed','native448_fixed','native224_fixed'),
                     ('preparation_tuned','native224_tuned','preview224_tuned'),
                     ('preparation_fixed','native224_fixed','preview224_fixed')]:
        ra=results[a]['scene_results']; rb=results[b]['scene_results']
        assert [r['scene'] for r in ra]==[r['scene'] for r in rb]
        diff=np.array([int(x['top1'])-int(y['top1']) for x,y in zip(ra,rb)])
        boot=diff[np.random.default_rng(20261030).integers(0,len(diff),(5000,len(diff)))].mean(1)
        comparisons[name]={'a':a,'b':b,'delta_points':float(diff.mean()*100),
                           'ci95_points':(100*np.quantile(boot,[.025,.975])).tolist(),
                           'wins':int((diff==1).sum()),'losses':int((diff==-1).sum())}
    cos=np.sum(native[224]*old['dinov3'],axis=1)
    previous=json.loads((PREVIOUS/'results.json').read_text(encoding='utf8'))
    result={'dataset':previous['dataset'],'models':results,'comparisons':comparisons,
            'checks':{'photos':len(truth),'same_source_pixel_hashes':len(metadata),
                      'max_abs_delta_repeated448':max(m['max_abs_delta_previous448'] for m in metadata),
                      'preview_native224_cosine_median':float(np.median(cos)),
                      'preview_native224_cosine_min':float(cos.min())},
            'protocol':json.loads((OUT/'protocol.json').read_text(encoding='utf8'))}
    assert results['preview224_fixed']['variants']['top1_correct']==40
    assert results['preview224_tuned']['variants']['top1_correct']==38
    save(OUT/'results.json',result)
    np.savez_compressed(OUT/'predictions.npz',**saved)


def timing(args):
    protocol(); data=json.loads((PREVIOUS/'dataset.json').read_text(encoding='utf8'))
    encoder=Dino('small'); samples=[]
    for j,i in enumerate(np.linspace(0,len(data['paths'])-1,24,dtype=int)):
        start=time.perf_counter(); image=native_image(data['paths'][i]); decode=time.perf_counter()-start
        if j==0:
            for size in (224,448): encoder.encode(image,size)
        row={'index':int(i),'decode_seconds':decode}
        for size in ([224,448] if j%2==0 else [448,224]):
            start=time.perf_counter(); encoder.encode(image,size); row[str(size)]=time.perf_counter()-start
        image.close(); samples.append(row)
    save(OUT/'timing.json',{'threads':2,'provider':'CPUExecutionProvider','samples':samples,
        'median':{k:float(np.median([r[k] for r in samples])) for k in ['224','448','decode_seconds']}})
    print('Isolated timing complete',flush=True)


def report(args):
    r=json.loads((OUT/'results.json').read_text(encoding='utf8')); m=r['models']
    t=json.loads((OUT/'timing.json').read_text(encoding='utf8'))
    lines=['# DINOv3 Small : comparaison contrôlée 224 / 448','',
           '1 157 originaux du rush Carla & Ndue ; 179 originaux livrés distincts ; 101 scènes informatives. Seuls RUSH et le dossier des photos retenues sont utilisés.','',
           '## Résultat principal : réglage adapté à chaque résolution','',
           '| Entrée du modèle | Bonne variante en tête | Dans les deux premières | Choix exacts / 232 sélectionnées | Retenues + à vérifier : rappel |','|---|---:|---:|---:|---:|']
    for key,label in [('native224_tuned','224 depuis l’original'),('native448_tuned','448 depuis le même original')]:
        a=m[key]; lines.append(f"| {label} | {a['variants']['top1_correct']}/101 ({a['variants']['top1']:.1%}) | {a['variants']['top2']:.1%} | {a['exact_matches']}/232 | {a['kept_or_review_recall']:.1%} |")
    d=r['comparisons']['resolution_tuned']; lo,hi=d['ci95_points']
    lines+=['',f"Écart 448 − 224 : {d['delta_points']:+.1f} points ; intervalle apparié exploratoire à 95 % [{lo:+.1f} ; {hi:+.1f}]. Le 448 gagne {d['wins']} scènes et en perd {d['losses']} face au 224.",'',
            ('Cet intervalle contient zéro : ce test ne permet pas de conclure à un avantage fiable d’une résolution.' if lo<=0<=hi else 'L’intervalle exploratoire exclut zéro sur ce mariage ; une validation sur un autre reportage reste nécessaire.'),'',
            '## Contrôles : préparation et réglage','',
            '| Préparation et résolution | C fixe = 0,02 | C choisi sur l’apprentissage |','|---|---:|---:|']
    for key,label in [('preview224','Ancien aperçu, 224'),('native224','Original natif, 224'),('native448','Même original natif, 448')]:
        a=m[key+'_fixed']['variants']; b=m[key+'_tuned']['variants']
        lines.append(f"| {label} | {a['top1_correct']}/101 ({a['top1']:.1%}) | {b['top1_correct']}/101 ({b['top1']:.1%}) |")
    lines+=['',f"Le changement de préparation seul (224 natif − ancien aperçu224) modifie le taux de {r['comparisons']['preparation_fixed']['delta_points']:+.1f} points à C fixe et de {r['comparisons']['preparation_tuned']['delta_points']:+.1f} points après réglage interne.",'',
            'L’ancien chemin JPEG utilise le décodage réduit `draft`, puis un aperçu de 1 280 pixels maximum avec interpolation Lanczos, avant l’entrée 224 du modèle. Le nouveau chemin part des pixels natifs et redimensionne directement vers la taille du modèle.','',
            '## Sous-groupes, réglage interne','',
            '| Scènes contenant une retenue… | 224 natif | 448 natif |','|---|---:|---:|']
    for group,label in [('faces_detected','avec visage détecté'),('multiple_people','avec plusieurs personnes détectées'),('off_center_person','avec personne décentrée'),('low_sharpness','dans le quartile de faible netteté')]:
        a=m['native224_tuned']['subgroups'][group]; b=m['native448_tuned']['subgroups'][group]
        lines.append(f"| {label} | {a['top1_correct']}/{a['scenes']} | {b['top1_correct']}/{b['scenes']} |")
    lines+=['','Ces sous-groupes se recouvrent et dépendent des détecteurs précédents ; ils ne mesurent pas directement la justesse d’un jugement artistique.','',
            '## Conditions identiques','',
            '- Chaque original est décodé une seule fois, orienté suivant EXIF et converti en RGB/sRGB. Son empreinte de pixels préparés est conservée. Le même objet image fournit les deux entrées.',
            '- Deux redimensionnements directs et indépendants depuis cet original : 224 × 224 et 448 × 448. Même interpolation bilinéaire, même normalisation des couleurs, mêmes poids float32 et même sortie globale de 384 nombres. Aucune vue détaillée.',
            '- Le redimensionnement au carré conserve la déformation de proportions de la chaîne précédente, identique pour les deux conditions. Ce test ne compare pas d’autres stratégies de cadrage ou d’agrégation spatiale.',
            '- Les mêmes 16 caractéristiques techniques/contextuelles sont ajoutées aux deux résumés visuels. Même algorithme de classement, mêmes scènes, mêmes cinq blocs externes et mêmes quotas.',
            '- Pour le résultat principal, C est choisi séparément pour chaque résolution parmi 0,0001 ; 0,001 ; 0,01 ; 0,1 ; 1, à partir de trois sous-blocs internes. Chaque normalisation est ajustée uniquement sur son entraînement ; les scènes voisines des blocs de validation sont exclues.',
            '- La cible de réglage est la bonne variante en tête, pas le nombre total de choix exacts sur le reportage. Les deux mesures peuvent évoluer différemment.','',
            '## Vérifications et temps','',
            f"Contrôle historique reproduit : 40/101 à C fixe et 38/101 avec réglage interne. Le vecteur 448 recalculé diffère au maximum de {r['checks']['max_abs_delta_repeated448']:.3g} du cache précédent. Similarité cosinus médiane entre ancien aperçu224 et original224 : {r['checks']['preview_native224_cosine_median']:.6f} (minimum {r['checks']['preview_native224_cosine_min']:.6f}).",'',
            f"Chronométrage isolé, deux threads CPU, 24 originaux, ordre des résolutions alterné et préchauffage exclu : {t['median']['224']*1000:.0f} ms en 224, {t['median']['448']*1000:.0f} ms en 448, hors lecture. Décodage médian : {t['median']['decode_seconds']*1000:.0f} ms. Ces durées ne sont pas une mesure GPU.",'',
            '## Limites','',
            'Ce contrôle isole la résolution dans cette chaîne de traitement. Le mariage a déjà été utilisé pour plusieurs essais : il ne constitue pas un test indépendant de la démarche de recherche. Les blocs de test sont exclus des ajustements du modèle, mais une validation finale sur un autre reportage reste à faire. Aucun autre reportage n’a été fourni pour ce test.',
            'Les intervalles utilisent 5 000 rééchantillonnages appariés des scènes ; ils ne corrigent pas les comparaisons multiples ni la dépendance entre scènes du même mariage. Les choix livrés ne constituent pas des annotations explicites des yeux fermés, du flou artistique ou des intentions de composition.','',
            '## Reproduction','',
            'Protocole et révisions des poids : `protocol.json`. Résultats et réglages par bloc : `results.json`. Scores hors entraînement : `predictions.npz`. Vecteurs et empreintes des sources : `cache/`.','',
            '```powershell',
            '.\\.venv\\Scripts\\python.exe scripts/benchmark_resolution_controlled.py extract',
            '.\\.venv\\Scripts\\python.exe scripts/benchmark_resolution_controlled.py evaluate',
            '.\\.venv\\Scripts\\python.exe scripts/benchmark_resolution_controlled.py timing',
            '.\\.venv\\Scripts\\python.exe scripts/benchmark_resolution_controlled.py report','```','']
    (OUT/'rapport.md').write_text('\n'.join(lines),encoding='utf8')
    print('Report saved:',OUT/'rapport.md')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=['extract','evaluate','timing','report'])
    p.add_argument('--start',type=int,default=0); p.add_argument('--end',type=int); p.add_argument('--limit',type=int)
    args=p.parse_args(); globals()[args.stage](args)


if __name__=='__main__': main()
