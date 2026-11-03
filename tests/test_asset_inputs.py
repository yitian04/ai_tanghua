"""Render file inputs without connecting to a model provider or robot."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
from streamlit.testing.v1 import AppTest
from src.core.assets import AssetLibrary
from src.core.models import Trajectory,TrajectoryPoint


class InputTests(unittest.TestCase):
    def test_direct_batch_import_is_ordered_deduplicated_and_undoable(self):
        from apps.gui import asset_library
        from apps.gui.views import composition_page
        from src.pipeline.trajectory_composition.composer import Composition
        with tempfile.TemporaryDirectory() as directory:
            lib=AssetLibrary(directory)
            payload=json.dumps(Trajectory([TrajectoryPoint(0,0,0,10,True),TrajectoryPoint(10,10,0,10,True)]).to_dict()).encode()
            items=[lib.import_file(payload,name) for name in ('first.json','second.json')]
            doc=Composition()
            q={'root':directory,'target':'composition_objects','kinds':['trajectory'],'multiple':True,'on_import':composition_page._import_objects,'import_selection':{i['id']:i for i in items}}
            session={'composition_document':doc,'asset_dialog':q,'asset_grid':{'event':{'token':'batch1','action':'use_selected'}}}
            fake=SimpleNamespace(session_state=session)
            with patch.object(asset_library,'st',fake),patch.object(composition_page,'st',fake),patch.object(asset_library,'get_index',return_value=SimpleNamespace(lib=lib)):
                asset_library._on_grid_event();asset_library._on_grid_event()
                self.assertTrue(q['completed'])
                self.assertEqual([i.name for i in doc.items],['first.json','second.json'])
                self.assertEqual(len(session['composition_history'].undo_stack),1)
                # A changed source rejects the whole next batch before editing.
                lib.path(items[1]['id']).write_bytes(payload+b' ')
                session['asset_grid']={'event':{'token':'batch2','action':'use_selected'}}
                asset_library._on_grid_event()
                self.assertEqual(len(doc.items),2)
                self.assertIn('变化',q['notice'])

    def test_grid_selection_preserves_nanosecond_file_identity(self):
        from apps.gui import asset_library
        first={'id':'data/images/a.png','fingerprint':(1793689298630808700,508,'a')}
        second={'id':'data/images/b.png','fingerprint':(1793689298622809301,508,'b')}
        dialog={'multi':True,'records':{item['id']:item for item in (first,second)}}
        session={'asset_dialog':dialog}
        with patch.object(asset_library,'st',SimpleNamespace(session_state=session)):
            for item in (first,second):
                session['asset_grid']={'event':{'token':item['id'],'action':'select','id':item['id'],'checked':True,'expected':list(map(str,item['fingerprint']))}}
                asset_library._on_grid_event()
            self.assertEqual(list(dialog['manager_selection']),[first['id'],second['id']])
            # A genuinely changed source must still be rejected.
            session['asset_grid']={'event':{'token':'changed','action':'select','id':first['id'],'checked':False,'expected':['0','508','a']}}
            asset_library._on_grid_event()
            self.assertEqual(len(dialog['manager_selection']),2)
            self.assertIn('变化',dialog['notice'])

    def test_remaining_module_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            lib=AssetLibrary(directory)
            buffer=io.BytesIO();Image.new('RGB',(30,30),'white').save(buffer,format='PNG')
            image=lib.import_file(buffer.getvalue(),'test.png')
            curve=lib.import_file(json.dumps({'curves':[{'points':[[0,0],[10,10]],'curve_id':0}]}).encode(),'curve.json')
            trajectory=lib.import_file(json.dumps(Trajectory([TrajectoryPoint(0,0,0,10,True),TrajectoryPoint(10,10,0,10,True)]).to_dict()).encode(),'trajectory.json')
            for module,key,asset in [('vector_page','vector',image),('planning_page','planning',curve),('export_page','export',trajectory),('robot_page','robot',trajectory)]:
                with self.subTest(module=module):
                    code=f'''from apps.gui.views import {module} as view
import streamlit as st
'''
                    if module=='robot_page':
                        code+='view._init_state=lambda config: None\nview._render_ur5_control=lambda *args: None\n'
                    code+=f'view.render({{}}, {directory!r})\n'
                    app=AppTest.from_string(code)
                    app.session_state[f'asset_selected_{key}']=[str(lib.path(asset['id']))]
                    app.run(timeout=30)
                    self.assertFalse(list(app.exception),list(app.exception))
                    self.assertFalse(any('路径' in t.label for t in app.text_input))
                    labels=[b.label for b in app.button]
                    self.assertIn('本地上传',labels)
                    self.assertIn('从素材库选择',labels)


if __name__=='__main__':unittest.main()
