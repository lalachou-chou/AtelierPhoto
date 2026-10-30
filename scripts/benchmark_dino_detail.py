"""DINOv3 Small/Base at 448 pixels plus two native-resolution detail crops.

Reuses the exact dataset, labels, scene grouping and purged folds of the first
benchmark. Does not modify original images, profile databases, or first results.
No network calls. Download weights with prepare_selection_benchmark.py first.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.compare_selection_models import (
    ASSETS, load_data, unit, split_fold, chronological_folds, pair_data,
    rerank_within_scenes, variant_results, summarize_variants,
)
import numpy as np
from PIL import Image, ImageOps, ImageCms, ImageDraw
from atelier import selection
from atelier.analysis import technical

PREVIOUS = ROOT/'test-output/selection-comparison'
OUTPUT = ROOT/'test-output/selection-dino-detail'
VIEW_POLICY = 'v1: native oriented sRGB; full square448; topface-expanded-or-upperperson224; secondface-or-primaryperson224; center/full fallbacks'


def native_image(path):
    with Image.open(path) as src:
        image = ImageOps.exif_transpose(src).convert('RGB')
        if src.info.get('icc_profile'):
            source = ImageCms.ImageCmsProfile(io.BytesIO(src.info['icc_profile']))
            image = ImageCms.profileToProfile(image, source, ImageCms.createProfile('sRGB'), outputMode='RGB')
        return image


def square_box(box, width, height, scale=1.):
    """Square crop inside image, without black padding or changing its aspect ratio."""
    x,y,w,h = box
    cx,cy = (x+w/2)*width,(y+h/2)*height
    side = min(max(w*width,h*height)*scale, width, height)
    side = max(1,round(side))
    left = min(max(0,round(cx-side/2)),width-side)
    top = min(max(0,round(cy-side/2)),height-side)
    return (left,top,left+side,top+side)


def detail_boxes(detail, width, height):
    """Fixed, label-blind choices using detections saved by the first benchmark."""
    faces, people = detail['faces'], detail['people']
    if faces:
        a = square_box(faces[0]['box'],width,height,2.)
        ak = 'face'
    elif people:
        x,y,w,h,_ = people[0]
        a = square_box((x,y,w,h*.45),width,height,1.15)
        ak = 'upper_person'
    else:
        a = square_box((.25,.25,.5,.5),width,height)
        ak = 'center_fallback'
    if len(faces)>1:
        b = square_box(faces[1]['box'],width,height,2.)
        bk = 'second_face'
    elif people:
        # Full person, preserving that region's aspect ratio on square canvas crop.
        b = square_box(people[0][:4],width,height,1.05)
        bk = 'person'
    else:
        b = (0,0,width,height)
        bk = 'full_fallback'
    return [(a,ak),(b,bk)]


class Dino:
    def __init__(self, name):
        import onnxruntime as ort
        self.name = name
        folder = ASSETS/('dinov3' if name=='small' else 'dinov3_base')
        self.processor = json.loads((folder/'preprocessor_config.json').read_text())
        config = json.loads((folder/'config.json').read_text())
        self.dimension = config['hidden_size']
        self.special = 1+config['num_register_tokens']
        opts = ort.SessionOptions()
        opts.intra_op_num_threads=2
        opts.inter_op_num_threads=1
        self.session = ort.InferenceSession(str(folder/'onnx/model.onnx'),sess_options=opts,providers=['CPUExecutionProvider'])

    def encode(self, image, size):
        p = self.processor
        image = image.convert('RGB').resize((size,size),Image.Resampling(p['resample']))
        x = np.asarray(image,np.float32)*p['rescale_factor']
        x = (x-np.asarray(p['image_mean'],np.float32))/np.asarray(p['image_std'],np.float32)
        hidden, pooled = self.session.run(['last_hidden_state','pooler_output'],{'pixel_values':x.transpose(2,0,1)[None]})
        assert hidden.shape == (1,(size//16)**2+self.special,self.dimension), hidden.shape
        vector = unit(pooled[0])
        if not np.isfinite(vector).all():
            raise ValueError('Nonfinite embedding')
        return vector


def signature():
    assets = {name:json.loads((ASSETS/folder/'manifest.json').read_text()) for name,folder in [('small','dinov3'),('base','dinov3_base')]}
    value = {'assets':assets,'view_policy':VIEW_POLICY,'global_size':448,'detail_size':224,'threads':2,
             'dataset_sha256':hashlib.sha256((PREVIOUS/'dataset.json').read_bytes()).hexdigest()}
    return value,hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def extract(args):
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/'cache').mkdir(exist_ok=True)
    manifest = json.loads((PREVIOUS/'dataset.json').read_text(encoding='utf8'))
    spec,key=signature()
    if not (OUTPUT/'protocol.json').exists():
        (OUTPUT/'protocol.json').write_text(json.dumps(spec,indent=2),encoding='utf8')
    elif json.loads((OUTPUT/'protocol.json').read_text(encoding='utf8'))!=spec:
        raise ValueError('Protocol differs from existing extraction; use a new output directory')
    encoders=[Dino('small'),Dino('base')]
    run_start=time.perf_counter(); processed=0
    for i,path in enumerate(manifest['paths']):
        if i < args.start or (args.end is not None and i >= args.end):
            continue
        target=OUTPUT/'cache'/f'{i:05}.npz'
        stat=Path(path).stat()
        stamp=[str(path),stat.st_size,stat.st_mtime_ns]
        if target.exists():
            with np.load(target) as saved:
                m=json.loads(str(saved['metadata']))
            if m['signature']==key and m['stamp']==stamp:
                continue
        with np.load(PREVIOUS/'cache'/f'{i:05}.npz') as previous:
            old=json.loads(str(previous['metadata']))
            # Reject changed sources rather than combining stale and new measurements.
            assert old['stamp']==stamp, f'Source changed: {path}'
        start=time.perf_counter()
        image=native_image(path)
        views=detail_boxes(old['detail'],image.width,image.height)
        crops=[image.crop(box) for box,_ in views]
        seconds={'decode_native':time.perf_counter()-start}
        vectors={}
        for encoder in encoders:
            name=encoder.name
            if name=='base':
                start=time.perf_counter()
                vectors[name+'_224']=encoder.encode(image,224)
                seconds[name+'_224']=time.perf_counter()-start
            start=time.perf_counter()
            vectors[name+'_448']=encoder.encode(image,448)
            seconds[name+'_448']=time.perf_counter()-start
            start=time.perf_counter()
            detailed=np.array([encoder.encode(crop,224) for crop in crops])
            vectors[name+'_details']=detailed
            vectors[name+'_detailmean']=unit(detailed.mean(0))
            seconds[name+'_details']=time.perf_counter()-start
        m={'stamp':stamp,'signature':key,'views':[{'box':list(b),'kind':k} for b,k in views],
           'native_size':list(image.size),'seconds':seconds}
        temp=target.with_suffix('.tmp')
        with temp.open('wb') as stream:
            np.savez_compressed(stream,metadata=json.dumps(m),**vectors)
        temp.replace(target)
        processed+=1
        image.close()
        for crop in crops: crop.close()
        if i%20==0 or i==len(manifest['paths'])-1:
            average=(time.perf_counter()-run_start)/processed
            print(f'{i+1}/{len(manifest["paths"])} | {average:.2f}s/image | last='+json.dumps({k:round(v,3) for k,v in seconds.items()}),flush=True)
        if args.limit and processed>=args.limit:
            break


def metrics(scores, truth, labels, folds, clip, blocked, masks):
    decisions=np.full(len(truth),'reject',dtype='<U6')
    for fold in range(5):
        ix=folds==fold
        decisions[ix]=selection.decide(scores[ix],labels[ix],clip[ix],.2,.2,np.where(blocked[ix])[0])
    chosen,available=decisions=='keep',decisions!='reject'
    correct=int((chosen&truth).sum())
    return {'selected':int(chosen.sum()),'exact_matches':correct,
            'precision':correct/max(1,int(chosen.sum())), 'recall':correct/int(truth.sum()),
            'kept_or_review_recall':float((available&truth).sum()/truth.sum()),
            'missed_kept':int((~available&truth).sum()),
            'variants':summarize_variants(variant_results(scores,truth,labels)),
            'scene_results':variant_results(scores,truth,labels),
            'subgroups':{k:summarize_variants(variant_results(scores,truth,labels,m)) for k,m in masks.items()}}


def read_extracted(order):
    vectors={}; metadata=[]
    _,key=signature()
    for i in order:
        with np.load(OUTPUT/'cache'/f'{i:05}.npz') as z:
            meta=json.loads(str(z['metadata']))
            assert meta['signature']==key
            metadata.append(meta)
            for name in z.files:
                if name!='metadata': vectors.setdefault(name,[]).append(z[name])
    return {k:np.asarray(v) for k,v in vectors.items()},metadata


def evaluate(args):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from threadpoolctl import threadpool_limits
    threadpool_limits(limits=2)
    info,records,old,truth,order=load_data(PREVIOUS)
    v,meta=read_extracted(order)
    with np.load(PREVIOUS/'predictions.npz') as z:
        original={k:z[k] for k in z.files}
    labels,folds=original['labels'],original['folds']
    assert np.array_equal(order,original['order']) and np.array_equal(truth,original['truth'])
    tech=np.array([selection.tech_vector(r['stats']) for r in records])
    common=np.c_[tech,selection.context(tech,[r['time'] for r in records],old['clip'],labels)]
    blocked=np.array([technical(r['stats'],.5,False)[0]=='reject' for r in records])
    masks={'faces_detected':old['face'][:,0]>0,'multiple_people':old['people'][:,0]>=2,
           'off_center_person':(old['people'][:,0]>0)&(np.abs(old['people'][:,1]+old['people'][:,3]/2-.5)>.2),
           'low_sharpness':tech[:,3]<=np.quantile(tech[:,3],.25)}
    matrices={'small_224':np.c_[common,old['dinov3']], 'base_224':np.c_[common,v['base_224']]}
    for name in ['small','base']:
        matrices[name+'_448']=np.c_[common,v[name+'_448']]
        matrices[name+'_448_details']=np.c_[common,v[name+'_448'],v[name+'_detailmean']]
        matrices[name+'_448_details_separate']=np.c_[common,v[name+'_448'],v[name+'_details'].reshape(len(truth),-1)]
    results={}; saved={'order':order,'truth':truth,'labels':labels,'folds':folds}
    logs=[]
    for name,x in matrices.items():
        scores=np.zeros(len(truth)); pair_scores=np.zeros(len(truth)); nested=np.zeros(len(truth)); tuning=[]
        for fold in range(5):
            train,test=split_fold(labels,folds,fold)
            scaler=StandardScaler().fit(x[train]); z=scaler.transform(x)
            model=LogisticRegression(C=.02,solver='lbfgs',max_iter=700,tol=1e-7).fit(z[train],truth[train])
            scores[test]=model.decision_function(z[test])
            px,py=pair_data(z[train],truth[train],labels[train],np.random.default_rng(42+fold))
            ranker=LogisticRegression(C=.02,fit_intercept=False,solver='lbfgs',max_iter=700,tol=1e-7).fit(px,py)
            pair_scores[test]=rerank_within_scenes(scores[test],ranker.decision_function(z[test]),labels[test])
            # Same nested sensitivity check as before, using only outer training data.
            train_ix=np.where(train)[0]; inner_folds=chronological_folds(labels[train],3)
            choices=[.0001,.001,.01,.1,1.]; accuracies=[]
            for c in choices:
                correct=[]
                for inner in range(3):
                    fit,val=split_fold(labels[train],inner_folds,inner)
                    fi,vi=train_ix[fit],train_ix[val]
                    sc=StandardScaler().fit(x[fi])
                    m=LogisticRegression(C=c,solver='lbfgs',max_iter=700,tol=1e-7).fit(sc.transform(x[fi]),truth[fi])
                    correct.extend(r['top1'] for r in variant_results(m.decision_function(sc.transform(x[vi])),truth[vi],labels[vi]))
                accuracies.append(float(np.mean(correct)))
            c=choices[int(np.argmax(accuracies))]
            tuned=LogisticRegression(C=c,solver='lbfgs',max_iter=700,tol=1e-7).fit(z[train],truth[train])
            nested[test]=tuned.decision_function(z[test])
            tuning.append({'fold':fold,'C':c,'inner_top1':accuracies})
            logs.append({'model':name,'fold':fold,'train':int(train.sum()),'test':int(test.sum()),
                         'top1':summarize_variants(variant_results(scores[test],truth[test],labels[test]))})
        for suffix,score in [('',scores),('_pairwise',pair_scores),('_nested',nested)]:
            key=name+suffix
            saved[key]=score
            results[key]=metrics(score,truth,labels,folds,old['clip'],blocked,masks)
            if suffix=='_nested': results[key]['tuning']=tuning
            print(key, 'top1',results[key]['variants']['top1_correct'],'exact',results[key]['exact_matches'],flush=True)
        # Fixed hybrid hypothesis from previous experiment, no post-hoc fitted mixing.
        hybrid=rerank_within_scenes(original['clip'],scores,labels)
        saved[name+'_clip_scenes']=hybrid
        results[name+'_clip_scenes']=metrics(hybrid,truth,labels,folds,old['clip'],blocked,masks)
    previous=json.loads((PREVIOUS/'results.json').read_text(encoding='utf8'))
    for name in ['clip','clip_pairwise','dinov3','dinov3_nested']:
        results['previous_'+name]=previous['models'][name]
    report={'dataset':previous['dataset'],'models':results,'fold_results':logs,
            'specification':json.loads((OUTPUT/'protocol.json').read_text()),
            'protocol':{'comparison':'Same original labels, scenes, folds and quotas as previous study.',
                        'main_C':.02,'nested':'C chosen on three inner folds only, grid 0.0001 to 1.',
                        'detail_fusion':'Primary: concatenate global unit embedding and normalized mean of two local unit embeddings. Secondary: concatenate both separately.',
                        'limitations':'Exploratory continuation on one reportage; no new independent test. No eye/blur intent annotations. Crops depend on imperfect prior detectors.'},
            'timing':{k:{'median':float(np.median([r['seconds'][k] for r in meta])),
                         'total':float(sum(r['seconds'][k] for r in meta))} for k in meta[0]['seconds']},
            'crop_kinds':{k:sum(v['kind']==k for r in meta for v in r['views']) for k in sorted({v['kind'] for r in meta for v in r['views']})}}
    # Paired scene bootstrap, reported as exploratory rather than definitive significance.
    reference={r['scene']:r['top1'] for r in results['previous_dinov3']['scene_results']}
    for model in results.values():
        rows=model['scene_results']; diff=np.array([int(r['top1'])-int(reference[r['scene']]) for r in rows])
        rng=np.random.default_rng(20261029)
        boot=diff[rng.integers(0,len(diff),(5000,len(diff)))].mean(1)
        model['delta_vs_small224']={'points':float(diff.mean()*100),'ci95_points':(100*np.quantile(boot,[.025,.975])).tolist()}
    (OUTPUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    np.savez_compressed(OUTPUT/'predictions.npz',**saved)


def crops_preview():
    available=sorted((OUTPUT/'cache').glob('*.npz'))
    selected=[available[i] for i in np.linspace(0,len(available)-1,min(8,len(available)),dtype=int)]
    board=Image.new('RGB',(1200,300*len(selected)),'#191b20'); draw=ImageDraw.Draw(board)
    for row,path in enumerate(selected):
        with np.load(path) as z: meta=json.loads(str(z['metadata']))
        source=native_image(meta['stamp'][0])
        images=[source.copy()]+[source.crop(v['box']) for v in meta['views']]
        for col,img in enumerate(images):
            img.thumbnail((390,260)); board.paste(img,(col*400,row*300))
            text=Path(meta['stamp'][0]).name if col==0 else meta['views'][col-1]['kind']
            draw.text((col*400+4,row*300+270),text,fill='white')
    board.save(OUTPUT/'vues-detaillees.jpg',quality=92)


def timing(args):
    """Run only when extraction workers have finished: same inputs, no contention."""
    manifest=json.loads((PREVIOUS/'dataset.json').read_text(encoding='utf8'))
    encoders=[Dino('small'),Dino('base')]
    samples=[]
    indexes=np.linspace(0,len(manifest['paths'])-1,24,dtype=int)
    for step,i in enumerate(indexes):
        with np.load(OUTPUT/'cache'/f'{i:05}.npz') as z:
            m=json.loads(str(z['metadata']))
        begin=time.perf_counter(); image=native_image(manifest['paths'][i])
        crops=[image.crop(v['box']) for v in m['views']]
        sample={'index':int(i),'decode_native':time.perf_counter()-begin}
        # Warm graphs before the measured sample, including the 448 dynamic shape.
        if step==0:
            for encoder in encoders:
                encoder.encode(image,224); encoder.encode(image,448)
        for encoder in (encoders if step%2==0 else encoders[::-1]):
            for size in (224,448):
                start=time.perf_counter(); encoder.encode(image,size)
                sample[encoder.name+'_'+str(size)]=time.perf_counter()-start
            start=time.perf_counter()
            for crop in crops: encoder.encode(crop,224)
            sample[encoder.name+'_details']=time.perf_counter()-start
            sample[encoder.name+'_448_details']=sample[encoder.name+'_448']+sample[encoder.name+'_details']
        samples.append(sample)
        print(f'Isolated timing {step+1}/{len(indexes)}',flush=True)
    report={'photos':len(samples),'threads':2,'providers':['CPUExecutionProvider'],
            'procedure':'Single process; two ONNX intra-op threads; warmup excluded; encoder order alternates; native-image loading separate.',
            'steps':{key:{'median':float(np.median([s[key] for s in samples])),
                          'mean':float(np.mean([s[key] for s in samples])),
                          'p90':float(np.quantile([s[key] for s in samples],.9))}
                     for key in samples[0] if key!='index'},'samples':samples}
    (OUTPUT/'timing-isolated.json').write_text(json.dumps(report,indent=2),encoding='utf8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=['extract','evaluate','preview','timing'])
    p.add_argument('--limit',type=int)
    p.add_argument('--start',type=int,default=0)
    p.add_argument('--end',type=int)
    a=p.parse_args()
    if a.stage=='extract': extract(a)
    elif a.stage=='evaluate': evaluate(a)
    elif a.stage=='preview': crops_preview()
    else: timing(a)


if __name__=='__main__': main()
