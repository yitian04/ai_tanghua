import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from src.core.assets import AssetLibrary,classify
from src.core.models import Trajectory,TrajectoryPoint


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.lib=AssetLibrary(self.root)
        image=Image.new('RGB',(20,20),'white');buf=io.BytesIO();image.save(buf,format='PNG');self.image=buf.getvalue()
        self.curve=json.dumps({'curves':[{'points':[[0,0],[1,2]]}]}).encode()
        self.trajectory=json.dumps(Trajectory([TrajectoryPoint(0,0,0,10,True),TrajectoryPoint(1,2,0,10,True)]).to_dict()).encode()

    def test_classification_routing_and_no_overwrite(self):
        for payload,name,folder in [(self.image,'a.png','images'),(self.curve,'a.json','curves'),(self.trajectory,'b.json','trajectories')]:
            asset=self.lib.import_file(payload,name)
            self.assertIn('/'+folder+'/',asset['id'])
        first=self.lib.import_file(self.image,'a.png');second=self.lib.import_file(self.image,'a.png')
        self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(len(self.lib.scan()),5)
        for payload,name in [(self.image,'a.jpg'),(b'{"task_id":"x"}','task.json'),(b'{"curves":[]}','empty.json'),(b'bad','a.png'),(b'<svg><script/></svg>','a.svg')]:
            with self.assertRaises((ValueError,OSError)):classify(payload,name)

    def test_recycle_restore_collision_and_purge(self):
        asset=self.lib.import_file(self.image,'a.png');self.lib.delete(asset)
        self.assertFalse(self.lib.path(asset['id']).exists());self.assertEqual(self.lib.scan(),[])
        token=self.lib.trash_items()[0]['trash_id']
        self.lib.import_file(self.image,'a.png')
        restored=self.lib.restore(token)
        self.assertNotEqual(restored['id'],asset['id'])
        self.lib.delete(restored);self.lib.purge(self.lib.trash_items()[0]['trash_id'])
        self.assertEqual(self.lib.trash_items(),[])

    def test_legacy_project_trash_survives_removed_import_support(self):
        import hashlib
        from src.pipeline.trajectory_composition.composer import Composition
        from src.core.asset_previews import render_preview
        from apps.gui.asset_library import LABELS
        asset=self.lib.import_file(self.trajectory,'old.json');self.lib.delete(asset)
        token=self.lib.trash_items()[0]['trash_id'];folder=self.lib.trash_path(token)
        payload=json.dumps(Composition().to_dict()).encode()
        (folder/'payload').write_bytes(payload)
        record=json.loads((folder/'record.json').read_text(encoding='utf-8'))
        record.update(kind='project',name='old.project.json',id='data/compositions/old.project.json',size=len(payload),fingerprint=[1,len(payload),hashlib.sha256(payload).hexdigest()])
        (folder/'record.json').write_text(json.dumps(record),encoding='utf-8')
        archived=self.lib.trash_items()[0]
        self.assertEqual(LABELS.get(archived['kind'],'历史文件'),'历史文件')
        self.assertIsNone(render_preview(payload,record['name'],'project'))
        restored=self.lib.restore(token)
        self.assertEqual(self.lib.path(restored['id']).read_bytes(),payload)
        self.assertEqual(self.lib.trash_items(),[])
        self.assertEqual(self.lib.scan(),[])
        with self.assertRaises(ValueError):classify(payload,record['name'])

    def test_changed_file_and_exclusions(self):
        asset=self.lib.import_file(self.curve,'a.json')
        self.lib.path(asset['id']).write_bytes(self.curve+b' ')
        with self.assertRaises(ValueError):self.lib.delete(asset)
        for folder in ['model_gateway','software_checks','vectorization_temp']:
            p=self.root/'data'/folder/'a.png';p.parent.mkdir(parents=True);p.write_bytes(self.image)
        self.assertEqual(len(self.lib.scan()),1)
        with self.assertRaises(ValueError):self.lib.path('../outside.json')
        with self.assertRaises(ValueError):self.lib.purge('../outside')

    def test_local_folder_and_reveal_validate_before_opening(self):
        asset=self.lib.import_file(self.image,'中文 名称.png')
        with patch('src.core.local_files.show_in_folder') as show:
            self.lib.open_folder()
            show.assert_called_with(self.root/'data')
            self.lib.reveal(asset)
            show.assert_called_with(self.lib.path(asset['id']),select=True)
            self.lib.path(asset['id']).write_bytes(self.image+b' ')
            show.reset_mock()
            with self.assertRaises(ValueError):self.lib.reveal(asset)
            show.assert_not_called()
            with self.assertRaises(ValueError):self.lib.reveal({**asset,'id':'../outside.png'})
            show.assert_not_called()
            asset=self.lib.inspect(asset['id']);self.lib.delete(asset)
            trash=self.lib.trash_items()[0]
            self.lib.reveal(trash)
            show.assert_called_with(self.lib.trash_path(trash['trash_id'])/'payload',select=True)
            self.lib.open_folder(trash=True)
            show.assert_called_with(self.lib.trash)

    def test_distinct_svg_urp_categories_and_asset_read(self):
        svg=self.lib.import_file(b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L20 10"/></svg>','line.svg')
        urp=self.lib.import_file(b'<URProgram/>','program.urp')
        self.assertEqual(svg['category'],'SVG')
        self.assertEqual(urp['category'],'执行文件（URP）')
        self.assertEqual(self.lib.read(urp),b'<URProgram/>')
        self.lib.delete(svg)
        self.assertEqual(self.lib.trash_items()[0]['category'],'SVG')


if __name__=='__main__':unittest.main()
