"""Independent local multi-image transport sanity check; no photographer labels."""
import base64
import io
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.benchmark_visual_comparator import OUT, MODEL, api, dump
from PIL import Image, ImageDraw


def main():
    images=[]
    expected=[('red','circle'),('blue','triangle'),('green','square')]
    for color,shape in expected:
        im=Image.new('RGB',(640,480),'white'); d=ImageDraw.Draw(im)
        if shape=='circle': d.ellipse((180,100,460,380),fill=color)
        elif shape=='triangle': d.polygon([(320,80),(140,390),(500,390)],fill=color)
        else: d.rectangle((180,100,460,380),fill=color)
        buf=io.BytesIO(); im.save(buf,format='PNG')
        images.append(base64.b64encode(buf.getvalue()).decode())
    results=[]
    schema={'type':'object','properties':{'images':{'type':'array','items':{'type':'object',
        'properties':{'color':{'type':'string'},'shape':{'type':'string'}},'required':['color','shape']},
        'minItems':3,'maxItems':3}},'required':['images']}
    for order in [[0,1,2],[2,1,0]]:
        response=api('/api/chat',{'model':MODEL,'stream':False,'keep_alive':'30m','format':schema,
            'options':{'temperature':0,'num_ctx':16384,'num_predict':300},
            'messages':[{'role':'user','content':'You receive THREE separate images in order. For EACH image, identify the color and the geometric shape on the white background. Return the array in supplied image order. Do not describe just one image.',
                         'images':[images[i] for i in order]}]})
        results.append({'expected':[expected[i] for i in order],'raw':response})
    dump(OUT/'sanity-multi-image.json',results)
    for r in results: print(r['expected'],r['raw']['message']['content'],r['raw'].get('prompt_eval_count'))


if __name__=='__main__': main()
