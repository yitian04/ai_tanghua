from pathlib import Path
from copy import deepcopy
import json
import io
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from PIL import Image
from streamlit.testing.v1 import AppTest
from src.core.models import CurveList,Curve2D
from src.core.assets import AssetLibrary
from src.core.drafts import DraftStore
from src.pipeline.shop_window import compose_window,build_example,Window
from src.pipeline.planning.planner import TrajectoryPlanner

ROOT=Path(__file__).resolve().parents[1]
SAMPLES=ROOT/'resources/shop_whitebox'


def frame():
    return CurveList([Curve2D([[0,0],[100,0],[100,60],[0,60],[0,0]],closed=True)])


class ShopTests(unittest.TestCase):
    def test_clip_snap_overlap_and_template_immutability(self):
        template=frame();original=deepcopy(template.to_dict())
        content=CurveList([Curve2D([[-10,30],[30,30],[110,30]]),Curve2D([[0,60],[100,60]]),Curve2D([[20,20],[30,20]])])
        merged,stats=compose_window(template,content,(101,61),Window(0,0,100,60))
        self.assertEqual(template.to_dict(),original)
        self.assertEqual(merged.curves[0].points,template.curves[0].points)
        self.assertEqual(stats['content_curves'],2)
        self.assertAlmostEqual(stats['removed_overlap_length'],100)
        self.assertEqual(merged.curves[1].points[0],[0.,30.])
        self.assertEqual(merged.curves[1].points[-1],[100.,30.])
        self.assertGreater(stats['connectivity']['count'],1)
        for c in merged.curves[1:]:
            self.assertTrue(all(0<=p[0]<=100 and 0<=p[1]<=60 for p in c.points))
        self.assertEqual([c.curve_id for c in merged.curves],list(range(len(merged.curves))))

    def test_full_canvas_mapping_keeps_whitespace_and_splits_exits(self):
        content=CurveList([Curve2D([[10,10],[20,10],[110,70],[20,30]])])
        merged,stats=compose_window(frame(),content,(101,61),Window(0,0,100,60),snap_tolerance=0)
        self.assertEqual(merged.curves[1].points[0],[10.,10.])
        self.assertEqual(stats['content_curves'],2)
        self.assertNotEqual(merged.curves[1].points[-1],merged.curves[2].points[0])

    def test_sample_composition_plans_and_preserves_template(self):
        template=(SAMPLES/'template_curves.json').read_bytes();image=(SAMPLES/'generated_example.png').read_bytes()
        with patch('requests.post',side_effect=AssertionError('No network')):
            content,merged,stats=build_example(template,image)
        before=json.loads(template)['curves']
        self.assertTrue(content.curves)
        self.assertEqual([c.points for c in merged.curves[:len(before)]],[c['points'] for c in before])
        self.assertEqual([c.closed for c in merged.curves[:len(before)]],[c.get('closed',False) for c in before])
        for c in merged.curves[len(before):]:
            self.assertTrue(all(38.9-1e-7<=p[0]<=482.6+1e-7 and 144.6-1e-7<=p[1]<=397.2+1e-7 for p in c.points))
        self.assertTrue(TrajectoryPlanner().plan(merged).points)
        json.dumps(merged.to_dict())

    def test_rejects_invalid_inputs(self):
        template=json.dumps(frame().to_dict()).encode()
        output=io.BytesIO();Image.new('RGBA',(120,70),(0,0,0,0)).save(output,format='PNG')
        with self.assertRaises(ValueError):build_example(template,output.getvalue(),Window(0,0,100,60))
        with self.assertRaises(ValueError):build_example(b'{}',output.getvalue())
        with self.assertRaises(ValueError):compose_window(frame(),frame(),(101,61),Window(10,0,0,60))

    def test_page_draft_staleness_and_publish_once(self):
        with tempfile.TemporaryDirectory() as directory:
            code=f'''from apps.gui.views.shop_whitebox_page import render_example as render
from apps.gui import workspace
workspace.state()['root']={directory!r}
render({{}}, {directory!r})'''
            app=AppTest.from_string(code).run(timeout=30)
            self.assertFalse(list(app.exception),list(app.exception))
            next(b for b in app.button if b.label=='提取并合成').click().run(timeout=60)
            self.assertFalse(list(app.exception),list(app.exception))
            self.assertIn('shop_result',app.session_state)
            result=app.session_state['shop_result']
            self.assertTrue(result['merged'].curves)
            from apps.gui import workspace
            session={'workspace_state':{'root':directory,'drafts':{},'workdirs':{}},'shop_result':result,'shop_current_signature':result['signature']}
            with patch.object(workspace,'st',SimpleNamespace(session_state=session)):
                workspace.collect('shop');draft=workspace.draft('shop')
                store=DraftStore(directory);first=store.publish(draft)
                self.assertEqual(store.publish(draft),first)
                session['shop_current_signature']='changed';workspace.collect('shop')
                self.assertFalse(draft.valid)
                with self.assertRaises(ValueError):store.publish(draft)
            self.assertEqual(len(first),1)
            self.assertEqual(first[0]['kind'],'curve')
            next(t for t in app.text_area if t.label=='AI 提示词').input('changed').run(timeout=30)
            self.assertFalse(list(app.exception),list(app.exception))
            self.assertTrue(next(b for b in app.button if b.label=='进入轨迹规划').disabled)


if __name__=='__main__':unittest.main()
