import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import Mock

from src.core.models import CurveList,Curve2D
from src.pipeline.shop_creation import catalog,drawing_curves,drawing_signature,inspiration,shared_image_provider,generate_reference
from src.pipeline.shop_window import compose_window,Window
from streamlit.testing.v1 import AppTest


class CreationTests(unittest.TestCase):
    def test_original_order_direction_and_separate_strokes_survive_round_trip(self):
        strokes=[[[100,100],[20,120]],[[300,240],[400,260]]]
        original=drawing_curves(strokes)
        loaded=CurveList.from_dict(json.loads(json.dumps(original.to_dict())))
        self.assertEqual([c.points for c in loaded.curves],strokes)
        self.assertEqual(loaded.metadata['canvas_size'],[800,456])
        template=CurveList([Curve2D([[0,0],[100,0],[100,60],[0,60],[0,0]],closed=True)])
        merged,stats=compose_window(template,loaded,(800,456),Window(0,0,100,60),0,0)
        self.assertEqual(stats['content_curves'],2)
        self.assertGreater(merged.curves[1].points[0][0],merged.curves[1].points[-1][0])
        self.assertNotEqual(drawing_signature(strokes),drawing_signature(strokes[:1]))

    def test_invalid_and_empty_drawings(self):
        for strokes in ([],[[[1,1]]],[[[1,1],[math.nan,1]]],[[[-1,0],[5,5]]],[[[0,0],[800,0]]]):
            with self.assertRaises(ValueError):drawing_curves(strokes)

    def test_catalog_and_inspiration(self):
        styles=catalog('.')
        self.assertEqual(len(styles),6);self.assertEqual(sum(len(s['themes']) for s in styles),18)
        root=Path(__file__).resolve().parents[1]
        for s in styles:
            self.assertTrue((root/s['candidate_reference']).is_file())
            self.assertIn('line_language',s)
            previous=s['themes'][0]
            for _ in range(20):
                current=inspiration(styles,s['id'],previous)
                self.assertNotEqual(current,previous);previous=current

    def test_shared_live_provider_is_reused_without_mutating_its_edit_model(self):
        provider=SimpleNamespace(provider_id='bananapro',generation_model='nano-banana-pro',edit_model='other')
        options=SimpleNamespace(size='1024x1024')
        reused,opts=shared_image_provider('.',{'shared_sample_image_runtime':(provider,options,True)})
        self.assertEqual(reused.generation_model,provider.generation_model)
        self.assertIsNot(reused,provider)
        reused.edit_model='changed';self.assertEqual(provider.edit_model,'other')

    def test_text_only_model_does_not_switch_to_a_different_edit_model(self):
        from src.pipeline.image_generation.providers import ImageCallResult
        from PIL import Image
        output=Path(tempfile.gettempdir())/'shop_test_16_9.png'
        Image.new('RGB',(160,90),'white').save(output)
        expected=ImageCallResult(output,'siliconflow','test')
        provider=SimpleNamespace(provider_id='siliconflow',generate=Mock(return_value=expected),edit=Mock())
        from src.pipeline.image_generation.providers import ImageRequestOptions
        with patch('src.pipeline.shop_creation.shared_image_provider',return_value=(provider,ImageRequestOptions())):
            result,prompt=generate_reference('.',catalog('.')[0],'小鹿和兔子','unused.png')
        self.assertEqual(result,expected);provider.generate.assert_called_once();provider.edit.assert_not_called()
        self.assertIn('No reference image input was supplied',prompt)

    def test_ratio_gate_pads_only_near_landscape_and_rejects_square(self):
        from PIL import Image
        from src.pipeline.image_generation.providers import ImageCallResult,ImageRequestOptions
        with tempfile.TemporaryDirectory() as directory:
            for width,height,accepted in [(1376,768,True),(1024,1024,False)]:
                path=Path(directory)/f'{width}.png'
                original=Image.new('RGB',(width,height),'white');original.putpixel((13,17),(0,0,0));original.save(path)
                provider=SimpleNamespace(provider_id='siliconflow',generate=Mock(return_value=ImageCallResult(path,'siliconflow','test')))
                with patch('src.pipeline.shop_creation.shared_image_provider',return_value=(provider,ImageRequestOptions())):
                    if not accepted:
                        with self.assertRaises(ValueError):generate_reference('.',catalog('.')[0],'太阳',path)
                    else:
                        result,_=generate_reference('.',catalog('.')[0],'太阳',path)
                        with Image.open(result.output_path) as output:
                            self.assertEqual(output.width*9,output.height*16)
                            x=(output.width-width)//2;y=(output.height-height)//2
                            self.assertEqual(output.crop((x,y,x+width,y+height)).tobytes(),original.tobytes())
                        self.assertTrue(path.with_name(path.stem+'.native.png').exists())

    def test_saved_project_model_and_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir()
            (root/'config/ai_generation_defaults.json').write_text(json.dumps({'stages':{'sample':{'source':'bananapro','provider_id':'bananapro','model_id':'nano-banana-pro'}}}))
            with patch('src.pipeline.shop_creation.create_image_provider',side_effect=lambda c:c):
                config,options=shared_image_provider(root)
            self.assertEqual(config.model,'nano-banana-pro')
            self.assertEqual(config.edit_model,config.model)

    def test_page_composition_draft_and_ai_failure_keep_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            code=f'''from apps.gui.views.shop_creation_page import render
from apps.gui.views import shop_creation_page
from apps.gui import workspace
workspace.state()['root']={directory!r}
def fake_generate(*args,**kwargs):
    raise RuntimeError('测试服务暂不可用')
from unittest.mock import patch
with patch.object(shop_creation_page,'generate_reference',fake_generate), patch.object(shop_creation_page,'_component',lambda script: lambda **kwargs: None):
    render({{}},{directory!r})'''
            app=AppTest.from_string(code).run(timeout=30)
            self.assertFalse(list(app.exception))
            state=dict(app.session_state['shop_creation_state'])
            state['strokes']=[[[100,100],[200,160]],[[300,200],[400,300]]]
            app.session_state['shop_creation_event']={'token':'draw','action':'compose','state':state}
            app.run(timeout=30)
            self.assertFalse(list(app.exception))
            self.assertEqual(len(app.session_state['shop_result']['content'].curves),2)
            self.assertEqual(len(app.session_state['workspace_state']['drafts']['shop'].artifacts),2)
            state.update(mode='ai',prompt='自定义输入不得丢失')
            app.session_state['shop_creation_event']={'token':'fail','action':'generate','state':state}
            app.run(timeout=30)
            self.assertFalse(list(app.exception))
            self.assertEqual(app.session_state['shop_creation_state']['prompt'],'自定义输入不得丢失')
            self.assertNotIn('shop_ai_result',app.session_state)


if __name__=='__main__':unittest.main()
