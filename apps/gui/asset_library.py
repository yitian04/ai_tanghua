"""One dialog router for global management and all typed file inputs."""
from __future__ import annotations
import hashlib
import io
import json
import uuid
from pathlib import Path
from datetime import datetime

import streamlit as st
from src.core.assets import AssetLibrary, classify, category

LABELS={'image':'图像','curve':'曲线 JSON','svg':'曲线 SVG','trajectory':'轨迹','gcode':'G-code','program':'执行文件'}
ICONS={'image':':material/image:','curve':':material/polyline:','svg':':material/polyline:','trajectory':':material/route:','gcode':':material/code:','program':':material/code:'}


@st.cache_data(show_spinner=False,max_entries=256)
def thumbnail(payload, name, kind):
    from src.core.asset_previews import render_preview
    return render_preview(payload,name,kind)

def preview(payload,name,kind,key=None):
    try:
        if kind=='image':
            from PIL import Image
            with Image.open(io.BytesIO(payload)) as im: st.caption(f'尺寸：{im.width} × {im.height} 像素')
        elif kind=='curve':
            data=json.loads(payload)
            st.caption(f"{len(data['curves'])} 条曲线 · 坐标：{data.get('coordinate_frame','image_px')}")
        elif kind=='trajectory':
            from src.pipeline.trajectory_composition.composer import import_trajectory
            t=import_trajectory(payload,name)
            speeds=[p.speed_mm_s for p in t.points if p.drawing]
            st.caption(f'{len(t.points)} 个轨迹点 · 单位 mm · 绘制速度 {min(speeds):g}–{max(speeds):g} mm/s')
            from apps.gui.trajectory_player import render_trajectory_player
            render_trajectory_player(t,key or 'asset_'+hashlib.sha256(payload).hexdigest()[:16])
            return
        image=thumbnail(payload,name,kind)
        if image: st.image(image,width='stretch')
        else:
            st.markdown(f"**{LABELS.get(kind,'历史文件')}**")
            st.code(payload.decode('utf-8-sig',errors='replace')[:1800],language='text')
            st.caption('此格式仅展示内容摘要，不将其作为可靠的几何预览。')
    except Exception as exc: st.warning(f'预览不可用：{exc}')


def request(root, **kwargs):
    st.session_state['asset_dialog']={'root':str(root),'step':'browse','selected':[],'nonce':uuid.uuid4().hex,**kwargs}
    # The click already reruns the app. show_pending() opens this request at
    # the end of the same pass; a second rerun only delays the first frame.


def file_input(root,key,label,kinds,multiple=False,candidate=None,allowed=None,on_import=None):
    with st.container(key=f"asset_input_{key}", gap="small"):
        st.markdown(f'**{label}**')
        actions=st.container(horizontal=True, gap="small", vertical_alignment="center")
        if actions.button('本地上传',key=f'asset_upload_{key}',width='content'):
            request(root,target=key,kinds=list(kinds),multiple=multiple,step='upload',allowed=allowed,on_import=on_import)
        if actions.button('从素材库选择',key=f'asset_browse_{key}',width='content'):
            request(root,target=key,kinds=list(kinds),multiple=multiple,allowed=allowed,on_import=on_import)
        statekey=f'asset_selected_{key}'
        paths=[] if on_import else st.session_state.get(statekey,[])
        lib=AssetLibrary(root)
        existing=[]
        for p in paths:
            try:
                asset=lib.inspect(Path(p).resolve().relative_to(lib.root))
                if asset['kind'] in kinds and (allowed is None or p in allowed): existing.append(p)
            except (ValueError,OSError,KeyError,TypeError): pass
        if len(existing)!=len(paths):
            st.session_state[statekey]=existing;st.warning('所选文件已删除或移动，请重新导入。')
        if candidate and str(candidate) not in existing:
            try:
                lib=AssetLibrary(root);relative=Path(candidate).resolve().relative_to(lib.root)
                item=lib.inspect(relative)
                if item['kind'] in kinds and (allowed is None or str(lib.path(item['id'])) in allowed):
                    if st.button('添加上一步轨迹' if on_import else '预览并确认上一步成果',key=f'asset_candidate_{key}'):
                        if on_import:
                            on_import([item],lib);st.rerun()
                        else:
                            request(root,target=key,kinds=list(kinds),multiple=multiple,step='confirm',selected=[item],allowed=allowed)
            except (ValueError,OSError): pass
        for path in existing: st.caption(f'已确认：{Path(path).name}')
        return existing if multiple else (existing[0] if existing else '')


