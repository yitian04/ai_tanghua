import io
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from threading import Event
from PIL import Image
from src.core.assets import AssetLibrary
from src.core.asset_index import AssetIndex,batch_operation


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.lib=AssetLibrary(self.tmp.name)
        out=io.BytesIO();Image.new('RGB',(30,20),'white').save(out,format='PNG')
        self.payload=out.getvalue();self.asset=self.lib.import_file(self.payload,'a.png')
        self.idx=AssetIndex(self.tmp.name)
        self.addCleanup(self.idx.close)

    def idle(self): self.idx.queue.join()

    def test_persistent_warm_index_and_invalid_cache(self):
        bad=Path(self.tmp.name)/'data/images/bad.png';bad.write_bytes(b'bad')
        self.idx.refresh();self.idle()
        entries,pending=self.idx.snapshot();self.assertEqual(len(entries),1);self.assertEqual(pending,0)
        with patch.object(self.idx.lib,'inspect',side_effect=AssertionError('unchanged files must not be parsed')):
            self.idx.refresh();self.idle();self.assertFalse(self.idx.errors)
        second=AssetIndex(self.tmp.name)
        self.addCleanup(second.close)
        with patch.object(second.lib,'inspect',side_effect=AssertionError('disk index should be reusable')):
            second.refresh();second.queue.join();self.assertEqual(len(second.snapshot()[0]),1)

    def test_preview_and_no_deleted_reinsertion(self):
        self.idx.refresh();self.idle()
        first=self.idx.previews('owner',[self.asset]);key=self.idx.thumb_key(self.asset)
        self.assertEqual(first[key][0],'loading')
        self.idle();self.assertEqual(self.idx.previews('owner',[self.asset])[key][0],'ready')
        self.lib.delete(self.asset);self.idx.refresh();self.idle()
        self.assertEqual(self.idx.snapshot()[0],[])

    def test_batch_partial_failure_and_snapshot_purge(self):
        second=self.lib.import_file(self.payload,'b.png')
        self.lib.path(second['id']).write_bytes(self.payload+b' ')
        ok,failed=batch_operation(self.lib,'recycle',[self.asset,self.asset,second])
        self.assertEqual(ok,[self.asset['id']]);self.assertEqual(len(failed),1)
        snapshot=self.lib.trash_items()
        third=self.lib.import_file(self.payload,'c.png');self.lib.delete(third)
        ok,failed=batch_operation(self.lib,'purge',snapshot)
        self.assertFalse(failed);self.assertEqual(len(self.lib.trash_items()),1)
        self.assertEqual(self.lib.trash_items()[0]['name'],'c.png')

    def test_slow_preview_does_not_block_or_resurrect_deleted_file(self):
        self.idx.refresh();self.idle()
        entered=Event();release=Event()
        def slow(*args,**kwargs):
            entered.set();release.wait(5);return self.payload
        with patch('src.core.asset_index.render_preview',side_effect=slow):
            key=self.idx.thumb_key(self.asset)
            self.assertEqual(self.idx.previews('owner',[self.asset])[key][0],'loading')
            self.assertTrue(entered.wait(2))
            self.lib.delete(self.asset);self.idx.refresh()
            self.assertEqual(self.idx.snapshot()[0],[])
            release.set();self.idle()
            self.assertFalse((self.idx.cache/(key+'.png')).exists())

    def test_preview_failure_is_isolated_and_cache_can_be_rebuilt(self):
        self.idx.refresh();self.idle()
        with patch('src.core.asset_index.render_preview',side_effect=ValueError('broken preview')):
            key=self.idx.thumb_key(self.asset);self.idx.previews('owner',[self.asset]);self.idle()
            self.assertEqual(self.idx.previews('owner',[self.asset])[key][0],'error')
            self.assertEqual(len(self.idx.snapshot()[0]),1)
        self.idx.refresh()
        self.idx.previews('owner',[self.asset]);self.idle()
        self.assertEqual(self.idx.previews('owner',[self.asset])[key][0],'ready')


if __name__=='__main__':unittest.main()
