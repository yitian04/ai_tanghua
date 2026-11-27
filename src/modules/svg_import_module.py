"""Import SVG source geometry directly into the canonical CurveList format."""
from pathlib import Path
import math
import re
import xml.etree.ElementTree as ET

from src.core.assets import classify
from src.pipeline.vectorization import parse_svg_to_curve_list
from src.pipeline.vectorization.svg_styles import normalize_styles


def svg_to_curves(source: str | Path, sample_tolerance: float = 1.2):
    source = Path(source)
    if not math.isfinite(sample_tolerance) or not 0.2 <= sample_tolerance <= 20:
        raise ValueError('SVG 采样间距必须在 0.2–20 之间。')
    payload = source.read_bytes()
    classify(payload, source.name)
    root = normalize_styles(ET.fromstring(payload))
    supported = {'svg', 'g', 'path', 'line', 'polyline', 'polygon', 'rect', 'circle', 'ellipse', 'title', 'desc', 'metadata'}
    for node in root.iter():
        tag = node.tag.split('}')[-1]
        effects = ('clip-path', 'mask', 'filter')
        if tag not in supported or any(k in node.attrib or k+':' in node.attrib.get('style', '').replace(' ', '') for k in effects):
            raise ValueError(f'SVG 包含尚不支持的元素或效果：{tag}。请先展开为普通路径。')
        transforms = re.findall(r'([a-zA-Z]+)\s*\(', node.attrib.get('transform', ''))
        if any(t.lower() not in {'matrix', 'translate', 'scale', 'rotate'} for t in transforms):
            raise ValueError('SVG 含尚不支持的变换，请先将变换应用到路径坐标。')
        if tag == 'svg' and node is not root:
            raise ValueError('请先将嵌套 SVG 展开为普通路径。')
    curves = parse_svg_to_curve_list(source, sample_tolerance_px=sample_tolerance)
    if not curves.curves:
        raise ValueError('SVG 没有可转换的曲线。')
    if any(not math.isfinite(v) for c in curves.curves for p in c.points for v in p):
        raise ValueError('SVG 包含无效坐标。')
    curves.metadata.update(source_svg=str(source), source_type='svg', sample_tolerance=sample_tolerance)
    return curves
