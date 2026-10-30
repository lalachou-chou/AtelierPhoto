"""Local, reproducible selection benchmark. No production profile writes or uploads.

Dependencies live in test-output/selection-models/deps. Public weights are prepared
by prepare_selection_benchmark.py. Ground truth is matched by filename only, never
by the encoder being evaluated. Fixed CLIP scenes and identical test folds avoid
changing the task between candidates. All scalers/classifiers fit train data only.
"""
import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'test-output' / 'selection-models'
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
os.environ.setdefault('OMP_NUM_THREADS', '2')
sys.path.insert(0, str(ROOT))
sys.path.append(str(ASSETS / 'deps'))

import numpy as np
from PIL import Image
from atelier import selection
from atelier.analysis import technical
from scripts.legacy_clip import ClipEncoder
from atelier.config import discover
from atelier.imaging import as_image, capture_time, features
from atelier.pipeline import decode_for_analysis


def unit(x):
    x = np.asarray(x, dtype=np.float32)
    return x / max(float(np.linalg.norm(x)), 1e-12)


def stem(path):
    return re.sub('[^0-9a-z]', '', Path(path).stem.lower())


def dataset(rush, kept):
    paths = discover([rush])
    by_stem = {}
    for i, p in enumerate(paths):
        s = stem(p)
        if s in by_stem:
            raise ValueError('Ambiguous original filename: ' + s)
        by_stem[s] = i
    truth = set()
    unmatched = []
    pairs = []
    for p in discover([kept]):
        s = stem(p)
        candidates = [k for k in by_stem if s == k or (len(k) >= 4 and s.startswith(k))]
        if not candidates:
            unmatched.append(p)
            continue
        matched = max(candidates, key=len)
        truth.add(by_stem[matched])
        pairs.append({'original': paths[by_stem[matched]], 'delivered': p})
    return paths, truth, unmatched, pairs


class Encoder:
    def __init__(self, name):
        import onnxruntime as ort
        folder = ASSETS / name
        self.processor = json.loads((folder / 'preprocessor_config.json').read_text())
        model = folder / 'onnx' / ('vision_model_quantized.onnx' if name == 'siglip2' else 'model.onnx')
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        opts.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(model), sess_options=opts, providers=['CPUExecutionProvider'])
        self.name = name

    def encode(self, image):
        p = self.processor
        size = p['size']
        image = image.convert('RGB').resize((size['width'], size['height']), Image.Resampling(p['resample']))
        x = np.asarray(image, dtype=np.float32) * p['rescale_factor']
        x = (x - np.array(p['image_mean'], np.float32)) / np.array(p['image_std'], np.float32)
        hidden, pooled = self.session.run(['last_hidden_state', 'pooler_output'], {'pixel_values': x.transpose(2, 0, 1)[None]})
        tokens = hidden[0, 5:] if self.name == 'dinov3' else hidden[0]
        grid = tokens.reshape(14, 14, -1)
        # Quadrant pooling preserves coarse position; normalize each block separately.
        spatial = np.concatenate([unit(grid[y:y+7, z:z+7].mean((0, 1))) for y in (0, 7) for z in (0, 7)])
        return unit(pooled[0]), spatial


def sharpness(rgb):
    gray = np.asarray(Image.fromarray(rgb).convert('L'), dtype=np.float32) / 255
    if min(gray.shape) < 5:
        return -14.
    lap = -4 * gray[1:-1, 1:-1] + gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]
    return float(np.log(np.var(lap) + 1e-6))


