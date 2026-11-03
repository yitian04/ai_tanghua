import copy
import io
import json
import tempfile
import unittest
from unittest.mock import patch
from src.pipeline.svg_generation.service import *

SVG='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" fill="none" stroke="#000000" stroke-width="2"><path d="M10 10 L90 90"/></svg>'

class SVGTests(unittest.TestCase):
    def test_valid_and_fenced(self):
        for raw in (SVG,'```svg\n'+SVG+'\n```'):
            svg,curves=parse_result(raw,100,100)
            self.assertEqual(curves.curves[0].points,[[10.,10.],[90.,90.]])
            self.assertNotIn('source_svg',curves.metadata)
    def test_inert_comments_allowed_but_active_xml_rejected(self):
        comment='<!-- 兔子身体：普通说明 -->'
        source=SVG.replace('<path',comment+'<path')
        text,curves=parse_result(source,100,100)
        self.assertIn(comment,text)
        self.assertEqual(curves.curves[0].points,[[10.,10.],[90.,90.]])
        for bad in ('<!DOCTYPE svg>'+SVG,'<?xml version="1.0"?>'+SVG,SVG.replace('<path','<!-- broken -- comment --><path'),SVG.replace('<path','<!-- unclosed <path')):
            with self.assertRaises(ValueError):parse_result(bad,100,100)

    def test_invalid_outputs_rejected(self):
        bad=[SVG+SVG,'explanation '+SVG,SVG[:-10],SVG.replace('L90 90','A10 10 0 0 0 90 90'),SVG.replace('L90 90','L90'),SVG.replace('L90 90','Z 1 2'),SVG.replace('fill="none"','fill="black"'),SVG.replace('<path','<path onclick="alert(1)"'),SVG.replace('<path','<path transform="translate(1 2)"'),SVG.replace('L90 90','L900 90'),SVG.replace('<path','<image'),SVG.replace('M10 10','MNaN 10'),SVG.replace('viewBox','onload')]
        for raw in bad:
            with self.subTest(raw=raw[:100]),self.assertRaises((ValueError,IndexError)):parse_result(raw,100,100)
    def test_connectivity_crossing_near_and_isolated(self):
        from src.core.models import Curve2D,CurveList
        curves=CurveList([Curve2D([[0,5],[10,5]]),Curve2D([[5,0],[5,10]])])
        before=copy.deepcopy(curves.to_dict());self.assertEqual(connected_components(curves)['count'],1)
        curves.curves.append(Curve2D([[30,30],[40,40]]))
        self.assertEqual(connected_components(curves)['count'],2)
        self.assertEqual(curves.curves[0].to_dict(),before['curves'][0])
    def test_chat_single_request_and_no_reference_without_consent(self):
        client=ChatClient('https://example.test/v1','private-key')
        response={'choices':[{'message':{'content':SVG},'finish_reason':'stop'}],'model':'returned','usage':{'total_tokens':12}}
        with patch.object(client,'request',return_value=response) as request:
            result=client.generate('model','bird',DEFAULT_PROMPT,100,100)
            self.assertEqual(result['model'],'returned');request.assert_called_once()
            request.reset_mock()
            with self.assertRaises(ValueError):client.generate('model','bird',DEFAULT_PROMPT,100,100,b'img',False)
            request.assert_not_called()
        self.assertNotIn('糖画',DEFAULT_PROMPT)
    def test_http_failure_has_no_secret_or_retry(self):
        from unittest.mock import Mock
        opener=Mock();opener.open.side_effect=urllib.error.HTTPError('url',403,'denied',{},None)
        with self.assertRaisesRegex(SVGError,'403') as error:ChatClient('https://example.test/v1','secret',opener).models()
        self.assertNotIn('secret',str(error.exception));opener.open.assert_called_once()
    def test_page_load_never_calls_model(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as root,patch.object(ChatClient,'request') as request:
            app=AppTest.from_string(f"from apps.gui.views.svg_generation_page import render\nrender({{}},{root!r})").run()
            self.assertFalse(app.exception,list(app.exception));request.assert_not_called()

if __name__=='__main__':unittest.main()

class SVGJobTests(unittest.TestCase):
    def test_rerender_snapshots_never_restart_slow_request(self):
        from threading import Event
        import time,uuid
        from src.pipeline.svg_generation import jobs
        entered=Event();release=Event();calls=[]
        def slow(self,*args,**kwargs):
            calls.append(1);entered.set();release.wait(2)
            return {'raw':SVG,'finish_reason':'stop','model':'fixture','usage':{}}
        with patch.object(ChatClient,'generate',slow):
            token=uuid.uuid4().hex
            job=jobs.submit(token,'https://example.test/v1','secret','m','bird',DEFAULT_PROMPT,100,100,2.)
            self.assertTrue(entered.wait(1))
            for _ in range(5):self.assertEqual(jobs.snapshot(job)['phase'],'requesting')
            self.assertEqual(jobs.submit(token,'https://example.test/v1','secret','m','bird',DEFAULT_PROMPT,100,100,2.),job)
            release.set()
            deadline=time.monotonic()+3
            while jobs.snapshot(job)['phase'] not in {'completed','failed'} and time.monotonic()<deadline:time.sleep(.01)
            result=jobs.snapshot(job);self.assertEqual(result['phase'],'completed');self.assertEqual(len(calls),1)
            self.assertNotIn('secret',repr(result));self.assertEqual(jobs.snapshot('missing')['phase'],'unknown')
