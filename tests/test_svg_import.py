import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from src.core.assets import AssetLibrary
from src.core.drafts import DraftStore
from src.modules.svg_import_module import svg_to_curves
from src.pipeline.export.json_exporter import export_curves_json, load_curves_json
from src.pipeline.planning.planner import TrajectoryPlanner


SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><g transform="translate(5 7)" fill="none" stroke="brown"><path d="M0 0 L20 0"/><path d="M30 10 C30 0 50 0 50 10"/></g></svg>'


class SVGImportTests(unittest.TestCase):
    def test_illustrator_styles_and_metadata_import(self):
        payload=b'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:i="http://ns.adobe.com/AdobeIllustrator/10.0/">
        <defs><style>.st0 {fill:none;stroke:#000;stroke-linecap:round;} .hidden {display:none;}</style></defs>
        <path class="st0" d="M0 0 C0 10 20 10 20 0"/>
        <path class="hidden" d="M100 100 L200 200"/>
        <metadata><i:aipgf>editor data</i:aipgf><path d="M300 300 L400 400"/></metadata></svg>'''
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'illustrator.svg';source.write_bytes(payload)
            curves=svg_to_curves(source)
            self.assertEqual(len(curves.curves),1)
            self.assertEqual(curves.curves[0].points[0],[0.,0.])
            lib=AssetLibrary(directory)
            self.assertEqual(lib.import_file(payload,'illustrator.svg')['kind'],'svg')

    def test_simple_css_cascade_and_complex_styles_rejected(self):
        from src.pipeline.vectorization.svg_styles import normalize_styles
        import xml.etree.ElementTree as ET
        root=ET.fromstring('<svg><defs><style>path {stroke:red;} .line {stroke:black;} #main {stroke:blue;}</style></defs><path id="main" class="line" stroke="green" style="stroke:brown" d="M0 0 L20 20"/></svg>')
        normalize_styles(root)
        self.assertEqual(root.find('path').get('stroke'),'brown')
        for body in ('.line {filter:blur(2px);}', '@import "x.css";', '.line {stroke:url(#paint);}', 'g path {stroke:black;}'):
            with self.subTest(body=body),self.assertRaises(ValueError):
                normalize_styles(ET.fromstring('<svg><defs><style>'+body+'</style></defs></svg>'))
        with self.assertRaises(ValueError):normalize_styles(ET.fromstring('<svg><defs><clipPath id="x"/></defs></svg>'))

    def test_source_import_json_and_planner_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            lib = AssetLibrary(directory)
            asset = lib.import_file(SVG, 'shop.svg')
            self.assertEqual(asset['kind'], 'svg')
            self.assertIn('/images/', asset['id'])
            curves = svg_to_curves(lib.path(asset['id']), .5)
            self.assertEqual(len(curves.curves), 2)
            self.assertEqual(curves.curves[0].points, [[5., 7.], [25., 7.]])
            self.assertGreater(len(curves.curves[1].points), 2)
            output = Path(directory)/'data/curves/shop.json'
            export_curves_json(curves, output)
            restored = load_curves_json(output)
            self.assertTrue(TrajectoryPlanner().plan(restored).points)
            self.assertEqual([p.suffix for p in output.parent.iterdir()], ['.json'])

    def test_rejects_unsupported_effects_and_empty_input(self):
        for payload in (b'<svg/>', SVG.replace(b'<path', b'<path clip-path="url(#x)"', 1), SVG.replace(b'<path', b'<image', 1)):
            with tempfile.TemporaryDirectory() as directory:
                source = Path(directory)/'bad.svg';source.write_bytes(payload)
                with self.assertRaises(ValueError):svg_to_curves(source)

    def test_arcs_and_rounded_rectangles_keep_their_shape(self):
        payload=b'<svg><path d="M10 50 A40 40 0 0 1 90 50"/><rect x="10" y="60" width="80" height="30" rx="10"/></svg>'
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'arch.svg';source.write_bytes(payload)
            curves=svg_to_curves(source,.5)
            arc,rect=curves.curves
            self.assertEqual(arc.points[0],[10.,50.])
            self.assertEqual(arc.points[-1],[90.,50.])
            self.assertLess(min(p[1] for p in arc.points),10.1)
            self.assertGreater(len(rect.points),8)
            self.assertNotIn([10.,60.],rect.points)
            self.assertEqual(rect.points[0],rect.points[-1])

    def test_raster_page_also_outputs_json_only(self):
        import io
        from PIL import Image,ImageDraw
        with tempfile.TemporaryDirectory() as directory:
            image=Image.new('RGB',(100,100),'white')
            ImageDraw.Draw(image).line([(15,20),(80,70)],fill='black',width=5)
            buffer=io.BytesIO();image.save(buffer,format='PNG')
            lib=AssetLibrary(directory);asset=lib.import_file(buffer.getvalue(),'line.png')
            app=AppTest.from_string(f'from apps.gui.views.vector_page import render\nrender({{}}, {directory!r})')
            app.session_state['asset_selected_vector']=[str(lib.path(asset['id']))]
            app.run(timeout=30)
            next(v for v in app.button if v.label=='生成曲线').click().run(timeout=30)
            self.assertFalse(list(app.exception),list(app.exception))
            output=Path(app.session_state['latest_curves_path'])
            self.assertTrue(load_curves_json(output).curves)
            self.assertEqual([p.suffix for p in output.parent.iterdir()],['.json'])

    def test_svg_page_outputs_only_json_without_raster_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            lib = AssetLibrary(directory);asset = lib.import_file(SVG, 'shop.svg')
            code = f'from apps.gui.views.vector_page import render\nrender({{}}, {directory!r})'
            app = AppTest.from_string(code)
            app.session_state['asset_selected_vector'] = [str(lib.path(asset['id']))]
            app.run(timeout=30)
            self.assertFalse(list(app.exception), list(app.exception))
            self.assertFalse(any(v.label == '二值化方式' for v in app.selectbox))
            next(v for v in app.button if v.label == '生成曲线').click().run(timeout=30)
            self.assertFalse(list(app.exception), list(app.exception))
            output = Path(app.session_state['latest_curves_path'])
            self.assertEqual(len(load_curves_json(output).curves), 2)
            self.assertEqual([p.suffix for p in output.parent.iterdir()], ['.json'])

    def test_ai_svg_draft_publishes_json_only(self):
        from apps.gui import workspace
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source.svg';source.write_bytes(SVG)
            curves=svg_to_curves(source)
            session={'workspace_state':{'root':directory,'drafts':{},'workdirs':{}},'svg_result':{'svg':SVG.decode(),'curves':curves,'connectivity':{'count':1}}}
            with patch.object(workspace,'st',SimpleNamespace(session_state=session)):
                workspace.collect('svg')
                draft=workspace.draft('svg')
            self.assertEqual([a.name for a in draft.artifacts],['generated_curves.json'])
            saved=DraftStore(directory).publish(draft)
            self.assertEqual([a['kind'] for a in saved],['curve'])


if __name__ == '__main__':unittest.main()
