"""Small AI-window experiment using local sample assets, never a model call."""
from pathlib import Path
import hashlib
import json

from apps.gui.parameter_ui import ui as st
from apps.gui.asset_library import file_input
from apps.gui.image_viewer import image_viewer, figure_viewer
from apps.gui import workspace
from apps.gui.views.vector_page import _plot_curves
from src.core.assets import AssetLibrary
from src.core.asset_conversion import convert_payload
from src.pipeline.shop_window import Window, build_example
import matplotlib.pyplot as plt


def ensure_examples(root_dir):
    lib=AssetLibrary(root_dir)
    bundled=Path(__file__).resolve().parents[3]/'resources/shop_whitebox'
    result=[]
    for filename,name,folder in [('template_curves.json','whitebox_shop_template.json','curves'),('generated_example.png','whitebox_window_example.png','images')]:
        payload=(bundled/filename).read_bytes()
        path=Path('data')/folder/name
        try:
            asset=lib.inspect(path)
            if lib.read(asset)!=payload:raise ValueError('样例名称已有其他内容')
        except (ValueError,OSError):
            # Never overwrite an existing asset, even if its default name was reused.
            digest=hashlib.sha256(payload).hexdigest()[:12]
            versioned=Path(name).stem+'_'+digest+Path(name).suffix
            candidate=Path('data')/folder/versioned
            try:
                asset=lib.inspect(candidate)
                if lib.read(asset)!=payload:raise ValueError('内容不符')
            except (ValueError,OSError):asset=lib.import_file(payload,name if not (lib.root/path).exists() else versioned)
        result.append(asset)
    return lib,result


def render(config,root_dir):
    from apps.gui.views.shop_creation_page import render as render_creation
    return render_creation(config,root_dir)


def render_example(config,root_dir):
    st.subheader('理想小店（白盒）')
    st.caption('示例测试 · 使用预设素材模拟 AI 结果，不调用模型。')
    ways=st.columns(3)
    ways[0].button('手绘',disabled=True,width='stretch')
    ways[1].button('AI',disabled=True,type='primary',width='stretch')
    ways[2].button('转盘',disabled=True,width='stretch')
    lib,defaults=ensure_examples(root_dir)
    for key,asset in zip(('shop_template','shop_example'),defaults):
        statekey='asset_selected_'+key
        if statekey not in st.session_state:st.session_state[statekey]=[str(lib.path(asset['id']))]
    left,right=st.columns([1,1.7])
    with left:
        prompt=st.text_area('AI 提示词',value='森林里，小鹿和兔子一起迎接好天气。',key='shop_prompt')
        styles=st.text_input('风格关键词',value='简洁线稿，圆润，连续线条',key='shop_styles')
        template_path=file_input(root_dir,'shop_template','小店模板（曲线 JSON）',{'curve'})
        image_path=file_input(root_dir,'shop_example','模拟 AI 素材',{'image'})
        template=image=None;error=''
        try:
            if template_path:template=lib.inspect(Path(template_path).resolve().relative_to(lib.root))
            if image_path:image=lib.inspect(Path(image_path).resolve().relative_to(lib.root))
        except (ValueError,OSError) as exc:error=str(exc)
        template_identity=(template['id'],tuple(template['fingerprint'])) if template else None
        if st.session_state.get('shop_template_identity')!=template_identity:
            st.session_state['shop_template_identity']=template_identity
            st.session_state['shop_bounds_confirm']=False
        custom=bool(template and template['fingerprint'][2]!=defaults[0]['fingerprint'][2])
        with st.expander('高级设置',expanded=custom):
            values=[]
            for label,key,value in [('左边界','xmin',38.9),('上边界','ymin',144.6),('右边界','xmax',482.6),('下边界','ymax',397.2)]:
                values.append(st.number_input(label,value=value,key='shop_'+key,format='%.3f'))
            tolerance=st.number_input('曲线提取容差',min_value=.2,max_value=20.,value=1.2,key='shop_sampling')
            snap=st.number_input('贴边连接容差',min_value=0.,max_value=20.,value=2.,key='shop_snap')
            overlap=st.number_input('窗框重合容差',min_value=0.,max_value=20.,value=.5,key='shop_overlap')
            if custom:st.checkbox('已核对替换模板的橱窗边界',key='shop_bounds_confirm')
        window=Window(*values)
        try:window.validate()
        except ValueError as exc:error=str(exc)
        signature=hashlib.sha256(repr((template_identity,image['fingerprint'] if image else None,prompt,styles,values,tolerance,snap,overlap)).encode()).hexdigest()
        st.session_state['shop_current_signature']=signature
        if error:st.error(error)
        allowed=bool(template and image and not error and (not custom or st.session_state.get('shop_bounds_confirm')))
        if st.button('提取并合成',type='primary',width='stretch',disabled=not allowed,key='shop_generate'):
            try:
                with st.spinner('提取橱窗内容并合成…'):
                    content,merged,stats=build_example(lib.read(template),lib.read(image),window,tolerance,snap,overlap,
                        {'prompt':prompt,'style_keywords':styles,'template_asset_id':template['id'],'image_asset_id':image['id'],
                         'template_fingerprint':template['fingerprint'],'image_fingerprint':image['fingerprint']})
                st.session_state['shop_result']={'signature':signature,'content':content,'merged':merged,'stats':stats}
            except Exception as exc:st.error(f'提取合成失败：{exc}')
    with right:
        tabs=st.tabs(['模拟生成素材','提取的内容曲线','完整小店'])
        with tabs[0]:
            if image:image_viewer(lib.read(image),key='shop_source',filename=image['name'])
        result=st.session_state.get('shop_result')
        if result:
            stale=result['signature']!=signature
            if stale:st.warning('输入已修改，请重新提取并合成。')
            with tabs[1]:
                fig=_plot_curves(result['content'],show_source_image=False)
                figure_viewer(fig,key='shop_content');plt.close(fig)
            with tabs[2]:
                payload=json.dumps(result['merged'].to_dict(),ensure_ascii=False,indent=2).encode()
                svg,filename=convert_payload(payload,'理想小店_合并曲线.json')
                image_viewer(svg,key='shop_merged',filename=filename)
                stats=result['stats'];groups=stats['connectivity'].get('count')
                st.caption(f"模板 {stats['template_curves']} 条 · 橱窗 {stats['content_curves']} 条 · 贴边连接 {stats['snapped_endpoints']} 处 · 连通部分 {groups if groups is not None else '未完成分析'}")
                st.download_button('下载合并曲线 JSON',payload,'理想小店_合并曲线.json',disabled=stale)
            workspace.collect('shop')
            if st.button('进入轨迹规划',disabled=stale or not allowed):
                st.session_state['pending_navigation']='轨迹规划';st.rerun()
