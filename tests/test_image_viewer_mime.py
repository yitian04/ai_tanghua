import io
import unittest
from PIL import Image,PngImagePlugin
from apps.gui.image_viewer import payload_mime


class ImageViewerMimeTests(unittest.TestCase):
    def test_png_containing_svg_metadata_remains_png(self):
        meta=PngImagePlugin.PngInfo();meta.add_text('description','Embedded <svg xmlns="http://www.w3.org/2000/svg">metadata</svg>')
        output=io.BytesIO();Image.new('RGB',(20,20),'white').save(output,format='PNG',pnginfo=meta)
        self.assertIn(b'<svg',output.getvalue()[:1000])
        self.assertEqual(payload_mime(output.getvalue()),'image/png')

    def test_svg_with_xml_declaration_and_long_comment(self):
        payload=('<?xml version="1.0"?>\n<!--'+'a'*1500+'--><svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0L20 20"/></svg>').encode()
        self.assertEqual(payload_mime(payload),'image/svg+xml')

    def test_invalid_content_is_rejected(self):
        for payload in (b'bad',b'<html/>'):
            with self.assertRaises(ValueError):payload_mime(payload)