class SelectedUpload:
    def __init__(self,path): self.path=Path(path);self.name=self.path.name
    def getvalue(self): return self.path.read_bytes()


def image_input(root,key,label,allowed=None):
    path=file_input(root,key,label,{'image'},allowed=allowed)
    return SelectedUpload(path) if path else None


# The browser uses persistent incremental indexing; retain scan for older callers.
@st.cache_data(ttl=3,show_spinner=False)
def scan(root,refresh): return AssetLibrary(root).scan()


@st.cache_resource
def get_index(root):
    from src.core.asset_index import AssetIndex
    return AssetIndex(root)


def show_pending():
    if 'asset_dialog' in st.session_state: _dialog()


def _dismiss():
    q=st.session_state.pop('asset_dialog',None)
    if q: get_index(q['root']).release(q['nonce'])


@st.cache_resource
def grid_component(js):
    import streamlit.components.v2 as components
    version=hashlib.sha256(js.encode()).hexdigest()[:12]
    return components.component('asset_grid_'+version,js=js)


def _selected(q):
    return q.setdefault('manager_selection' if not q.get('target') else 'import_selection',{})


def _operate(q,action,items):
    from src.core.asset_index import batch_operation
    index=get_index(q['root'])
    with index.lock:
        succeeded,failed=batch_operation(index.lib,action,items)
        index.refresh()
    chosen=_selected(q)
    for identity in succeeded: chosen.pop(identity,None)
    q['notice']=f"成功 {len(succeeded)} 项"+(f"，失败 {len(failed)} 项" if failed else '')
    q['errors']=failed
    q['step']='browse'


def _ask_purge(q,items):
    if items: q['confirmation']={'token':uuid.uuid4().hex,'items':[dict(i) for i in items]}


def _use_items(q,lib,items):
    if not items: raise ValueError('请先选择素材。')
    for item in items:
        if item['kind'] not in q['kinds']: raise ValueError('素材不适用于当前输入。')
        if q.get('allowed') is not None and str(lib.path(item['id'])) not in q['allowed']:
            raise ValueError('素材不适用于当前输入。')
        lib.read(item)
    if q.get('on_import'):
        q['on_import'](items,lib)
    else:
        st.session_state[f"asset_selected_{q['target']}"]=[str(lib.path(i['id'])) for i in items]
    q['completed']=True


def _open_local_folder(lib, *, item=None, trash=False):
    try:
        if item: lib.reveal(item)
        else: lib.open_folder(trash=trash)
        st.toast('已在本机文件夹中显示。' if item else '已打开本机素材文件夹。')
    except Exception as exc:
        st.warning(f'无法打开本机文件夹：{exc}')


