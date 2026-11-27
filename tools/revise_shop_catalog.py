"""Separate subject matter from minimal line-language presets."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'resources/shop_styles/catalog.json'
old=json.loads(path.read_text(encoding='utf-8'))
backup=ROOT/'outputs/shop_style_candidates/catalog_v1.json'
if not backup.exists():backup.write_text(json.dumps(old,ensure_ascii=False,indent=2),encoding='utf-8')
specs=[('圆润轮廓','Rounded broad contours, gentle arcs and simple compact proportions.',
        ['一杯热咖啡与一只牛角面包，杯口伸出两条连续热气曲线。','三个高低不同的蘑菇与两片大叶子。','一只小兔坐在一朵大花旁。']),
       ('几何折线','Large circles, triangles and clean straight segments; simplify each subject to a few geometric contours.',
        ['圆形太阳、三角形山峰与一道平缓河流。','帆船由一个三角帆和一个弧形船身组成，水面只有两条波纹。','三个高低错落的几何花瓶，各插一枝简化花朵。']),
       ('舒展流线','Long sweeping connected curves, flowing direction and few changes of curvature.',
        ['一条舒展的海浪托起一片小帆。','一枝木兰横向舒展，只有三朵大花和四片叶子。','飘带与一朵大云随风向右舒展。']),
       ('对称纹样','A few broad mirrored contours with an open center; use only a small number of repeated elements.',
        ['左右各一枝大叶片，围绕中央一朵花对称展开。','两条对称水波之间升起一轮太阳。','一只张开翅膀的蝴蝶，左右各一朵大花。']),
       ('稚拙造型','Playful exaggerated proportions with deliberate smooth simple contours, never scratchy or wobbly marks.',
        ['一把大雨伞旁放着两只圆头雨靴。','一座小山托着比山还大的云朵和太阳。','一颗大草莓和两颗圆樱桃并排摆放。']),
       ('留白构景','Few large silhouettes described only by hollow outlines, asymmetrical balance and spacious negative space.',
        ['一座平缓小山、一朵大云和半露的太阳组成疏朗横幅。','一片荷叶、一朵莲花和一道长水纹。','一弯月亮照着一枝横向舒展的树枝。'])]
new=[]
ids=['rounded','geometric','flowing','symmetric','naive','spacious']
for index,(original,(label,language,themes)) in enumerate(zip(old,specs)):
    new.append({**original,'id':ids[index],'label':label,'line_language':language,'themes':themes,'version':2,
                'legacy_library_id':original.get('legacy_library_id',original.get('number')),
                'reference_policy':'Use only the user supplied line-density reference; numbered artwork is not passed to generation.'})
path.write_text(json.dumps(new,ensure_ascii=False,indent=2),encoding='utf-8')
