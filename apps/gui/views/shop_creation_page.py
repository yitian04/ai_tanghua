"""Three shop interactions in one responsive, persistent creation surface."""
import base64
import hashlib
import json
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET

import streamlit as st
import streamlit.components.v2 as components
from apps.gui import workspace
from apps.gui.image_viewer import image_viewer
from src.core.asset_conversion import convert_payload
from src.core.assets import AssetLibrary
from src.core.models import CurveList
from src.pipeline.shop_creation import catalog, drawing_curves, drawing_signature, generate_reference, WEATHER, WEATHER_MESSAGES
from src.pipeline.shop_window import compose_window, Window


@st.cache_resource
def _component(script):
    return components.component('shop_creation_'+hashlib.sha256(script.encode()).hexdigest()[:12],js=script)


def _uri(payload,mime):
    return 'data:'+mime+';base64,'+base64.b64encode(payload).decode()


def _accept():
    event=st.session_state.get('shop_creation_canvas',{}).get('event')
    if not event or event.get('token')==st.session_state.get('shop_creation_ack'):return
    st.session_state['shop_creation_ack']=event['token']
    st.session_state['shop_creation_event']=event


def render(config,root_dir):
    del config
    root=Path(root_dir);styles=catalog(root)
    if 'shop_creation_state' not in st.session_state:
        st.session_state['shop_creation_state']={'mode':'draw','strokes':[],'prompt':styles[0]['themes'][0],
                                                 'style':styles[0]['id'],'wheel':None}
        st.session_state['shop_creation_editor_id']=uuid.uuid4().hex
    state=st.session_state['shop_creation_state']
    template=CurveList.from_dict(json.loads((Path(__file__).resolve().parents[3]/'resources/shop_whitebox/template_curves.json').read_text(encoding='utf-8')))
    error='';event=st.session_state.pop('shop_creation_event',None)
    if event:
        try:
            incoming=event['state']
            if incoming['mode'] not in ('draw','ai','wheel') or incoming['style'] not in {x['id'] for x in styles}:
                raise ValueError('创作方式或画风无效。')
            if not isinstance(incoming['prompt'],str) or len(incoming['prompt'])>500:raise ValueError('描述不能超过500字。')
            if incoming.get('wheel') not in [None,*range(7)]:raise ValueError('抽取结果无效。')
            if incoming['strokes']:drawing_curves(incoming['strokes'])
            state.update(incoming)
            action=event['action']
            if action=='compose':
                content=drawing_curves(state['strokes'])
                merged,stats=compose_window(template,content,(800,456),metadata={'source':'freehand'})
                merged.metadata['shop_window']['example_test']=False
                st.session_state['shop_result']={'signature':drawing_signature(state['strokes']),
                                                 'content':content,'merged':merged,'stats':stats}
            elif action=='generate':
                if not state['prompt'].strip():raise ValueError('请先描述橱窗场景。')
                style=next(s for s in styles if s['id']==state['style'])
                output=root/'data/.drafts/shop'/st.session_state['shop_creation_editor_id']/(uuid.uuid4().hex+'.png')
                output.parent.mkdir(parents=True,exist_ok=True)
                with st.spinner('正在生成橱窗参考图…'):
                    result,prompt=generate_reference(root,style,state['prompt'],output,st.session_state)
                if result.provider_id == 'comfyui':
                    record = {'model': result.model_id, 'provider': result.provider_id,
                              'prompt': prompt, 'usage': result.usage, 'request_id': result.request_id}
                    result.output_path.with_suffix('.comfyui.json').write_text(
                        json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8',
                    )
                st.session_state['shop_ai_result']={'path':str(result.output_path),'theme':state['prompt'],
                    'style':state['style'],'prompt':prompt,'model':result.model_id,'provider':result.provider_id,
                    'reference_used':'No reference image input was supplied' not in prompt}
            elif action=='save_ai':
                result=st.session_state.get('shop_ai_result')
                if not result:raise ValueError('请先生成参考图。')
                workspace.collect('shop')
                result['saved']=workspace.publish('shop')
                st.success('参考图已保存至素材库。')
        except Exception as exc:
            error=str(exc)
    st.session_state['shop_current_signature']=drawing_signature(state['strokes'])
    template_svg,_=convert_payload(json.dumps(template.to_dict()).encode(),'template.json')
    node=ET.fromstring(template_svg);xmin,ymin,width,height=map(float,node.attrib['viewBox'].split())
    node.set('stroke-width','2.4');node.set('stroke','#824719')
    template_svg=ET.tostring(node,encoding='utf-8')
    window=Window()
    ai=st.session_state.get('shop_ai_result');ai_image=''
    if ai and Path(ai['path']).is_file():ai_image=_uri(Path(ai['path']).read_bytes(),'image/png')
    script=(Path(__file__).resolve().parents[1]/'components/shop_creation.js').read_text(encoding='utf-8')
    _component(script)(key='shop_creation_canvas',data={'editor_id':st.session_state['shop_creation_editor_id'],
        'ack':st.session_state.get('shop_creation_ack'),'state':state,'styles':styles,'weather':WEATHER,
        'messages':WEATHER_MESSAGES,'template':_uri(template_svg.replace(b'#000000',b'#824719'),'image/svg+xml'),
        'bounds':{'width':width,'height':height},
        'window':{'left':100*(window.xmin-xmin)/width,'top':100*(window.ymin-ymin)/height,
                  'width':100*(window.xmax-window.xmin)/width,'height':100*(window.ymax-window.ymin)/height},
        'error':error,'ai_image':ai_image,'ai_stale':bool(ai and (ai['theme']!=state['prompt'] or ai['style']!=state['style']))},
        on_event_change=_accept,height='content')
    result=st.session_state.get('shop_result')
    if state['mode']=='draw' and result:
        stale=result['signature']!=st.session_state['shop_current_signature']
        if stale:st.warning('手绘已修改，请重新合成后保存。')
        else:
            with st.expander('完整小店 · 合成预览',expanded=True):
                payload=json.dumps(result['merged'].to_dict(),ensure_ascii=False,indent=2).encode()
                svg,name=convert_payload(payload,'小店合并曲线.json');image_viewer(svg,key='shop_composed',filename=name)
        workspace.collect('shop')
        raw=json.dumps(result['content'].to_dict(),ensure_ascii=False,indent=2).encode()
        st.download_button('下载手绘原稿 JSON',raw,'小店手绘原稿.json',disabled=stale)
        st.download_button('下载合并曲线 JSON',json.dumps(result['merged'].to_dict(),ensure_ascii=False,indent=2).encode(),
                           '小店合并曲线.json',disabled=stale)
        if st.button('保存手绘与合并曲线到素材库',disabled=stale):
            workspace.publish('shop');st.success('手绘原稿与合并曲线已保存至素材库。')
        if st.button('进入轨迹规划',disabled=stale):
            st.session_state['pending_navigation']='轨迹规划';st.rerun()
    if state['mode']=='ai' and ai_image:
        workspace.collect('shop')
        st.download_button('下载参考图',Path(ai['path']).read_bytes(),'小店参考图.png')
        st.caption('当前为候选画风，最终参考图待筛选。')
        if not ai.get('reference_used',True):st.caption('当前模型按文字生成，本次未传入画风参考图。')