class PhotoSignals:
    def __init__(self):
        import mediapipe as mp
        self.mp = mp
        base = mp.tasks.BaseOptions
        vision = mp.tasks.vision
        self.face = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=base(model_asset_path=str(ASSETS / 'face_landmarker.task')),
            num_faces=12, output_face_blendshapes=True,
            min_face_detection_confidence=.35, min_face_presence_confidence=.35))
        self.people = vision.ObjectDetector.create_from_options(vision.ObjectDetectorOptions(
            base_options=base(model_asset_path=str(ASSETS / 'efficientdet_lite0.tflite')),
            category_allowlist=['person'], score_threshold=.3, max_results=15))

    def extract(self, image):
        rgb = np.asarray(image.convert('RGB'))
        h, w = rgb.shape[:2]
        mpimage = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        detected = self.face.detect(mpimage)
        faces = []
        for landmarks, blend in zip(detected.face_landmarks, detected.face_blendshapes):
            xy = np.array([[p.x, p.y] for p in landmarks])
            x0, y0 = np.clip(xy.min(0), 0, 1)
            x1, y1 = np.clip(xy.max(0), 0, 1)
            crop = rgb[int(y0*h):max(int(y0*h)+1, int(y1*h)), int(x0*w):max(int(x0*w)+1, int(x1*w))]
            b = {v.category_name: float(v.score) for v in blend}
            faces.append({'box': [float(x0), float(y0), float(x1-x0), float(y1-y0)],
                          'blink': (b.get('eyeBlinkLeft', 0)+b.get('eyeBlinkRight', 0))/2,
                          'smile': (b.get('mouthSmileLeft', 0)+b.get('mouthSmileRight', 0))/2,
                          'sharp': sharpness(crop),
                          'yaw_proxy': float((landmarks[1].x - (landmarks[33].x+landmarks[263].x)/2) / max(x1-x0, 1e-6))})
        faces.sort(key=lambda f: f['box'][2]*f['box'][3], reverse=True)
        face_vec = [float(len(faces))]
        for f in (faces + [None]*3)[:3]:
            face_vec.extend(f['box']+[f['blink'], f['smile'], f['sharp'], f['yaw_proxy']] if f else [0.]*8)
        people = []
        for detection in self.people.detect(mpimage).detections:
            box = detection.bounding_box
            people.append([box.origin_x/w, box.origin_y/h, box.width/w, box.height/h, detection.categories[0].score])
        people.sort(key=lambda b: b[2]*b[3], reverse=True)
        person_vec = [float(len(people))] + [v for b in (people + [[0.]*5]*3)[:3] for v in b]
        # Spatial sharpness and light distribution, without judging blur as bad.
        small = np.asarray(image.resize((256, 256), Image.Resampling.LANCZOS))
        grid = [small[y:y+64, x:x+64] for y in range(0, 256, 64) for x in range(0, 256, 64)]
        spatial = [sharpness(g) for g in grid] + [float(g.mean()/255) for g in grid] + [w/h]
        return {'faces': faces, 'people': people}, np.array(face_vec), np.array(person_vec), np.array(spatial)


