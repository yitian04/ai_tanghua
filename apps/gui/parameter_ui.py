"""Thread-local Streamlit facade for explicitly scoped ordinary settings."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import inspect
import json
import re

import streamlit as _st
from src.core.preferences import PreferenceStore

_ACTIVE=ContextVar('parameter_scope',default=None)
_GROUPS=ContextVar('parameter_groups',default=None)
WIDGETS={'number_input','slider','selectbox','radio','checkbox','text_input','text_area'}
EXCLUDED=('主体名称','参考图主体','文字内容','合成文件名称','对象名称','固定主体','已有公开','选择要恢复','我已','同时加入','准备姿态','现场')
PLANE={'画布宽 mm','画布高 mm','机器人中心 X mm','机器人中心 Y mm','绘制 Z mm','抬笔高度 mm','空走速度 mm/s','Rx deg','Ry deg','Rz deg'}


class Scope:
    def __init__(self,root,group):self.root=root;self.group=group;self.store=PreferenceStore(root);self.keys={};self.values=self.store.current(group)
    def field(self,kind,label,kwargs):
        if kwargs.get('type')=='password' or any(label.startswith(x) for x in EXCLUDED):return None
        key=str(kwargs.get('key',''))
        if self.group=='svg' and (label=='主题与需求' or key.startswith(('svg_ack','svg_model_list','svg_vision'))):return None
        if self.group=='execution':
            # Human-facing wording may improve without losing saved settings.
            return {'转弯圆滑程度 mm':'blend mm','加速度 m/s²':'URScript加速度 m/s²'}.get(label,label)
        if self.group=='composition' and label not in PLANE:return None
        if self.group=='robot' and label!='机器人 IP 地址':return None
        if self.group=='ai':
            if 'recover_' in key or 'oauth' in key or label=='账户 / 服务商':return None
            if kind in {'text_input','text_area'} and not (label in {'模型 ID','API 地址'} or '自定义 ID' in label or label.startswith(('提示词正文','反向提示词'))):return None
            if key.startswith(('positive_prompt_','negative_prompt_')):
                direction='positive' if key.startswith('positive') else 'negative'
                stage='line_art' if '_line_art_' in key else 'sample'
                language='en' if key.endswith('_en') else 'zh'
                return f'{direction}:{stage}:{language}'
            if kind in {'radio','selectbox'} and not isinstance(label,str):return None
            # Stable explicit keys distinguish stage-specific model selectors.
            return key or label
        if self.group=='text' and kind in {'text_input','text_area'}:return None
        if self.group=='vector' and kind in {'text_input','text_area'}:return None
        return label


@contextmanager
def parameter_scope(root,group):
    scopes=_GROUPS.get();owner=scopes is None
    if owner:scopes=[];group_token=_GROUPS.set(scopes)
    scope=next((s for s in scopes if s.group==group),None) or Scope(root,group)
    if scope not in scopes:scopes.append(scope)
    token=_ACTIVE.set(scope)
    try:yield scope
    finally:
        _ACTIVE.reset(token)
        if owner:_GROUPS.reset(group_token)


def render_actions(scopes):
    for scope in scopes:
        if not scope.keys:continue
        def restore(s=scope):
            values=s.store.restore(s.group)
            for field,key in s.keys.items():
                if field in values:_st.session_state[key]=values[field]
        def save(s=scope):s.store.save_defaults(s.group)
        with _st.container(key='parameter_actions_'+scope.group,gap='small'):
            _st.caption('URScript 执行参数' if scope.group=='execution' else '参数设置')
            row=_st.container(horizontal=True,gap='small')
            row.button('恢复默认设置',key='restore_parameters_'+scope.group,on_click=restore)
            row.button('保存为默认设置',key='save_parameters_'+scope.group,on_click=save)


def render_current_actions():render_actions(_GROUPS.get() or [])


class UI:
    def __init__(self,target):self.target=target
    def __enter__(self):self.target.__enter__();return self
    def __exit__(self,*args):return self.target.__exit__(*args)
    def __getattr__(self,name):
        target=getattr(self.target,name)
        if name in {'columns','tabs'}:
            return lambda *args,**kwargs:[UI(item) for item in target(*args,**kwargs)]
        if name in {'container','expander','form','empty','popover'}:
            return lambda *args,**kwargs:UI(target(*args,**kwargs))
        if name=='button':
            def button(label,*args,**kwargs):
                if _ACTIVE.get():
                    from apps.gui.workspace import action_button
                    return action_button(target,label,*args,**kwargs)
                return target(label,*args,**kwargs)
            return button
        if name=='error':
            def error(message,*args,**kwargs):
                if _st.session_state.get('wf_running'):_st.session_state['wf_error']=str(message)
                return target(message,*args,**kwargs)
            return error
        if name not in WIDGETS:return target
        def widget(*args,**kwargs):
            scope=_ACTIVE.get()
            if not scope:return target(*args,**kwargs)
            bound=inspect.signature(target).bind_partial(*args,**kwargs);values=dict(bound.arguments)
            label=str(values.get('label',''));field=scope.field(name,label,values)
            if field is None:return target(*args,**kwargs)
            key=values.get('key') or 'setting_'+scope.group+'_'+hashlib.sha256(field.encode()).hexdigest()[:12]
            values['key']=key;scope.keys[field]=key
            options=list(values.get('options',[])) if name in {'selectbox','radio'} else None
            default=options[int(values.get('index',0) or 0)] if options else values.get('value',False if name=='checkbox' else None)
            if isinstance(default,tuple):default=list(default)
            try:json.dumps(default,allow_nan=False)
            except (TypeError,ValueError):return target(*args,**kwargs)
            scope.store.seed(scope.group,field,default)
            remembered=scope.values.get(field,default)
            if options is not None and remembered not in options:remembered=default
            if name in {'number_input','slider'} and isinstance(remembered,(int,float)):
                if values.get('min_value') is not None:remembered=max(values['min_value'],remembered)
                if values.get('max_value') is not None:remembered=min(values['max_value'],remembered)
                if isinstance(default,int) and not isinstance(default,bool):remembered=int(remembered)
            # Let Streamlit initialize its own state from the remembered default.
            # Existing state (including restore callbacks) is the sole authority.
            if key not in _st.session_state:
                if options is not None:
                    values['index']=options.index(remembered) if remembered in options else values.get('index',0)
                elif remembered is not None:
                    values['value']=remembered
            else:
                if options is not None: values['index']=0
                elif name=='checkbox': values['value']=False
                elif name in {'text_input','text_area'}: values['value']=''
                elif name=='number_input': values['value']='min'
                elif name=='slider': values['value']=None
            original_callback=values.get('on_change');callback_args=values.get('args') or ();callback_kwargs=values.get('kwargs') or {}
            def changed():
                # Navigation/reset can remove a widget before an already queued
                # callback runs. That event no longer owns a value or an action.
                try:
                    current=_st.session_state[key]
                except KeyError:
                    return
                scope.store.remember(scope.group,{field:current})
                if original_callback:original_callback(*callback_args,**callback_kwargs)
            values['on_change']=changed;values.pop('args',None);values.pop('kwargs',None)
            if _st.session_state.get('wf_running'):values['disabled']=True
            result=target(**values)
            if scope.store.current(scope.group).get(field)!=result:scope.store.remember(scope.group,{field:result})
            return result
        return widget


ui=UI(_st)
