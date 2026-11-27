"""Generate the numbered shop candidates with the project's saved image model."""
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.pipeline.shop_creation import catalog, generate_reference, image_prompt


def main():
    output = ROOT/'outputs/shop_style_candidates'
    output.mkdir(parents=True, exist_ok=True)
    jobs = []
    for style in catalog(ROOT):
        for theme in style['themes']:
            number = len(jobs)+1
            jobs.append({'number':number,'style_id':style['id'],'style_label':style['label'],
                         'theme':theme,'prompt':image_prompt(style,theme),'file':f'{number:02d}_{style["id"]}.png',
                         'reference_used':None,'status':'pending','style':style})
    manifest = output/'manifest.json'
    if manifest.exists():
        previous = json.loads(manifest.read_text(encoding='utf-8'))
        for job, old in zip(jobs,previous):
            if old.get('prompt')==job['prompt'] and old.get('status')=='complete' and (output/job['file']).is_file():
                job.update(status='complete',model=old.get('model'),provider=old.get('provider'))
            elif (output/job['file']).is_file():
                job['previous']=old
        (output/'first_round_manifest.json').write_text(json.dumps(previous,ensure_ascii=False,indent=2),encoding='utf-8')
    def save():
        manifest.write_text(json.dumps([{k:v for k,v in j.items() if k not in ('style','previous')} for j in jobs],ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    def run(job):
        if job['status']=='complete':return job
        try:
            pending=output/'.pending'/job['file'];pending.parent.mkdir(exist_ok=True)
            result,actual_prompt = generate_reference(ROOT,job['style'],job['theme'],pending)
            with Image.open(result.output_path) as im:im.verify()
            if (output/job['file']).is_file():
                previous_dir=output/'first_round';previous_dir.mkdir(exist_ok=True)
                destination=previous_dir/job['file']
                if not destination.exists():(output/job['file']).replace(destination)
            Path(result.output_path).replace(output/job['file'])
            job.update(status='complete',model=result.model_id,provider=result.provider_id,prompt=actual_prompt,
                       reference_used=None if 'No reference image input was supplied' in actual_prompt else 'resources/shop_styles/line_density_reference.png')
        except Exception as exc:
            # Do not expose remote request headers or credentials in artifacts.
            if job.get('previous'):
                job.update(job['previous']);job.update(refinement_status='failed',refinement_error=type(exc).__name__)
            else:job.update(status='failed',error=type(exc).__name__)
        return job
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(run,j) for j in jobs]):
            job=future.result();save();suffix=' (refinement failed; original retained)' if job.get('refinement_status')=='failed' else ''
            print(f'{job["number"]:02d}: {job["status"]}{suffix}',flush=True)
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',18)
    sheet=Image.new('RGB',(1440,6*330),'white');draw=ImageDraw.Draw(sheet)
    for j in jobs:
        x=((j['number']-1)%3)*480;y=((j['number']-1)//3)*330
        if j['status']=='complete':
            with Image.open(output/j['file']) as im:
                im=im.convert('RGB');im.thumbnail((460,260));sheet.paste(im,(x+(480-im.width)//2,y))
        draw.text((x+12,y+265),f'{j["number"]:02d} · {j["style_label"]} · {j["style_id"]}',font=font,fill='#59361d')
        theme=j['theme'];draw.text((x+12,y+291),theme[:24],font=font,fill='#59361d')
    sheet.save(output/'contact_sheet.jpg')
    lines=['# 小店线稿风格候选','候选参考，尚未选定为最终画风。','来源：yang0 / https://github.com/yang0/handraw-style','']
    for j in jobs:
        lines.extend([f'## {j["number"]:02d} · {j["style_label"]} · {j["style_id"]}',j['theme'],f'状态：{j["status"]}',f'![样图]({j["file"]})','```text',j['prompt'],'```',''])
    (output/'prompts.md').write_text('\n'.join(lines),encoding='utf-8')
    print(f'Completed {sum(j["status"]=="complete" for j in jobs)}/18',flush=True)


if __name__=='__main__':main()
