"""Controlled line-art trial. Keep native outputs; never stretch failed ratios."""
import sys,json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.pipeline.shop_creation import shared_image_provider
from src.pipeline.image_generation.providers import ImageRequestOptions

BASE=('Draw only the illustration described below on a pure white 16:9 landscape canvas. '
      'This is a simple line drawing, NOT a product mockup or architectural drawing. '
      'Use a single uniform black monoline pen, smooth connected long curves, round caps and joins. '
      'All styles must be equally minimal: 3 to 5 large elements, only essential contours, '
      'no more than about 15 long strokes. Use one continuous stroke per connected contour wherever possible. '
      'No short broken marks, hatching, fur, leaf veins, fine ornament, doubled outlines, shading, texture, filled shapes or text. '
      'No frame, border, building, shopfront, door or window. Fill the wide composition without cropping its subjects. '
      'Style: rounded, friendly, broad simple shapes. Theme: ')
THEMES=['一座平缓小山、一朵大云和半露的太阳，三者以舒展曲线组成疏朗横幅。',
        '一枝木兰从左向右舒展，只有三朵大花和四片叶子。',
        '一杯冒着两条连续热气线的咖啡，旁边是一只牛角面包。']
MODELS=['nano-banana-pro','nano-banana-2','gpt-image-2']

def main():
    out=ROOT/'outputs/shop_model_comparison_v2';out.mkdir(parents=True,exist_ok=True)
    jobs=[{'model':m,'theme':t,'topic':i+1,'prompt':BASE+t,'file':f'{m}_{i+1}.png'} for m in MODELS for i,t in enumerate(THEMES)]
    def run(j):
        p,options=shared_image_provider(ROOT);p.generation_model=j['model']
        options=ImageRequestOptions(size='1536x864',extra_body={'aspect_ratio':'16:9','resolution':'1K'})
        # Probe this gateway's GPT ratio support explicitly; report actual returned dimensions.
        if j['model'].startswith('gpt-image'):
            original=p._add_model_options
            def add(body,model,opts):
                original(body,model,opts);body.update(aspect_ratio='16:9',size='1536x864')
            p._add_model_options=add
        try:
            result=p.generate(j['prompt'],out/j['file'],options)
            with Image.open(result.output_path) as im:
                j['dimensions']=list(im.size);j['ratio_error']=abs(im.width/im.height-16/9)/(16/9)
                j['native_16_9']=j['ratio_error']<.005
            j['status']='complete'
        except Exception as e:
            j['status']='failed';j['error_type']=type(e).__name__
            j['error_summary']='HTTP 503 / service busy' if '503' in str(e) else str(e)[:300]
        return j
    with ThreadPoolExecutor(max_workers=2) as pool:
        for f in as_completed([pool.submit(run,j) for j in jobs]):
            j=f.result();(out/'manifest.json').write_text(json.dumps(jobs,ensure_ascii=False,indent=2),encoding='utf-8')
            print(j['model'],j['topic'],j['status'],j.get('dimensions',j.get('error_summary')),flush=True)
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',17)
    sheet=Image.new('RGB',(1500,1050),'white');d=ImageDraw.Draw(sheet)
    for k,j in enumerate(jobs):
        x=(k%3)*500;y=(k//3)*350
        if j['status']=='complete':
            with Image.open(out/j['file']) as im:
                im=im.convert('RGB');im.thumbnail((480,275));sheet.paste(im,(x+(500-im.width)//2,y))
        d.text((x+10,y+280),f'{j["model"]} / 题目{j["topic"]}',font=font,fill='black')
        d.text((x+10,y+306),str(j.get('dimensions',j.get('error_summary'))),font=font,fill='black')
    sheet.save(out/'comparison.jpg')
if __name__=='__main__':main()