def _on_grid_event():
    q=st.session_state.get('asset_dialog')
    if not q: return
    event=st.session_state.get('asset_grid',{}).get('event')
    if not event or event.get('token') in q.setdefault('processed',[]): return
    q['processed'].append(event['token']);q['processed']=q['processed'][-128:];q['ack']=event['token']
    for key in event.get('received_images',[]): q.setdefault('sent_images',{})[key]=True
    action=event.get('action');item=q.get('records',{}).get(event.get('id'))
    try:
        if action in {'select','preview','recycle','restore','ask_purge'} and event.get('id'):
            # The grid can still show a verified tile while another session
            # refreshes its index. Resolve the source rather than losing clicks.
            if item is None:
                lib=get_index(q['root']).lib
                if str(event['id']).startswith('data/'):
                    item=lib.inspect(event['id'])
                else:
                    item=next((i for i in lib.trash_items() if i['trash_id']==event['id']),None)
            if item and event.get('expected') and tuple(map(str,item['fingerprint']))!=tuple(map(str,event['expected'])):
                raise ValueError('素材已变化，请刷新后重新选择。')
            if item and q.get('target') and (item['kind'] not in q['kinds'] or (q.get('allowed') is not None and str(get_index(q['root']).lib.path(item['id'])) not in q['allowed'])):
                raise ValueError('素材不适用于当前输入。')
        if action=='page': q['page']=max(1,int(event['page']))
        elif action=='select' and item and (q.get('multi') or q.get('multiple')):
            if event['checked']: _selected(q)[event['id']]=dict(item)
            else: _selected(q).pop(event['id'],None)
        elif action=='preview' and item and not q.get('multi'):
            q['selected']=[dict(item)];q['step']='detail';q['preview_nonce']=uuid.uuid4().hex
        elif action=='use_selected' and q.get('target'):
            if q.get('on_import'): _use_items(q,get_index(q['root']).lib,list(_selected(q).values()))
            else: q['selected']=list(_selected(q).values());q['step']='confirm';q['preview_nonce']=uuid.uuid4().hex
        elif action=='recycle_selected' and not q.get('target') and q.get('multi') and q.get('view')=='library':
            _operate(q,'recycle',list(_selected(q).values()))
        elif action=='purge_selected' and not q.get('target') and q.get('multi') and q.get('view')=='trash':
            _ask_purge(q,list(_selected(q).values()))
        elif action=='recycle' and item and not q.get('target'): _operate(q,'recycle',[item])
        elif action=='restore' and item and not q.get('target'): _operate(q,'restore',[item])
        elif action=='ask_purge' and item and not q.get('target'): _ask_purge(q,[item])
        elif action=='cancel_purge': q.pop('confirmation',None)
        elif action=='confirm_purge' and not q.get('target'):
            confirmation=q.get('confirmation')
            if confirmation and confirmation['token']==event.get('confirmation'):
                q.pop('confirmation',None);_operate(q,'purge',confirmation['items'])
    except Exception as exc: q['notice']=str(exc)


ASSET_CSS="""
<style>
[role="dialog"]:has(.st-key-asset_shell){max-height:calc(100dvh - 24px);overflow:hidden}
.st-key-asset_shell{--asset-height:min(700px,calc(100dvh - 148px));height:var(--asset-height)!important;min-height:220px;overflow:hidden}
.st-key-asset_shell [data-testid="stHorizontalBlock"]:has(.st-key-asset_left){flex-wrap:nowrap!important;align-items:stretch;gap:12px!important}
.st-key-asset_shell [data-testid="stColumn"]:has(.st-key-asset_left){flex:0 0 164px!important;width:164px!important;min-width:0!important}
.st-key-asset_shell [data-testid="stColumn"]:has(.st-key-asset_right){flex:1 1 0!important;width:0!important;min-width:0!important}
.st-key-asset_left,.st-key-asset_right{height:var(--asset-height)!important;min-height:0;overflow:hidden}
.st-key-asset_left{overflow-y:auto;overscroll-behavior:contain;padding-right:4px}
.st-key-asset_left button{min-height:30px!important;padding:4px 6px!important}
.st-key-asset_left input{min-height:30px!important}
.st-key-asset_left [data-testid="stMarkdownContainer"]{overflow-wrap:anywhere}
.st-key-asset_detail{height:var(--asset-height)!important;min-height:0;overflow:auto;overscroll-behavior:contain;padding-right:6px}
.st-key-asset_shell,.st-key-asset_left,.st-key-asset_right,.st-key-asset_detail{flex:0 0 var(--asset-height)!important}
.st-key-asset_detail_actions{position:sticky;bottom:0;background:var(--background-color,#fff);padding:8px 0;z-index:2}
.st-key-asset_upload_footer{margin-top:auto!important;position:sticky;bottom:0;background:var(--background-color,#fff);padding:8px 0;z-index:2;flex-shrink:0}
.st-key-asset_detail > [data-testid="stLayoutWrapper"]:has(.st-key-asset_upload_footer){margin-top:auto!important;position:sticky;bottom:0;z-index:2;flex:0 0 auto}
@media(max-width:720px){.st-key-asset_shell [data-testid="stColumn"]:has(.st-key-asset_left){flex-basis:128px!important;width:128px!important}}
@media(max-width:420px){.st-key-asset_shell [data-testid="stColumn"]:has(.st-key-asset_left){flex-basis:112px!important;width:112px!important}.st-key-asset_shell [data-testid="stHorizontalBlock"]:has(.st-key-asset_left){gap:8px!important}}
</style>
"""

