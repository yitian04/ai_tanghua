import json
from pathlib import Path
import tempfile
import unittest

from streamlit.testing.v1 import AppTest
from src.core.assets import AssetLibrary, classify
from src.core.asset_conversion import convert_payload, convert_and_save


SVG=b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M10 10 C10 30 30 30 30 10"/></svg>'
CURVES=json.dumps({'coordinate_frame':'layout_mm','curves':[
    {'curve_id':0,'points':[[-10,5],[20,5],[20,30]],'closed':False},
    {'curve_id':1,'points':[[30,10],[40,10],[40,20],[30,10]],'closed':True},
]}).encode()


class ConversionTests(unittest.TestCase):
    def test_svg_to_json_is_sampled_and_has_no_temporary_source(self):
        data,name=convert_payload(SVG,'shop.svg')
        self.assertEqual(name,'shop_curves.json')
        self.assertEqual(classify(data,name),'curve')
        result=json.loads(data)
        self.assertGreater(len(result['curves'][0]['points']),2)
        self.assertEqual(result['metadata']['source_svg'],'shop.svg')

    def test_curve_roundtrip_preserves_coordinates_order_and_frame(self):
        svg,name=convert_payload(CURVES,'shop.json')
        self.assertEqual(classify(svg,name),'svg')
        self.assertNotIn(b'<image',svg)
        restored,_=convert_payload(svg,name)
        result=json.loads(restored)
        self.assertEqual(result['coordinate_frame'],'layout_mm')
        self.assertEqual([c['points'] for c in result['curves']], [c['points'] for c in json.loads(CURVES)['curves']])
        self.assertEqual([c['closed'] for c in result['curves']],[False,True])

    def test_save_routes_and_collision_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            lib=AssetLibrary(directory);source=lib.import_file(SVG,'shop.svg')
            first=convert_and_save(lib,source);second=convert_and_save(lib,source)
            self.assertNotEqual(first['id'],second['id'])
            self.assertIn('/curves/',first['id'])
            restored=convert_and_save(lib,first)
            self.assertIn('/images/',restored['id'])
            self.assertEqual(lib.read(source),SVG)
            lib.path(source['id']).write_bytes(SVG+b' ')
            with self.assertRaisesRegex(ValueError,'变化'):convert_and_save(lib,source)
            self.assertEqual(len(lib.scan()),4)

    def test_preview_button_saves_once_and_retains_source(self):
        with tempfile.TemporaryDirectory() as directory:
            lib=AssetLibrary(directory);source=lib.import_file(SVG,'shop.svg')
            code=f'''import streamlit as st
from types import SimpleNamespace
from src.core.assets import AssetLibrary
from apps.gui.asset_library import _conversion_button
lib=AssetLibrary({directory!r})
item=lib.inspect({source['id']!r})
q=st.session_state.setdefault('q',{{'nonce':'test'}})
left,right=st.columns([1,5])
with left:_conversion_button(q,lib,SimpleNamespace(refresh=lambda:None),item,lib.read(item))
'''
            app=AppTest.from_string(code).run(timeout=30)
            self.assertFalse(list(app.exception),list(app.exception))
            app.button[0].click().run(timeout=30)
            self.assertFalse(list(app.exception),list(app.exception))
            app.run(timeout=30)
            self.assertTrue(app.button[0].disabled)
            self.assertEqual(len(lib.scan()),2)
            self.assertEqual(lib.read(source),SVG)

    def test_invalid_conversion_does_not_save(self):
        with tempfile.TemporaryDirectory() as directory:
            lib=AssetLibrary(directory)
            with self.assertRaises(ValueError):convert_and_save(lib,{'name':'empty.svg'},b'<svg/>')
            self.assertEqual(lib.scan(),[])


if __name__=='__main__':unittest.main()
