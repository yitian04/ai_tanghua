import unittest
import numpy as np
from PIL import Image
from src.core.image_pixels import white_background, white_background_array
from src.modules.image_process_module import threshold_image, create_binary_preview, vectorize_image_to_curve_list


class TransparentImageTests(unittest.TestCase):
    def test_hidden_black_pixels_become_white_and_partial_alpha_blends(self):
        pixels=np.array([[[0,0,0,0],[0,0,0,128],[0,0,0,255]]],dtype=np.uint8)
        expected=np.array([[[255]*3,[127]*3,[0]*3]],dtype=np.uint8)
        np.testing.assert_array_equal(white_background_array(pixels),expected)
        np.testing.assert_array_equal(np.array(white_background(Image.fromarray(pixels))),expected)

    def test_palette_transparency_is_respected(self):
        image=Image.new('P',(2,1));image.putpalette([0,0,0,255,0,0]+[0]*762)
        image.putdata([0,1]);image.info['transparency']=0
        self.assertEqual(list(white_background(image).getdata()),[(255,255,255),(255,0,0)])

    def test_transparent_and_white_sources_have_identical_curves(self):
        rgba=np.zeros((180,260,4),dtype=np.uint8)
        rgba[50:58,30:230,3]=255
        rgb=white_background_array(rgba)
        for method in ('manual','otsu','adaptive'):
            np.testing.assert_array_equal(threshold_image(rgba,method),threshold_image(rgb,method))
        first,_=create_binary_preview(rgba,max_preview_dim=128,input_mode='line_only')
        second,_=create_binary_preview(rgb,max_preview_dim=128,input_mode='line_only')
        np.testing.assert_array_equal(first,second)
        a=vectorize_image_to_curve_list(rgba);b=vectorize_image_to_curve_list(rgb)
        self.assertTrue(a.curves)
        self.assertEqual([c.to_dict() for c in a.curves],[c.to_dict() for c in b.curves])


if __name__=='__main__':unittest.main()