TRASH_CSS="""<style>
[role="dialog"]:has(.st-key-asset_shell){background:#f3f4f6}
.st-key-asset_left button,.st-key-asset_detail button{background:#e5e7eb;border-color:#cbd0d7;color:#18212b}
.st-key-asset_left button:hover,.st-key-asset_detail button:hover{background:#dce0e5}
.st-key-asset_return_library button,.st-key-asset_return_library button:hover{background:#fff!important}
.st-key-asset_detail_actions{background:#f3f4f6}
</style>"""

LIBRARY_CSS="""<style>
[role="dialog"]:has(.st-key-asset_shell){background:#fff}
.st-key-asset_left button,.st-key-asset_detail button[kind="secondary"]{background:#fff;border-color:#cbd5e1;color:#18212b}
.st-key-asset_left button:hover,.st-key-asset_detail button[kind="secondary"]:hover{background:#f3f4f6}
.st-key-asset_detail_actions{background:#fff}
</style>"""


@st.dialog('素材库',width='large',on_dismiss=_dismiss)
def _dialog():
    q=st.session_state.get('asset_dialog')
    if not q: return
    if q.get('completed'):
        _dismiss();st.rerun()
    q.setdefault('nonce',uuid.uuid4().hex);q.setdefault('view','library');q.setdefault('page',1)
    q.setdefault('multi',False);q.setdefault('import_selection',{});q.setdefault('manager_selection',{})
    idx=get_index(q['root']);lib=idx.lib
    if not q.get('indexed'):
        idx.refresh();q['indexed']=True
    entries,pending=idx.snapshot()
    trash=lib.trash_items() if not q.get('target') else []
    pool=trash if q['view']=='trash' else entries
    q['records']={i.get('trash_id',i['id']):i for i in pool}
    st.html(ASSET_CSS+(TRASH_CSS if q['view']=='trash' else LIBRARY_CSS))
    def go(step):
        q['step']=step;q.pop('confirmation',None);q.pop('speed_confirm',None)
        if step!='browse': q['preview_nonce']=uuid.uuid4().hex
        st.rerun(scope='fragment')
    def close(): _dismiss();st.rerun()
    with st.container(key='asset_shell',gap='small'):
        left,right=st.columns([1,5],gap='small')
        with left:
            with st.container(key='asset_left',gap='small'):
                target=q.get('target');manage=not target
                detail_left=st.container(gap='small')
                if q['step'] in {'browse','upload'}:
                    target=q.get('target');manage=not target
                    st.markdown('**回收站**' if q['view']=='trash' else ('**选择素材**' if target else '**素材管理**'))
                    if q['step']!='browse' and st.button('返回素材',width='stretch'):
                        go('browse')
                    # Hidden widgets are cleaned up by Streamlit; retain list filters
                    # in dialog state while the detail view is mounted.
                    previous=q.get('filter')
                    if previous:
                        for prefix,value in zip(('asset_category_','asset_search_','asset_sort_'),previous[1:]):
                            key=prefix+q['nonce']
                            if key not in st.session_state: st.session_state[key]=value
                    cat=st.radio('分类',['全部','图像','曲线','轨迹','执行文件（URP）','SVG'],horizontal=True,key='asset_category_'+q['nonce'])
                    search=st.text_input('搜索名称',placeholder='搜索',key='asset_search_'+q['nonce'])
                    order=st.selectbox('排序',['最新优先','名称排序'],label_visibility='collapsed',key='asset_sort_'+q['nonce'])
                    signature=(q['view'],cat,search,order)
                    if q.get('filter')!=signature: q['page']=1;q['filter']=signature
                    tools=st.container(horizontal=True,gap='small')
                    if tools.button('刷新',width='content'):
                        idx.refresh();q['sent_images']={};st.rerun(scope='fragment')
                    if manage:
                        if st.button('打开本地文件夹',icon=':material/folder_open:',width='stretch',help='打开本机 data 素材目录；回收站视图打开回收站目录。'):
                            _open_local_folder(lib,trash=q['view']=='trash')
                        if q['view']=='library':
                            if tools.button('上传素材',width='content'): go('upload')
                            if st.button(f'回收站 ({len(trash)})',width='stretch'):
                                q.update(view='trash',multi=False,page=1,manager_selection={});go('browse')
                        else:
                            with st.container(key='asset_return_library',gap='small'):
                                if st.button('返回素材库',width='stretch'):
                                    q.update(view='library',multi=False,page=1,manager_selection={});go('browse')
                            if st.button('清空回收站',disabled=not trash,width='stretch'): _ask_purge(q,trash)
                        if st.button('退出多选' if q['multi'] else '多选',width='stretch'):
                            q['multi']=not q['multi'];q['manager_selection']={};st.rerun(scope='fragment')
                    chosen=_selected(q)
                    if q['step']=='browse' and (q['multi'] or (target and q.get('multiple'))):
                        st.caption(f'已选 {len(chosen)} 项（跨页保留）')
                        selection_tools=st.container(horizontal=True,gap='small')
                        if selection_tools.button('全选本页',width='content'):
                            for identity in q.get('visible',[]):
                                if identity in q['records']: chosen[identity]=dict(q['records'][identity])
                            st.rerun(scope='fragment')
                        if selection_tools.button('清空选择',width='content'): chosen.clear();st.rerun(scope='fragment')
                    if q.get('notice'): st.caption(q['notice'])
        with right:
            with st.container(key='asset_right',gap='small'):
                try:
                    if q['step'] in {'browse'}:
                        filtered=[i for i in pool if (not target or i['kind'] in q['kinds']) and (cat=='全部' or i['category']==cat) and search.casefold() in i['name'].casefold() and (q.get('allowed') is None or str(lib.path(i['id'])) in q['allowed'])]
                        if order=='名称排序': filtered.sort(key=lambda i:i['name'].casefold())
                        else: filtered.sort(key=lambda i:i.get('deleted_at',i['mtime']),reverse=True)
                        pages=max(1,(len(filtered)+23)//24);q['page']=min(q['page'],pages)
                        visible=filtered[(q['page']-1)*24:q['page']*24]
                        q['visible']=[i.get('trash_id',i['id']) for i in visible]
                        previews=idx.previews(q['nonce'],visible)
                        images={};cards=[];sent=q.setdefault('sent_images',{})
                        for item in visible:
                            key=idx.thumb_key(item);status,uri=previews[key]
                            if uri and key not in sent: images[key]=uri
                            # Nanosecond timestamps exceed JavaScript's integer
                            # precision. Transport identity fields losslessly.
                            cards.append({**{k:item[k] for k in ('name','kind')},'fingerprint':list(map(str,item['fingerprint'])),'identity':item.get('trash_id',item['id']),'thumb_key':key,'thumb_state':status,'label':LABELS.get(item['kind'],'历史文件')+' · '+Path(item['name']).suffix.lstrip('.').upper()})
                        busy=pending>0 or any(s=='loading' for s,_ in previews.values())
                        batch_action=None
                        if target and q.get('multiple'):
                            batch_action={'name':'use_selected','label':'导入轨迹' if q.get('on_import') else '预览并确认已选'}
                        elif manage and q['multi']:
                            batch_action={'name':'purge_selected' if q['view']=='trash' else 'recycle_selected','label':'永久删除' if q['view']=='trash' else '放入回收站'}
                        data=dict(owner=q['nonce'],ack=q.get('ack'),items=cards,images=images,view=q['view'],filter=str(signature),page=q['page'],pages=pages,total=len(filtered),pending=pending,selected=list(chosen),multi=q['multi'],import_multi=bool(target and q.get('multiple')),direct_import=bool(q.get('on_import')),manage=manage,confirm=q.get('confirmation'),busy=busy,notice=q.get('notice',''),errors=q.get('errors',[]),batch_action=batch_action)
                        js=(Path(__file__).parent/'components'/'asset_grid.js').read_text(encoding='utf-8')
                        grid_component(js)(key='asset_grid',data=data,on_event_change=_on_grid_event,height='content')
                    else:
                        idx.release(q['nonce'])
                        with st.container(key='asset_detail',gap='small'):
                            _detail(q,lib,idx,close,go,detail_left)
                except Exception as exc:
                    st.error(str(exc))
                    if st.button('返回素材列表'): go('browse')


def _detail(q,lib,idx,close,go,left):
    target=q.get('target');step=q['step']
    if step=='upload':
        files=st.file_uploader('选择本地文件',accept_multiple_files=True,key='asset_files_'+q['nonce'])
        if q.get('on_import'):
            st.caption('可多选标准轨迹 JSON / CSV，导入后直接加入对象列表。')
            if files: st.caption(f'待导入 {len(files)} 个文件：'+ '、'.join(file.name for file in files))
            with st.container(key='asset_upload_footer',horizontal=True,horizontal_alignment='right',gap='small'):
                if st.button('导入轨迹',disabled=not files,type='primary'):
                    for file in files:
                        if classify(file.getvalue(),file.name) not in q['kinds']: raise ValueError(f'{file.name} 不适用于当前输入。')
                    items=[lib.import_file(file.getvalue(),file.name) for file in files]
                    _use_items(q,lib,items);idx.refresh();scan.clear();close()
            return
        st.caption('预览确认后才归档；取消不会保存上传文件。')
        if st.button('预览上传文件',disabled=not files):
            staged=[]
            for file in files:
                payload=file.getvalue();kind=classify(payload,file.name)
                if target and kind not in q['kinds']: raise ValueError(f'{file.name} 不适用于当前输入。')
                item=dict(name=file.name,kind=kind,payload=payload)
                if q.get('allowed') is not None:
                    match=next((p for p in q['allowed'] if Path(p).is_file() and Path(p).read_bytes()==payload),None)
                    if not match: raise ValueError('此入口只接受已批准的样本。')
                    item['approved_path']=match
                staged.append(item)
            if target and not q.get('multiple') and len(staged)!=1: raise ValueError('一次请选择一个文件。')
            q['staged']=staged;go('confirm_upload')
        return
    staged=step=='confirm_upload';items=q.get('staged',[]) if staged else q.get('selected',[])
    if not items:
        with left:
            if st.button('返回'): go('browse')
        return
    with left:
        st.markdown('**素材预览**')
        number=st.selectbox('当前文件',range(len(items)),format_func=lambda n:items[n]['name'],key='asset_detail_file_'+q.get('preview_nonce',q['nonce'])) if len(items)>1 else 0
    item=items[number]
    payload=item['payload'] if staged else (lib.trash_path(item['trash_id'])/'payload').read_bytes() if item.get('trash_id') else lib.path(item['id']).read_bytes()
    st.markdown('**'+item['name']+'** · '+LABELS.get(item['kind'],'历史文件'))
    st.caption(f"{len(payload):,} 字节" + (' · '+item['id'] if 'id' in item else ''))
    if item.get('mtime'): st.caption('修改时间：'+datetime.fromtimestamp(item['mtime']).strftime('%Y-%m-%d %H:%M:%S'))
    with left:
        if not staged and st.button('在文件夹中显示',icon=':material/folder_open:',key=f"asset_reveal_{q['nonce']}_{number}",disabled=staged,help='打开本机文件夹并选中该文件。上传文件需先确认导入。'):
            _open_local_folder(lib,item=item)
        if item['kind']=='trajectory' and not staged and not target and not item.get('trash_id'):
            from src.core.trajectory_speed import edit_payload
            from src.pipeline.trajectory_composition.composer import import_trajectory
            trajectory=import_trajectory(payload,item['name'])
            st.caption('名义时间不包含机器人侧等待、速度上限、加减速和本机倍率。')
            with st.expander('速度设置',expanded=True):
                edits={}
                for drawing,label in ((True,'绘制速度'),(False,'空移速度')):
                    speeds=[p.speed_mm_s for p in trajectory.points if p.drawing==drawing]
                    if not speeds: continue
                    st.caption(f'{label}：{min(speeds):g}–{max(speeds):g} mm/s')
                    field=f"speed_{q.get('preview_nonce',q['nonce'])}_{number}_{drawing}"
                    enabled=st.checkbox('统一'+label,key=field+'_enabled')
                    value=st.number_input(label+' mm/s',min_value=0.000001,value=float(speeds[0]),format='%.6f',key=field,disabled=not enabled)
                    if enabled: edits['drawing' if drawing else 'travel']=value
                edited=edit_payload(payload,item['name'],**edits) if edits else payload
                if st.button('保存修改',disabled=not edits,key=f'save_speed_{number}'):
                    q['speed_confirm']=dict(item=item,payload=edited)
                confirm=q.get('speed_confirm')
                if confirm and confirm['item']['id']==item['id']:
                    st.warning('确认覆盖原轨迹？坐标和笔顺保持不变。')
                    yes,no=st.columns(2)
                    if yes.button('确认覆盖',key=f'confirm_speed_{number}'):
                        updated=lib.replace_trajectory(confirm['item'],confirm['payload'])
                        q['selected']=[updated];q.pop('speed_confirm',None);idx.refresh();scan.clear()
                        q['preview_nonce']=uuid.uuid4().hex;st.rerun(scope='fragment')
                    if no.button('取消修改',key=f'cancel_speed_{number}'):
                        q.pop('speed_confirm',None);st.rerun(scope='fragment')
                payload=edited
    preview(payload,item['name'],item['kind'],key=f"asset_{q.get('preview_nonce',q['nonce'])}_{number}")
    with left:
        if staged or step=='confirm' or target:
            if st.button('导入轨迹' if q.get('on_import') else '导入并使用' if target else '确认导入素材库',type='primary'):
                if staged:
                    items=[lib.inspect(Path(i['approved_path']).resolve().relative_to(lib.root)) if i.get('approved_path') else lib.import_file(i['payload'],i['name']) for i in items]
                else:
                    for item in items:
                        if tuple(lib.inspect(item['id'])['fingerprint'])!=tuple(item['fingerprint']): raise ValueError('文件已变化，请重新选择。')
                if target: _use_items(q,lib,items)
                idx.refresh();scan.clear();close()
        elif items:
            st.download_button('下载文件',payload,item['name'])
            if item.get('trash_id'):
                if st.button('恢复'): _operate(q,'restore',[item]);st.rerun(scope='fragment')
                if st.button('永久删除'): _ask_purge(q,[item])
                confirmation=q.get('confirmation')
                if confirmation:
                    st.warning('永久删除后无法恢复：'+ '、'.join(i['name'] for i in confirmation['items']))
                    if st.button('确认永久删除'):
                        q.pop('confirmation',None);_operate(q,'purge',confirmation['items']);st.rerun(scope='fragment')
                    if st.button('取消删除'):
                        q.pop('confirmation',None);st.rerun(scope='fragment')
            elif st.button('移入回收站'): _operate(q,'recycle',[item]);st.rerun(scope='fragment')
        if st.button('取消 / 返回'): go('browse')
