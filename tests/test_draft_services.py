import json
import tempfile
import unittest
from pathlib import Path
from src.core.assets import AssetLibrary
from src.core.drafts import Artifact,Draft,DraftStore
from src.core.preferences import PreferenceStore


class DraftServicesTests(unittest.TestCase):
    def test_publish_is_explicit_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            payload=json.dumps({'curves':[{'points':[[0,0],[10,10]],'curve_id':0}]}).encode()
            value=Draft([Artifact('line.json',payload,'curves')],'revision')
            store=DraftStore(directory)
            self.assertEqual(store.library.scan(),[])
            first=store.publish(value);self.assertEqual(len(first),1)
            self.assertEqual(store.publish(value),first)
            second=store.publish(Draft([Artifact('line.json',payload,'curves')],'other'))
            self.assertNotEqual(first[0]['id'],second[0]['id'])
            self.assertEqual(len(store.library.scan()),2)

    def test_invalid_bundle_does_not_publish_partially(self):
        with tempfile.TemporaryDirectory() as directory:
            payload=json.dumps({'curves':[{'points':[[0,0],[10,10]]}]}).encode()
            store=DraftStore(directory)
            value=Draft([Artifact('line.json',payload,'curves'),Artifact('bad.json',b'bad','curves')],'revision')
            with self.assertRaises(ValueError):store.publish(value)
            self.assertEqual(store.library.scan(),[])

    def test_recent_defaults_and_restart_are_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            store=PreferenceStore(directory);store.seed('text','height',20)
            store.remember('text',{'height':30});store.save_defaults('text')
            store.remember('text',{'height':40})
            self.assertEqual(PreferenceStore(directory).current('text')['height'],40)
            self.assertEqual(store.restore('text')['height'],30)
            self.assertEqual(AssetLibrary(directory).scan(),[])


if __name__=='__main__':unittest.main()


class CompositionOutputTests(unittest.TestCase):
    def test_merge_draft_publishes_only_standard_trajectory(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from apps.gui import workspace
        from src.core.assets import classify
        from src.core.models import Trajectory,TrajectoryPoint
        from src.pipeline.trajectory_composition.composer import Composition,make_item
        with tempfile.TemporaryDirectory() as directory:
            doc=Composition()
            trajectory=Trajectory([TrajectoryPoint(0,0,0,10,True),TrajectoryPoint(10,10,0,10,True)])
            doc.items=[make_item(trajectory,'first',doc.plane),make_item(trajectory,'second',doc.plane)]
            session={'workspace_state':{'root':directory,'drafts':{},'workdirs':{}},'composition_document':doc}
            with patch.object(workspace,'st',SimpleNamespace(session_state=session)):
                workspace.collect('composition')
                value=workspace.draft('composition')
            self.assertTrue(value.valid)
            self.assertEqual(len(value.artifacts),1)
            self.assertEqual(classify(value.artifacts[0].payload,value.artifacts[0].name),'trajectory')
            files=DraftStore(directory).publish(value)
            self.assertEqual(len(files),1)
            self.assertFalse(any(Path(directory).rglob('*.project.json')))
            with self.assertRaisesRegex(ValueError,'不再支持合成工程'):
                classify(json.dumps(doc.to_dict()).encode(),'old.project.json')
