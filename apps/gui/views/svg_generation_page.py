from __future__ import annotations

from apps.gui.image_viewer import image_viewer, figure_viewer
import hashlib
import json
from pathlib import Path
import streamlit as native
from apps.gui.parameter_ui import ui as st
from apps.gui.asset_library import file_input
from apps.gui import workspace
from src.core.assets import AssetLibrary
from src.pipeline.svg_generation.service import ChatClient,Credentials,DEFAULT_PROMPT,parse_result,connected_components


def render(config,root_dir):
    st.subheader('AI SVG 曲线')
    st.caption('描述主题，由文本模型直接生成 SVG 并解析为曲线；实际毫米尺寸在轨迹规划中设置。')
    inputs,outputs=st.columns([2,3],gap='small')
    with inputs:
        credentials=Credentials(root_dir);saved=credentials.load()
        with st.expander('模型与接口',expanded=not bool(saved.get('api_key')),key='svg_model_expander',on_change='rerun'):
            provider=st.selectbox('接口服务',['ChatAnywhere','自定义兼容接口'])
            if provider=='ChatAnywhere':
                base='https://api.chatanywhere.tech/v1'
                native.text_input('API 地址',value=base,disabled=True)
            else:base=st.text_input('API 地址',value=saved.get('base','https://api.chatanywhere.tech/v1'))
            key=st.text_input('API 密钥',value=saved.get('api_key','') if saved.get('base')==base else '',type='password',key='svg_credential_'+hashlib.sha256(base.encode()).hexdigest()[:12])
            if st.button('保存私有凭据'):
                credentials.save(base,key);st.success('已保存至独立私有配置，不进入素材或参数默认值。')
            if st.button('读取模型列表'):
                try:
                    st.session_state['svg_model_list']=ChatClient(base,key).models();st.session_state['svg_model_origin']=base
                except Exception as exc:st.warning(str(exc))
            choices=st.session_state.get('svg_model_list',[]) if st.session_state.get('svg_model_origin')==base else []
    
            selected=st.selectbox('选择服务模型',['']+choices,key='svg_model_list_pick',format_func=lambda value:value or '请选择模型，或在下方手填')
            manual=st.text_input('模型 ID',value='')
            model=selected or manual
            if selected:
                from src.core.preferences import PreferenceStore
                PreferenceStore(root_dir).remember('svg',{'模型 ID':selected})
            st.caption('当前模型：'+(model or '尚未选择'))
            st.caption('聊天接口模型列表不等于识图或 SVG 能力保证；不自动选择、替换或重试模型。')
        subject=st.text_area('主题与需求',key='svg_subject')
        with st.expander('提示词与高级参数',expanded=False,key='svg_advanced_expander',on_change='rerun'):
            prompt=st.text_area('创作提示词',value=DEFAULT_PROMPT,height=160,key='svg_prompt')
            a,b,c=st.columns(3)
            width=a.number_input('画布宽（SVG 单位）',min_value=64,max_value=4096,value=1024)
            height=b.number_input('画布高（SVG 单位）',min_value=64,max_value=4096,value=1024)
            tolerance=c.number_input('曲线采样间距（SVG 单位）',min_value=.2,max_value=20.,value=2.)
            if st.session_state.get('wf_running'):
                st.caption('生成中：参考图已冻结，可浏览全局素材库。')
                paths=st.session_state.get('asset_selected_svg_reference',[])
                reference=paths[0] if paths else None
            else:reference=file_input(root_dir,'svg_reference','可选参考图',{'image'})
            vision=st.checkbox('我确认此模型支持参考图',key='svg_vision_'+hashlib.sha256((base+model).encode()).hexdigest()[:12])
            if reference and not vision:st.info('已选择参考图；请确认模型识图能力后再生成，不会静默忽略图片。')
        if st.button('生成 SVG 曲线',type='primary',disabled=not subject.strip() or not model.strip() or not key.strip() or bool(reference and not vision)):
            try:
                payload=None
                if reference:
                    library=AssetLibrary(root_dir);item=library.inspect(Path(reference).resolve().relative_to(library.root));payload=library.read(item)
                from src.pipeline.svg_generation import jobs
                import uuid
                st.session_state['svg_job']=jobs.submit(uuid.uuid4().hex,base,key,model,subject,prompt,width,height,tolerance,payload,vision)
            except Exception as exc:st.error(str(exc))
    with outputs:
        _poll(root_dir)
        _output(root_dir)


def _output(root_dir):
    result=st.session_state.get('svg_result')
    if not result:
        if st.session_state.get('svg_raw'):
            st.code(st.session_state['svg_raw'],language='xml')
            st.download_button('下载诊断文本',st.session_state['svg_raw'],'svg_response.txt')
        return
    st.caption('返回模型：'+str(result['model'])+' · 用量：'+json.dumps(result['usage'],ensure_ascii=False))
    left,right=st.tabs(['SVG 原图','有序曲线'],key='svg_preview_tabs',on_change='rerun')
    with left:
        st.markdown('**SVG 原图**');image_viewer(result['svg'],width='stretch')
    with right:
        st.markdown('**转换后的有序曲线**')
        from apps.gui.views.vector_page import _plot_curves
        import matplotlib.pyplot as plt
        fig=_plot_curves(result['curves']);fig.axes[0].set_xlabel('SVG X');fig.axes[0].set_ylabel('SVG Y');figure_viewer(fig);plt.close(fig)
    curves=result['curves'];groups=result['connectivity']
    st.caption(f"{len(curves.curves)} 条曲线 · {sum(len(c.points) for c in curves.curves)} 个点 · {groups['count']} 个连通部分（采样几何容差 {groups['tolerance']} SVG 单位）。连通不等于一笔完成。")
    if groups['count']>1:
        st.warning('图案存在分离部分；不会自动连接或重新调用模型。')
        st.checkbox('我已查看分离部分，确认仍使用此结果',key='svg_ack')
        st.dataframe([{'曲线':i+1,'连通组':group} for i,group in enumerate(groups['curve_groups'])],hide_index=True)
    with st.expander('查看 SVG 源码'):st.code(result['svg'],language='xml')
    workspace.collect('svg')
    value=workspace.draft('svg')
    native.html('<style>.st-key-svg_inline_actions .st-key-workspace_actions{position:static!important;width:100%!important;max-width:100%!important;box-shadow:none!important}</style>')
    with native.container(key='svg_inline_actions'):workspace.render_controls(inline=True)
    if native.button('进入轨迹规划',disabled=not value or not value.valid):
        workspace.request_navigation('轨迹规划',transfer=True);st.rerun()


@native.fragment(run_every=.5)
def _poll(root_dir):
    job=st.session_state.get('svg_job')
    if not job:return
    from src.pipeline.svg_generation import jobs
    state=jobs.snapshot(job)
    if state['phase'] in {'completed','failed','unknown'}:
        if st.session_state.get('svg_claimed')!=job and 'asset_dialog' not in st.session_state:
            st.session_state['svg_claimed']=job
            st.session_state['svg_raw']=state.get('raw','')
            if state.get('result'):st.session_state['svg_result']=state['result']
            if state.get('error'):st.session_state['svg_job_error']=state['error']
            st.session_state['wf_running']=False
            native.rerun()
        if state.get('error'):native.error(state['error'])
    else:
        native.info({'queued':'排队中','requesting':'等待模型响应','validating':'校验与采样','connectivity':'检查连通性'}[state['phase']]+f" · 已等待 {state['elapsed']:.0f} 秒")
