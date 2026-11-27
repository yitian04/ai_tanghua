"""Explicit conversions between SVG sources and canonical JSON curves."""
import json
import math
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

from src.core.assets import classify
from src.core.models import CurveList


def convert_payload(payload: bytes, name: str):
    kind = classify(payload, name)
    stem = Path(name).stem
    if kind == 'svg':
        from src.modules.svg_import_module import svg_to_curves
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'input.svg'
            source.write_bytes(payload)
            curves = svg_to_curves(source)
        frame = ET.fromstring(payload).attrib.get('data-coordinate-frame')
        if frame:curves.coordinate_frame = frame
        curves.metadata['source_svg'] = name
        return json.dumps(curves.to_dict(), ensure_ascii=False, indent=2).encode('utf-8'), stem+'_curves.json'
    if kind != 'curve':
        raise ValueError('仅支持 SVG 源图与曲线 JSON 互转。')
    curves = CurveList.from_dict(json.loads(payload.decode('utf-8-sig')))
    paths = [c for c in curves.curves if len(c.points) >= 2]
    if not paths:
        raise ValueError('曲线中没有可转换的线段。')
    points = [p for c in paths for p in c.points]
    if any(not math.isfinite(v) for p in points for v in p):
        raise ValueError('曲线包含无效坐标。')
    xmin, xmax = min(p[0] for p in points), max(p[0] for p in points)
    ymin, ymax = min(p[1] for p in points), max(p[1] for p in points)
    # Keep original coordinates (including negative/mm coordinates), with padding.
    namespace = 'http://www.w3.org/2000/svg'
    ET.register_namespace('', namespace)
    root = ET.Element('{'+namespace+'}svg', {
        'viewBox': f'{xmin-1:.12g} {ymin-1:.12g} {xmax-xmin+2:.12g} {ymax-ymin+2:.12g}',
        'fill': 'none', 'stroke': '#000000', 'stroke-width': '1',
        'stroke-linecap': 'round', 'stroke-linejoin': 'round',
        'data-coordinate-frame': curves.coordinate_frame,
    })
    for curve in paths:
        commands = ['M '+ ' '.join(f'{v:.12g}' for v in curve.points[0])]
        commands += ['L '+ ' '.join(f'{v:.12g}' for v in point) for point in curve.points[1:]]
        if curve.closed:commands.append('Z')
        ET.SubElement(root, '{'+namespace+'}path', {'d': ' '.join(commands)})
    return ET.tostring(root, encoding='utf-8'), stem+'_source.svg'


def convert_and_save(library, item, payload=None):
    # Existing files must still match the previewed identity before saving a copy.
    source = library.read(item) if payload is None else payload
    converted, name = convert_payload(source, item['name'])
    return library.import_file(converted, name)
