"""Pack user line-density guidance with each numbered style reference."""
from pathlib import Path
import json
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'resources/shop_styles'
with Image.open(p/'line_density_reference.png') as source:
    original=source.convert('RGB');original.thumbnail((1000,700))
for style in json.loads((p/'catalog.json').read_text(encoding='utf-8')):
    with Image.open(ROOT/style['candidate_reference']) as source:
        ref=source.convert('RGB');ref.thumbnail((500,650))
    sheet=Image.new('RGB',(1540,760),'white')
    sheet.paste(original,(10,50));sheet.paste(ref,(1030,50))
    draw=ImageDraw.Draw(sheet)
    draw.text((10,15),'A: REQUIRED LINE SIMPLICITY / WHITE BACKGROUND',fill='black')
    draw.text((1030,15),'B: SHAPE LANGUAGE ONLY',fill='black')
    sheet.save(p/(style['id']+'_input.jpg'),quality=85)