def extract(args):
    out = Path(args.output)
    cache = out / 'cache'
    cache.mkdir(parents=True, exist_ok=True)
    paths, truth, unmatched, pairs = dataset(args.rush, args.kept)
    manifest = {'rush': str(Path(args.rush).resolve()), 'kept': str(Path(args.kept).resolve()),
                'paths': paths, 'truth_indices': sorted(truth), 'unmatched_delivered': unmatched,
                'pairs': pairs, 'protocol': 'filename-only truth; all originals; fixed CLIP scenes; no OCR'}
    (out / 'dataset.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    clip = ClipEncoder()
    siglip = Encoder('siglip2')
    dino = Encoder('dinov3')
    signals = PhotoSignals()
    for i, path in enumerate(paths):
        target = cache / f'{i:05d}.npz'
        stamp = [str(path), Path(path).stat().st_size, Path(path).stat().st_mtime_ns]
        if target.exists():
            with np.load(target) as old:
                if json.loads(str(old['metadata']))['stamp'] == stamp:
                    continue
        start = time.perf_counter()
        pixels, _ = decode_for_analysis(path)
        image = as_image(pixels)
        stats = features(pixels)
        timing = {'decode_stats': time.perf_counter()-start}
        start = time.perf_counter()
        eclip = clip.encode(image)
        timing['clip'] = time.perf_counter()-start
        start = time.perf_counter()
        esiglip, ssiglip = siglip.encode(image)
        timing['siglip2'] = time.perf_counter()-start
        start = time.perf_counter()
        edino, sdino = dino.encode(image)
        timing['dinov3'] = time.perf_counter()-start
        start = time.perf_counter()
        detail, face, people, spatial = signals.extract(image)
        timing['photo_signals'] = time.perf_counter()-start
        meta = {'stamp': stamp, 'stats': stats, 'time': capture_time(path), 'detail': detail, 'seconds': timing}
        temporary = target.with_suffix('.tmp')
        with temporary.open('wb') as stream:
            np.savez_compressed(stream, metadata=json.dumps(meta), clip=eclip, siglip2=esiglip,
                                dinov3=edino, siglip2_spatial=ssiglip, dinov3_spatial=sdino,
                                face=face, people=people, spatial=spatial)
        temporary.replace(target)
        if i % 25 == 0 or i == len(paths)-1:
            print(f'Extract {i+1}/{len(paths)}; last image {sum(timing.values()):.2f}s; {Path(path).name}', flush=True)
        if args.limit and i+1 >= args.limit:
            break


def load_data(output):
    data = json.loads((output / 'dataset.json').read_text(encoding='utf-8'))
    records, vectors = [], {}
    for i in range(len(data['paths'])):
        with np.load(output / 'cache' / f'{i:05d}.npz') as item:
            records.append(json.loads(str(item['metadata'])))
            for k in item.files:
                if k != 'metadata':
                    vectors.setdefault(k, []).append(item[k])
    order = selection.chronological([r['time'] for r in records], data['paths'])
    truth = np.array([i in set(data['truth_indices']) for i in order])
    return data, [records[i] for i in order], {k: np.asarray(v)[order] for k, v in vectors.items()}, truth, np.asarray(order)


def pair_data(z, truth, labels, rng):
    pairs = []
    for label in np.unique(labels):
        good = np.where((labels == label) & truth)[0]
        bad = np.where((labels == label) & ~truth)[0]
        combos = [(a, b) for a in good for b in bad]
        if len(combos) > 30:
            combos = [combos[i] for i in rng.choice(len(combos), 30, replace=False)]
        pairs.extend(z[a] - z[b] for a, b in combos)
    if not pairs:
        raise ValueError('No training preference pairs')
    pairs = np.asarray(pairs)
    return np.concatenate([pairs, -pairs]), np.r_[np.ones(len(pairs)), np.zeros(len(pairs))]


def rerank_within_scenes(scores, pair_scores, labels):
    result = scores.copy()
    for label in np.unique(labels):
        ix = np.where(labels == label)[0]
        result[ix[np.argsort(pair_scores[ix], kind='stable')]] = np.sort(scores[ix])
    return result


def variant_results(scores, truth, labels, mask=None):
    results = []
    for label in np.unique(labels):
        ix = np.where(labels == label)[0]
        good, bad = ix[truth[ix]], ix[~truth[ix]]
        if len(good) and len(bad) and (mask is None or mask[good].any()):
            ranked = ix[np.argsort(-scores[ix], kind='stable')]
            comparisons = scores[good, None] - scores[bad][None]
            results.append({'scene': int(label), 'n': len(ix), 'top1': bool(truth[ranked[0]]),
                            'top2': bool(truth[ranked[:2]].any()),
                            'pair_accuracy': float(((comparisons > 0) + .5*(comparisons == 0)).mean())})
    return results


def summarize_variants(rows):
    return {'scenes': len(rows), 'top1_correct': sum(r['top1'] for r in rows),
            'top1': float(np.mean([r['top1'] for r in rows])) if rows else None,
            'top2': float(np.mean([r['top2'] for r in rows])) if rows else None,
            'pair_accuracy': float(np.mean([r['pair_accuracy'] for r in rows])) if rows else None}


def chronological_folds(labels, count=5):
    fold_of_scene = {int(label): min(count-1, int(np.where(labels == label)[0].mean()*count/len(labels))) for label in np.unique(labels)}
    return np.array([fold_of_scene[int(label)] for label in labels])


def split_fold(labels, folds, fold):
    test = folds == fold
    scenes = np.unique(labels[test])
    boundary = np.r_[scenes.min()-1, scenes.max()+1]
    train = (~test) & ~np.isin(labels, boundary)
    return train, test


def hybrids(args):
    """Exploratory post-comparison hypotheses; all component scores remain out-of-fold."""
    out = Path(args.output)
    report = json.loads((out/'results.json').read_text(encoding='utf-8'))
    info, records, v, truth, order = load_data(out)
    with np.load(out/'predictions.npz') as archive:
        saved = {k:archive[k] for k in archive.files}
    labels, folds = saved['labels'], saved['folds']
    tech = np.array([selection.tech_vector(r['stats']) for r in records])
    blocked = np.array([technical(r['stats'], .5, False)[0] == 'reject' for r in records])
    masks = {'faces_detected':v['face'][:,0]>0, 'multiple_people':v['people'][:,0]>=2,
             'off_center_person':(v['people'][:,0]>0)&(np.abs(v['people'][:,1]+v['people'][:,3]/2-.5)>.2),
             'portrait_format':np.array([r['stats']['aspect']<1 for r in records]),
             'landscape_format':np.array([r['stats']['aspect']>=1 for r in records]),
             'low_sharpness':tech[:,3]<=np.quantile(tech[:,3],.25)}
    for base in ['clip','clip_photo']:
        key = base+'_dino_rerank'
        score_values = rerank_within_scenes(saved[base], saved['dinov3'], labels)
        decisions = np.full(len(truth),'reject',dtype='<U6')
        for fold in range(5):
            ix = folds==fold
            decisions[ix] = selection.decide(score_values[ix],labels[ix],v['clip'][ix],.2,.2,np.where(blocked[ix])[0])
        chosen, available = decisions=='keep', decisions!='reject'
        tp = int((chosen&truth).sum())
        report['models'][key] = {'exploratory_after_initial_comparison':True,
            'selected':int(chosen.sum()), 'exact_matches':tp, 'precision':tp/max(1,int(chosen.sum())),
            'recall':tp/int(truth.sum()), 'kept_or_review_recall':float((available&truth).sum()/truth.sum()),
            'missed_kept':int((~available&truth).sum()),
            'scene_coverage':len(set(labels[chosen])&set(labels[truth]))/len(set(labels[truth])),
            'variants':summarize_variants(variant_results(score_values,truth,labels)),
            'scene_results':variant_results(score_values,truth,labels),
            'subgroups':{k:summarize_variants(variant_results(score_values,truth,labels,m)) for k,m in masks.items()}}
        saved[key] = score_values
        print(key, report['models'][key]['exact_matches'], report['models'][key]['kept_or_review_recall'],flush=True)
    report['protocol']['hybrids'] = 'Post-hoc exploratory: CLIP scene-score distributions, DINOv3 within-scene permutation. Needs independent confirmation.'
    (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    np.savez_compressed(out/'predictions.npz',**saved)


def tuned(args):
    """Nested regularization selection, solely within each outer training fold."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from threadpoolctl import threadpool_limits
    threadpool_limits(limits=2)
    out = Path(args.output)
    report = json.loads((out/'results.json').read_text(encoding='utf-8'))
    info, records, v, truth, order = load_data(out)
    with np.load(out/'predictions.npz') as archive:
        saved = {k:archive[k] for k in archive.files}
    labels, folds = saved['labels'], saved['folds']
    tech = np.array([selection.tech_vector(r['stats']) for r in records])
    ctx = selection.context(tech,[r['time'] for r in records],v['clip'],labels)
    blocked = np.array([technical(r['stats'],.5,False)[0]=='reject' for r in records])
    masks = {'faces_detected':v['face'][:,0]>0, 'multiple_people':v['people'][:,0]>=2,
             'off_center_person':(v['people'][:,0]>0)&(np.abs(v['people'][:,1]+v['people'][:,3]/2-.5)>.2),
             'portrait_format':np.array([r['stats']['aspect']<1 for r in records]),
             'landscape_format':np.array([r['stats']['aspect']>=1 for r in records]),
             'low_sharpness':tech[:,3]<=np.quantile(tech[:,3],.25)}
    for name in ['clip','siglip2','dinov3']:
        x=np.c_[tech,ctx,v[name]]
        scores=np.zeros(len(truth)); decisions=np.full(len(truth),'reject',dtype='<U6')
        choices=[]
        for fold in range(5):
            train,test=split_fold(labels,folds,fold)
            train_ix=np.where(train)[0]
            inner_folds=chronological_folds(labels[train],3)
            candidates=[]
            for c in [.0001,.001,.01,.1,1.]:
                successes=[]
                for inner in range(3):
                    fit,val=split_fold(labels[train],inner_folds,inner)
                    fit_ix,val_ix=train_ix[fit],train_ix[val]
                    scaler=StandardScaler().fit(x[fit_ix])
                    model=LogisticRegression(C=c,solver='lbfgs',max_iter=500,tol=1e-7).fit(scaler.transform(x[fit_ix]),truth[fit_ix])
                    score_values=model.decision_function(scaler.transform(x[val_ix]))
                    successes.extend(r['top1'] for r in variant_results(score_values,truth[val_ix],labels[val_ix]))
                candidates.append(float(np.mean(successes)))
            chosen=[.0001,.001,.01,.1,1.][int(np.argmax(candidates))]
            choices.append({'fold':fold,'C':chosen,'inner_top1':candidates})
            scaler=StandardScaler().fit(x[train])
            model=LogisticRegression(C=chosen,solver='lbfgs',max_iter=500,tol=1e-7).fit(scaler.transform(x[train]),truth[train])
            scores[test]=model.decision_function(scaler.transform(x[test]))
            decisions[test]=selection.decide(scores[test],labels[test],v['clip'][test],.2,.2,np.where(blocked[test])[0])
        key=name+'_nested'
        chosen,available=decisions=='keep',decisions!='reject'
        tp=int((chosen&truth).sum())
        report['models'][key]={'nested_regularization':choices,'selected':int(chosen.sum()),'exact_matches':tp,
            'precision':tp/max(1,int(chosen.sum())),'recall':tp/int(truth.sum()),
            'kept_or_review_recall':float((available&truth).sum()/truth.sum()),'missed_kept':int((~available&truth).sum()),
            'scene_coverage':len(set(labels[chosen])&set(labels[truth]))/len(set(labels[truth])),
            'variants':summarize_variants(variant_results(scores,truth,labels)),
            'scene_results':variant_results(scores,truth,labels),
            'subgroups':{k:summarize_variants(variant_results(scores,truth,labels,m)) for k,m in masks.items()}}
        saved[key]=scores
        print(key,'top1',report['models'][key]['variants']['top1'],'exact',tp,'C',[q['C'] for q in choices],flush=True)
    report['protocol']['nested']='Secondary sensitivity check: C selected among 0.0001,0.001,0.01,0.1,1 using 3 purged scene-grouped inner folds, maximizing variant top1. Outer folds unchanged and unseen for fitting or choosing C.'
    (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    np.savez_compressed(out/'predictions.npz',**saved)


def evaluate(args):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from threadpoolctl import threadpool_limits
    threadpool_limits(limits=2)
    out = Path(args.output)
    dataset_info, records, v, truth, order = load_data(out)
    times = [r['time'] for r in records]
    tech = np.array([selection.tech_vector(r['stats']) for r in records])
    labels = selection.scenes(times, v['clip'])
    context = selection.context(tech, times, v['clip'], labels)
    common = np.c_[tech, context]
    photo = np.c_[v['face'], v['people'], v['spatial']]
    # A scene belongs wholly to one chronological fold. Purge its boundary neighbours.
    folds = chronological_folds(labels)
    blocked = np.array([technical(r['stats'], .5, False)[0] == 'reject' for r in records])
    matrices = {'tech_only': common}
    for name in ['clip', 'siglip2', 'dinov3']:
        matrices[name] = np.c_[common, v[name]]
        matrices[name+'_photo'] = np.c_[common, v[name], photo]
    matrices['dinov3_spatial_photo'] = np.c_[common, v['dinov3'], v['dinov3_spatial'], photo]
    matrices['siglip2_spatial_photo'] = np.c_[common, v['siglip2'], v['siglip2_spatial'], photo]
    # Ablations isolate faces/expressions, person placement and spatial blur/light.
    for name in ['clip', 'siglip2', 'dinov3']:
        matrices[name+'_faces'] = np.c_[common, v[name], v['face']]
        matrices[name+'_people'] = np.c_[common, v[name], v['people']]
        matrices[name+'_blur_light'] = np.c_[common, v[name], v['spatial']]
    predictions = {}
    fold_reports = []
    raw_scores = {}
    for name, x in matrices.items():
        scores = np.zeros(len(truth))
        ranked_scores = np.zeros(len(truth))
        pred = np.full(len(truth), 'reject', dtype='<U6')
        ranked_pred = pred.copy()
        for fold in range(5):
            train, test = split_fold(labels, folds, fold)
            if not truth[train].any() or truth[train].all():
                raise ValueError('Fold has only one class')
            scaler = StandardScaler().fit(x[train])
            z = scaler.transform(x)
            classifier = LogisticRegression(C=.02, solver='lbfgs', max_iter=500, tol=1e-7).fit(z[train], truth[train])
            scores[test] = classifier.decision_function(z[test])
            px, py = pair_data(z[train], truth[train], labels[train], np.random.default_rng(42+fold))
            ranker = LogisticRegression(C=.02, fit_intercept=False, solver='lbfgs', max_iter=500, tol=1e-7).fit(px, py)
            ranking = ranker.decision_function(z[test])
            ranked_scores[test] = rerank_within_scenes(scores[test], ranking, labels[test])
            local_blocked = np.where(blocked[test])[0]
            for destination, source in [(pred, scores), (ranked_pred, ranked_scores)]:
                destination[test] = selection.decide(source[test], labels[test], v['clip'][test], .2, .2, local_blocked)
            fold_reports.append({'model': name, 'fold': fold, 'train': int(train.sum()), 'test': int(test.sum()),
                                 'training_pairs': len(py)//2,
                                 'variants': summarize_variants(variant_results(scores[test], truth[test], labels[test])),
                                 'pair_variants': summarize_variants(variant_results(ranked_scores[test], truth[test], labels[test]))})
        for suffix, score_values, decisions in [('', scores, pred), ('_pairwise', ranked_scores, ranked_pred)]:
            key = name+suffix
            raw_scores[key] = score_values
            chosen = decisions == 'keep'
            available = decisions != 'reject'
            tp = int((chosen & truth).sum())
            scene_records = variant_results(score_values, truth, labels)
            subgroups = {
                'faces_detected': v['face'][:, 0] > 0,
                'multiple_people': v['people'][:, 0] >= 2,
                'off_center_person': (v['people'][:, 0] > 0) & (np.abs(v['people'][:, 1]+v['people'][:, 3]/2-.5) > .2),
                'portrait_format': np.array([r['stats']['aspect'] < 1 for r in records]),
                'landscape_format': np.array([r['stats']['aspect'] >= 1 for r in records]),
                # Descriptive low-sharpness subgroup; not an artistic-blur annotation.
                'low_sharpness': tech[:, 3] <= np.quantile(tech[:, 3], .25),
            }
            predictions[key] = {'selected': int(chosen.sum()), 'exact_matches': tp,
                                'precision': tp/max(1,int(chosen.sum())), 'recall': tp/int(truth.sum()),
                                'kept_or_review_recall': float((available & truth).sum()/truth.sum()),
                                'missed_kept': int((~available & truth).sum()),
                                'scene_coverage': len(set(labels[chosen]) & set(labels[truth]))/len(set(labels[truth])),
                                'variants': summarize_variants(scene_records), 'scene_results': scene_records,
                                'subgroups': {k: summarize_variants(variant_results(score_values, truth, labels, m)) for k,m in subgroups.items()}}
            print(key, json.dumps({k: val for k,val in predictions[key].items() if k not in ('scene_results','subgroups')}, ensure_ascii=False), flush=True)
    report = {'dataset': {'photos': len(truth), 'kept': int(truth.sum()), 'scenes': len(np.unique(labels)),
                          'unmatched_delivered': dataset_info['unmatched_delivered'],
                          'faces_detected_photos': int((v['face'][:,0]>0).sum()),
                          'people_detected_photos': int((v['people'][:,0]>0).sum()),
                          'technical_blocked': int(blocked.sum()), 'blocked_but_kept': int((blocked&truth).sum())},
              'protocol': {'folds':5, 'grouping':'frozen CLIP scenes', 'purge':'one scene each side of test block',
                           'keep_rate':.2, 'review_rate':.2, 'C':.02,
                           'note':'Exploratory single-reportage comparison, no independent final test. No OCR. Pairwise only permutes scores within scenes.'},
              'timing_seconds_per_photo': {k: {'median': float(np.median([r['seconds'][k] for r in records])),
                                             'total': float(sum(r['seconds'][k] for r in records))} for k in records[0]['seconds']},
              'models': predictions, 'fold_results':fold_reports}
    informative = [np.where(labels == label)[0] for label in np.unique(labels)
                   if truth[labels == label].any() and not truth[labels == label].all()]
    report['reference_baselines'] = {
        'random_top1_expected':float(np.mean([truth[ix].mean() for ix in informative])),
        'sharpest_top1':summarize_variants(variant_results(tech[:,3],truth,labels)),
        'informative_scenes':len(informative)}
    import importlib.metadata
    report['environment'] = {'python':sys.version, 'platform':platform.platform(),
                             'processor':platform.processor(), 'libraries':{}}
    for name in ['numpy','Pillow','onnxruntime','mediapipe','scikit-learn','scipy']:
        report['environment']['libraries'][name] = importlib.metadata.version(name)
    report['model_assets'] = {}
    for name in ['siglip2','dinov3']:
        report['model_assets'][name] = json.loads((ASSETS/name/'manifest.json').read_text())
    report['model_assets']['clip'] = json.loads((ASSETS/'clip/model.json').read_text())
    for name in ['face_landmarker.task','efficientdet_lite0.tflite']:
        with (ASSETS/name).open('rb') as stream:
            report['model_assets'][name] = {'sha256':hashlib.file_digest(stream,'sha256').hexdigest()}
    (out / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    np.savez_compressed(out / 'predictions.npz', order=order, truth=truth, labels=labels, folds=folds, **raw_scores)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=['extract', 'evaluate', 'hybrids', 'tuned'])
    p.add_argument('--rush')
    p.add_argument('--kept')
    p.add_argument('--output', default=str(ROOT / 'test-output' / 'selection-comparison'))
    p.add_argument('--limit', type=int)
    args = p.parse_args()
    if args.stage == 'extract':
        extract(args)
    elif args.stage == 'evaluate':
        evaluate(args)
    elif args.stage == 'hybrids':
        hybrids(args)
    else:
        tuned(args)


if __name__ == '__main__':
    main()
