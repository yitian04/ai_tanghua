"""Session workspaces: draft results, guarded actions and committed navigation."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import uuid

import streamlit as st
from src.core.assets import AssetLibrary
from src.core.drafts import Artifact,Draft,DraftStore

_CONTEXT=ContextVar('workspace',default=None)
GROUPS={'理想小店（白盒）':'shop','AI糖画线稿':'ai','图像转曲线':'vector','AI SVG 曲线':'svg','轨迹规划':'planning','文字轨迹':'text','轨迹合成':'composition','数字文件':'export','机器人控制':'robot'}
INPUTS={'shop':('shop_template','shop_example'),'svg':('svg_reference',),'ai':('stage1_reference','stage2_sample'),'vector':('vector',),'planning':('planning',),'composition':('composition_objects',),'export':('export',),'robot':('robot',)}
GENERATE={'提取并合成','生成 SVG 曲线','生成文字轨迹','生成曲线','生成三维轨迹文件','导出 CSV','导出 G-code','导出 URP','生成糖画样图','重新生成样图','从确认样图提取线稿','重新提取线稿','生成黑白线稿','重新生成线稿','使用上传图片作为线稿','恢复远程任务结果','新建任务','载入参考图并进入第二阶段'}
TRANSFERS={'进入轨迹规划','加入轨迹合成','前往数字文件导出','确认线稿并交给曲线模块','人工放行并进入曲线测试'}
HIDDEN_DEFAULTS={'设为默认值','设为URScript默认值','保存为项目默认模型'}
RESULT_KEYS={
 'shop':('shop_result','shop_ai_result'),
 'svg':('svg_result','svg_raw','svg_ack','svg_job','svg_claimed','svg_job_error'),
 'text':('text_trajectory_result','latest_trajectory_path'),
 'planning':('planning_result','latest_trajectory_path'),
 'vector':('latest_curves_path',),
 'export':('export_result',),
 'composition':('composition_saved',),
}


def state():return st.session_state.setdefault('workspace_state',{'session':uuid.uuid4().hex,'drafts':{},'workdirs':{}})
def current_group():return (_CONTEXT.get() or {}).get('group')
def root():return (_CONTEXT.get() or {}).get('root')
def draft(group=None):return state()['drafts'].get(group or current_group())
def dirty(group=None):
    value=draft(group)
    return bool(value and value.dirty)


@contextmanager
def workspace_context(root_dir,page):
    token=_CONTEXT.set({'root':str(root_dir),'group':GROUPS[page],'page':page})
    try:yield
    finally:_CONTEXT.reset(token)


def output_path(root_dir,folder,name):
    context=_CONTEXT.get()
    if not context:return None
    group=context['group'];work=state()['workdirs'].setdefault(group,uuid.uuid4().hex)
    path=Path(root_dir)/'data'/'.drafts'/state()['session']/group/work/folder/name
    path.parent.mkdir(parents=True,exist_ok=True)
    return path


def clear_result(group):
    old=state()['drafts'].pop(group,None);work=state()['workdirs'].pop(group,None)
    paths=[a.source for a in old.artifacts if a.source] if old else []
    if work:
        private=Path(state()['root'])/'data'/'.drafts'/state()['session']/group/work
        paths.extend(str(p) for p in private.rglob('*') if p.is_file() and not p.name.endswith('.remote.json'))
    DraftStore(state()['root']).discard_files(paths)
    for key in RESULT_KEYS.get(group,()):st.session_state.pop(key,None)
    if group=='composition':
        from src.pipeline.trajectory_composition.composer import Composition
        doc=st.session_state.get('composition_document')
        if doc:st.session_state['composition_document']=Composition(doc.plane)
        for key in ('composition_history','composition_selected','composition_saved','wf_composition_revision'):st.session_state.pop(key,None)
        st.session_state['composition_editor_id']=uuid.uuid4().hex
    if group=='ai':
        from src.pipeline.image_generation import SugarPaintingService
        service=SugarPaintingService(state()['root'])
        task_id=st.session_state.get('ai_sugar_task_id')
        if task_id:
            try:
                task=service.load(task_id)
                task.sample_image='';task.line_art_image='';task.sample_confirmed=False;task.line_art_confirmed=False
                service.save(task)
            except (ValueError,OSError):pass


def clear_page(group):
    clear_result(group)
    prefixes={'shop':('shop_',),'svg':('svg_',),'ai':('ai_sugar_','stage1_','stage2_','positive_prompt_','negative_prompt_','subject_instruction_','recover_bananapro_'), 'vector':('vector_',), 'planning':('planning_',), 'text':('text_trajectory_',), 'composition':('composition_',)}.get(group,())
    for key in list(st.session_state):
        if isinstance(key,str) and (key.startswith(prefixes) if prefixes else False):st.session_state.pop(key,None)
    for key in list(st.session_state):
        if key.startswith(('asset_selected_','asset_candidate_')):
            if group=='ai' or any(key.endswith('_'+name) for name in INPUTS.get(group,())):st.session_state.pop(key,None)
    for key in ('latest_image_path','latest_curves_path','latest_trajectory_path','vector_image_path','job_name','pending_navigation'):
        st.session_state.pop(key,None)
    if group=='ai':
        from src.pipeline.image_generation import SugarPaintingService
        SugarPaintingService(state()['root']).clear_active_task()
    if group=='robot':
        for key in ('storage_confirmed','execution_confirmed'):st.session_state.pop(key,None)


def publish(group=None):
    group=group or current_group();value=draft(group)
    if not value:raise ValueError('没有可保存的成果。')
    from apps.gui.asset_library import get_index
    index=get_index(state()['root'])
    with index.lock:
        result=DraftStore(state()['root']).publish(value);index.refresh()
    return result


def request_navigation(target,transfer=False):
    active=state()['active'];group=GROUPS[active]
    if target==active:return
    if st.session_state.get('wf_running'):return
    intent={'kind':'transfer' if transfer else 'navigate','target':target,'source':group}
    if dirty(group):state()['intent']=intent
    else:commit_navigation(intent)


def commit_navigation(intent):
    group=intent['source'];target=intent['target'];assets=[]
    if intent['kind']=='transfer':
        value=draft(group)
        if not value or not value.published:raise ValueError('请先保存至素材库。')
        kind={'图像转曲线':'image','轨迹规划':'curve','轨迹合成':'trajectory','数字文件':'trajectory','机器人控制':'trajectory'}.get(target)
        assets=[a for a in value.published if a['kind']==kind]
        if not assets:raise ValueError('没有适用于目标模块的已保存素材。')
        for asset in assets:AssetLibrary(state()['root']).read(asset)
    clear_page(group)
    state()['active']=target;state().pop('intent',None)
    # enter() synchronizes the radio before it is rendered on the next run.
    if assets:state()['handoff']={'target':target,'assets':assets}


def enter(root_dir,pages):
    s=state();s['root']=str(root_dir)
    if 'active' not in s:
        s['active']=st.session_state.get('main_navigation','AI糖画线稿')
        if s['active'] not in pages:s['active']='AI糖画线稿'
        # Clear legacy cached results, not user assets or settings.
        for key in ('text_trajectory_result','latest_image_path','latest_curves_path','latest_trajectory_path','vector_image_path','composition_document','ai_sugar_task_id'):st.session_state.pop(key,None)
    pending=st.session_state.pop('pending_navigation',None)
    if pending in pages:request_navigation(pending,transfer=True)
    handoff=s.pop('handoff',None)
    if handoff and handoff['target']==s['active']:
        try:
            asset=handoff['assets'][-1];lib=AssetLibrary(root_dir);lib.read(asset);path=str(lib.path(asset['id']))
            key={'图像转曲线':'latest_image_path','轨迹规划':'latest_curves_path','轨迹合成':'composition_pending_path','数字文件':'latest_trajectory_path','机器人控制':'latest_trajectory_path'}[s['active']]
            st.session_state[key]=path
        except (ValueError,OSError):st.session_state['wf_notice']='素材已删除或移动，请重新导入。'
    value=s['drafts'].get(GROUPS[s['active']])
    if value and value.published:
        try:
            for asset in value.published:AssetLibrary(root_dir).read(asset)
        except (ValueError,OSError):clear_result(GROUPS[s['active']]);st.session_state['wf_notice']='成果已从素材库删除或移动，已清除失效引用。'
    st.session_state['main_navigation']=s['active']
    return s['active']


def navigation_changed():
    collect(GROUPS[state()['active']])
    target=st.session_state.get('main_navigation');active=state()['active']
    st.session_state['main_navigation']=active;request_navigation(target)


def action_button(target,label,*args,**kwargs):
    if label in HIDDEN_DEFAULTS or ('项目默认' in label and '模型' in label):return False
    context=_CONTEXT.get()
    if not context:return target(label,*args,**kwargs)
    group=context['group'];canonical={'生成糖画样图':'sample_generate','重新生成样图':'sample_generate','从确认样图提取线稿':'lineart_generate','重新提取线稿':'lineart_generate','生成黑白线稿':'direct_generate','重新生成线稿':'direct_generate'}
    token=str(kwargs.get('key') or canonical.get(label,label))
    running=st.session_state.get('wf_running',False)
    if running:kwargs['disabled']=True
    clicked=target(label,*args,**kwargs)
    resume=state().get('resume')
    if resume and resume['source']==group and resume['token']==token:
        state().pop('resume',None);st.session_state['wf_executing']=True
        return True
    guarded=label in GENERATE or label in TRANSFERS or str(label).startswith('恢复此结果')
    if not clicked or not guarded:return clicked
    intent={'kind':'continue' if label in TRANSFERS else 'generate','token':token,'source':group,'label':label}
    replacing=True
    if group=='ai' and label in {'从确认样图提取线稿','使用上传图片作为线稿'}:replacing=False
    if dirty(group) and replacing:state()['intent']=intent;return False
    prepare_generation(intent)
    state()['resume']=intent
    st.session_state['wf_running']=True
    st.rerun()


def prepare_generation(intent):
    if intent['kind']!='generate':return
    group=intent['source']
    if group!='ai':clear_result(group);return
    from src.pipeline.image_generation import SugarPaintingService
    service=SugarPaintingService(state()['root']);task_id=st.session_state.get('ai_sugar_task_id')
    if task_id:
        task=service.load(task_id)
        if intent.get('token')=='sample_generate' or intent.get('label')=='新建任务':task.sample_image='';task.sample_confirmed=False
        if intent.get('label')!='新建任务':task.line_art_image='';task.line_art_confirmed=False
        service.save(task)
    state()['drafts'].pop(group,None)


def collect(group):
    s=state();root_dir=s['root'];store=DraftStore(root_dir)
    if group=='composition':
        from src.pipeline.trajectory_composition.composer import compose,out_of_bounds
        doc=st.session_state.get('composition_document')
        if not doc or not doc.items:return
        payload=json.dumps(doc.to_dict(),ensure_ascii=False,indent=2).encode();revision=hashlib.sha256(payload).hexdigest()
        if draft(group) and draft(group).revision==revision:return
        name=st.session_state.get('composition_output_name') or '糖画组合'
        from apps.gui.views.file_naming import sanitize_filename
        name=sanitize_filename(name)
        bad=any(out_of_bounds(item,doc.plane) for item in doc.items)
        artifacts=[]
        if not bad:artifacts.insert(0,Artifact(name+'_trajectory.json',json.dumps(compose(doc).to_dict(),ensure_ascii=False,indent=2).encode(),'compositions'))
        s['drafts'][group]=Draft(artifacts,revision,not bad,'超出画布，请调整后再保存。' if bad else '')
        return
    if group=='shop':
        image=st.session_state.get('shop_ai_result')
        if st.session_state.get('shop_creation_state',{}).get('mode')=='ai' and image and Path(image['path']).is_file():
            payload=Path(image['path']).read_bytes();revision=hashlib.sha256(payload).hexdigest()
            if not draft(group) or draft(group).revision!=revision:
                s['drafts'][group]=Draft([Artifact('小店参考_'+image['style']+'.png',payload,'images',image['path'])],revision)
            return
        result=st.session_state.get('shop_result')
        if not result:return
        payload=json.dumps(result['merged'].to_dict(),ensure_ascii=False,indent=2).encode()
        revision=hashlib.sha256(payload).hexdigest()
        if not draft(group) or draft(group).revision!=revision:
            s['drafts'][group]=Draft([Artifact('理想小店_合并曲线.json',payload,'curves')],revision)
            if result.get('content') and result['content'].metadata.get('source')=='freehand':
                raw=json.dumps(result['content'].to_dict(),ensure_ascii=False,indent=2).encode()
                s['drafts'][group].artifacts.append(Artifact('理想小店_手绘原稿.json',raw,'curves'))
        value=draft(group)
        value.valid=result['signature']==st.session_state.get('shop_current_signature')
        value.error='' if value.valid else '输入已修改，请重新提取并合成。'
        return
    if group=='svg':
        result=st.session_state.get('svg_result')
        if not result:return
        payload=json.dumps(result['curves'].to_dict(),ensure_ascii=False).encode()
        revision=hashlib.sha256(result['svg'].encode()+payload).hexdigest()
        if not draft(group) or draft(group).revision!=revision:
            s['drafts'][group]=Draft([Artifact('generated_curves.json',payload,'curves')],revision)
        value=draft(group)
        value.valid=result['connectivity']['count']<=1 or bool(st.session_state.get('svg_ack'))
        value.error='' if value.valid else '图案含分离部分，请在预览中明确确认后继续。'
        return
    paths=[]
    if group=='text'  and st.session_state.get('text_trajectory_result'):
        path=Path(st.session_state['text_trajectory_result'][1]);paths=[path.with_name(path.stem.replace('_trajectory','_curves')+'.json'),path]
    elif group in {'vector','planning','export'}:
        folder={'vector':'curves','planning':'trajectories','export':'exports'}[group]
        work=s['workdirs'].get(group)
        if work:
            paths=list((Path(root_dir)/'data'/'.drafts'/s['session']/group/work/folder).glob('*'))
            if group=='vector':paths=[p for p in paths if p.suffix.lower()=='.json']
    elif group=='ai':
        from src.pipeline.image_generation import SugarPaintingService
        task_id=st.session_state.get('ai_sugar_task_id')
        if task_id:
            task=SugarPaintingService(root_dir).load(task_id)
            SugarPaintingService(root_dir).archive_remote_records(task_id)
            paths=[Path(p) for p in (task.sample_image,task.line_art_image) if p and Path(p).is_file()]
    if not paths:return
    try:new=store.from_paths(paths)
    except (ValueError,OSError):return
    if not draft(group) or draft(group).revision!=new.revision:s['drafts'][group]=new


def after_render():
    group=current_group()
    if group:collect(group)
    if st.session_state.pop('wf_executing',False):
        if group=='svg' and st.session_state.get('svg_job'):
            from src.pipeline.svg_generation.jobs import snapshot
            st.session_state['wf_running']=snapshot(st.session_state['svg_job'])['phase'] not in {'completed','failed','unknown'}
        else:st.session_state['wf_running']=False
        message=st.session_state.pop('wf_error',None)
        if message:st.session_state['wf_notice']=message
        return True
    return False


def render_controls(inline=False):
    value=draft();busy=bool(st.session_state.get('wf_running'))
    st.html('''<style>.st-key-workspace_actions{position:fixed!important;bottom:14px;right:24px;z-index:30;width:auto!important;max-width:calc(100vw - 32px);background:#fff;border:1px solid #cbd5e1;border-radius:7px;padding:8px 12px;box-shadow:0 2px 8px #0001}.block-container{padding-bottom:90px!important}</style>''')
    if value and (current_group()!='svg' or inline):
        with st.container(key='workspace_actions',horizontal=True,vertical_alignment='center',gap='small'):
            st.caption(('未保存' if value.dirty else '已保存')+f' · {len(value.artifacts)} 个文件')
            if st.button('保存至素材库',type='primary',disabled=busy or not value.valid or not value.dirty):
                try:
                    if current_group()=='svg':state()['intent']={'kind':'svg_save','source':'svg'};st.rerun()
                    publish();st.rerun()
                except Exception as exc:st.error(f'保存失败：{exc}')
            if st.button('放弃',disabled=busy):state()['intent']={'kind':'discard','source':current_group()}
        if not value.valid:st.warning(value.error)
    unsaved=bool(value and value.dirty) or busy
    st.html(f'''<script>(()=>{{const key='__workspaceUnload';if(window[key])window.removeEventListener('beforeunload',window[key]);window[key]=null;if({str(unsaved).lower()}){{window[key]=e=>{{e.preventDefault();e.returnValue=true;}};window.addEventListener('beforeunload',window[key]);}}}})();</script>''',unsafe_allow_javascript=True)


def show_confirmation():
    if not state().get('intent'):return False
    _confirmation();return True


@st.dialog('当前成果尚未保存',width='small',dismissible=False)
def _confirmation():
    intent=state().get('intent')
    if not intent:return
    group=intent['source'];value=draft(group);kind=intent['kind']
    st.write('放弃只清理当前工作区，不会删除已入库素材。' if kind=='discard' else '请先处理当前成果，再继续操作。')
    if value:
        for artifact in value.artifacts:st.caption(artifact.name)
    def complete(save=False):
        try:
            if save:publish(group)
            if kind in {'navigate','transfer'}:commit_navigation(intent)
            elif kind in {'generate','continue'}:
                if kind=='generate':prepare_generation(intent)
                state()['resume']=intent;st.session_state['wf_running']=True
            else:clear_result(group)
            state().pop('intent',None);st.rerun()
        except (ValueError,OSError) as exc:st.error(f'操作未完成：{exc}')
    if kind=='svg_save':
        if st.button('确认保存曲线 JSON',type='primary',disabled=bool(value and not value.valid)):
            try:publish(group);state().pop('intent',None);st.rerun()
            except Exception as exc:st.error(str(exc))
        if st.button('取消'):state().pop('intent',None);st.rerun()
        return
    if kind!='discard':
        label={'navigate':'保存并离开','transfer':'保存并继续','generate':'保存后继续','continue':'保存并继续'}[kind]
        if st.button(label,type='primary',disabled=bool(value and not value.valid)):complete(True)
    if kind not in {'transfer','continue'}:
        if st.button('确认放弃' if kind=='discard' else '放弃后继续' if kind=='generate' else '放弃并离开'):complete(False)
    if st.button('取消'):
        state().pop('intent',None);st.rerun()
