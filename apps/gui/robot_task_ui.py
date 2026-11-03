"""Robot controls: explicit connections only, persistent routes, live task view."""
from __future__ import annotations
import copy
import hashlib
import json
import math
from pathlib import Path
import uuid
import streamlit as st
import streamlit.components.v2 as components
from src.robot.ur5.path_config import PathStore,record_waypoint,fingerprint,validate_config
from src.robot.ur5.rtde_channel import RTDEChannel
from src.robot.ur5.task_service import get_service,LABELS,ACTIVE


@st.cache_resource
def heartbeat_component(js):
    return components.component('robot_online_'+hashlib.sha256(js.encode()).hexdigest()[:12],js=js)


def owner_id():
    if 'robot_owner_id' not in st.session_state:st.session_state['robot_owner_id']=uuid.uuid4().hex
    return st.session_state['robot_owner_id']


@st.fragment(run_every=.5)
def task_panel(root,ip):
    service=get_service(root,ip);state=service.snapshot()
    previous=st.session_state.get('robot_display_state_'+ip)
    st.session_state['robot_display_state_'+ip]=state['state']
    if previous is not None and previous!=state['state']:
        # Refresh the controls outside this fragment once per state transition.
        st.rerun()
    def pulse():service.heartbeat(owner_id())
    # Every user can request a stop; only the initiating browser supplies the lease.
    if state['state'] in ACTIVE and service.owner==owner_id():
        js=(Path(__file__).parent/'components'/'robot_heartbeat.js').read_text(encoding='utf-8')
        heartbeat_component(js)(key='robot_online',data={'job':state['job']},on_pulse_change=pulse,height='content')
    st.markdown('**任务状态：'+LABELS[state['state']]+'**')
    st.caption(state['message'])
    if state.get('stop_notice'):
        st.info(state['stop_notice'])
        if st.button('清除停止提示',key='robot_clear_stop_notice'):
            try:service.clear_stop_notice();st.rerun(scope='fragment')
            except ValueError as exc:st.warning(str(exc))
    if state.get('stop_errors'):st.error('；'.join(state['stop_errors'])+'。请使用实体停止装置。')
    # This button deliberately has no motion/ownership disable condition.
    st.html('<style>.st-key-robot_stop_bar{position:fixed;right:24px;bottom:20px;z-index:1000;width:220px;max-width:calc(100vw - 32px);padding:8px;background:var(--background-color,#fff);border-radius:8px}.st-key-robot_stop_bar button{background:#b42336;color:white;min-height:44px}</style>')
    with st.container(key='robot_stop_bar'):
        if st.button('停止并关料',type='primary',key='robot_stop_always',width='stretch'):
            service.request_stop();st.rerun(scope='fragment')
    if state['state'] in {'unknown','stopping'}:
        if st.button('只读核对停稳与关料',key='robot_reconcile'):
            try:
                service.reconcile(None,state.get('output_pin',0));st.rerun(scope='fragment')
            except Exception as exc:st.error(str(exc))


def read_sample(ip):
    channel=RTDEChannel(ip)
    try:
        version=channel.open(control=False);sample=channel.receive()
        return version,sample
    finally:channel.close()


def _draft_key(ip):return 'robot_teaching_draft_'+ip


def teaching_dirty(root,ip):
    value=st.session_state.get(_draft_key(ip))
    return bool(value and fingerprint(value)!=fingerprint(PathStore(root,ip).load()))


def _point_summary(point):
    if not point:return '尚未记录'
    xyz=point['tcp'][:3];rot=point['tcp'][3:]
    return ' · '.join(f'{name} {v*1000:.1f} mm' for name,v in zip(('X','Y','Z'),xyz))+'\n\n'+ ' · '.join(f'{name} {math.degrees(v):.1f}°' for name,v in zip(('Rx','Ry','Rz'),rot))


def execution_requirements(c,formal=False):
    from src.robot.ur5.workspace_calibration import derive_workspace
    issues=[]
    try:derive_workspace(c.get('calibration',{}))
    except (ValueError,KeyError,TypeError) as exc:issues.append(str(exc))
    if not c.get('tcp_offset'):issues.append('尚未保存 TCP 工具标定。')
    if not c.get('registers_confirmed'):issues.append('尚未确认首次通信设置（寄存器 24–27）。')
    if not issues:
        try:validate_config(c,verified=False)
        except ValueError as exc:issues.append(str(exc))
    if formal:
        if not c.get('wiring_confirmed'):issues.append('尚未确认出料端口接线与异常关料。')
        if c.get('validated')!=fingerprint(c):issues.append('本配置尚未试运行并确认验证。')
    return issues


def render_path_settings(root,ip):
    from src.robot.ur5.workspace_calibration import CORNERS,calibrated_config,derive_workspace,save_planning_defaults
    from apps.gui.robot_help import help_button
    store=PathStore(root,ip);saved=store.load();service=get_service(root,ip)
    busy=service.snapshot()['state'] in ACTIVE
    key=_draft_key(ip)
    if key not in st.session_state:st.session_state[key]=copy.deepcopy(saved)
    c=st.session_state[key]
    title,info=st.columns([4,1])
    title.markdown('### 工作区示教')
    with info:help_button('workspace')
    st.caption('用示教器定位并停稳，再读取。读取和保存不会移动机器人；首版只支持水平、与机器人 XY 对齐的矩形。')
    if busy:st.info('任务未结束或结果未知，示教与保存暂时锁定；停止入口仍可操作。')
    calibration=c['calibration']
    def point_card(label,role,container):
        with container:
            st.markdown('**'+label+'**')
            point=calibration['corners'].get(role) if role in CORNERS else calibration.get(role)
            st.caption(_point_summary(point))
            if st.button('读取当前位置',key='teach_'+ip+'_'+role,disabled=busy,width='stretch'):
                try:
                    _,fresh=read_sample(ip)
                    point=record_waypoint(fresh,'movej' if role=='prepare' else 'movel')
                    if role in CORNERS:calibration['corners'][role]=point
                    else:calibration[role]=point
                    if fresh.get('tcp_offset'):c['tcp_offset']=list(fresh['tcp_offset'])
                    c['workspace']=None;c['validated']=None;c['dry_run']=None
                    st.rerun()
                except Exception as exc:st.error(str(exc))
    first,second=st.columns(2)
    point_card('1 · 准备姿态（开始／结束）','prepare',first)
    point_card('2 · 落笔姿态（绘制高度／朝向）','pen',second)
    st.markdown('**3 · 绘制区域四角**')
    st.caption('X → 向右，Y ↓ 向下；左上是 X 小、Y 小。四角均记录工具尖端位于绘制台面时的位置。')
    st.markdown('| 左上角 ↔ 上边 ↔ 右上角 |\n|:--:|\n| ↓ 左边　　绘制区域　　右边 ↓ |\n| 左下角 ↔ 下边 ↔ 右下角 |')
    for roles in (('top_left','top_right'),('bottom_left','bottom_right')):
        for col,role in zip(st.columns(2),roles):point_card(CORNERS[role],role,col)
    lift=st.number_input('4 · 抬起高度 mm（相对绘制台面）',min_value=.1,value=float(calibration.get('lift_mm',20.)),disabled=busy,key='teach_lift_'+ip)
    if lift!=calibration.get('lift_mm'):
        calibration['lift_mm']=lift;c['workspace']=None;c['validated']=None;c['dry_run']=None
    geometry=None
    try:
        geometry=derive_workspace(calibration)
        st.success(f"区域 {geometry['width_mm']:.1f} × {geometry['height_mm']:.1f} mm · 中心 ({geometry['center_x_mm']:.1f}, {geometry['center_y_mm']:.1f}) mm · 绘制 Z {geometry['draw_z_mm']:.1f} mm · 抬起后 Z {geometry['approach_z_mm']:.1f} mm")
    except (ValueError,KeyError,TypeError) as exc:st.info(str(exc))
    dirty=teaching_dirty(root,ip)
    a,b=st.columns(2)
    if a.button('保存工作区配置',disabled=busy or geometry is None,width='stretch'):
        try:
            c=store.save(calibrated_config(c));st.session_state[key]=copy.deepcopy(c)
            st.session_state['robot_setup_notice']='已保存工作区；改变配置后请关料试运行并重新确认。'
            st.rerun()
        except Exception as exc:st.error(str(exc))
    if b.button('保存至轨迹规划默认设置',disabled=busy or geometry is None or dirty,width='stretch'):
        save_planning_defaults(root,store.load());st.success('已更新规划默认值与最近值；现有轨迹和速度未改变。')
    if dirty:
        st.caption('有未保存的示教或设置，请先保存工作区配置。')
        if st.button('放弃未保存设置',disabled=busy):
            st.session_state[key]=copy.deepcopy(saved)
            st.session_state.pop('teach_lift_'+ip,None);st.rerun()
    if st.session_state.get('robot_setup_notice'):st.caption(st.session_state.pop('robot_setup_notice'))
    with st.expander('工具标定'):
        st.caption('TCP 是法兰到工具尖端的偏移，不是落笔位置。读取示教点时，新控制器会自动提供 TCP；旧控制器请按示教器填写。')
        with st.form('tcp_settings_'+ip):
            current=c.get('tcp_offset')
            display=[v*1000 for v in current[:3]]+[math.degrees(v) for v in current[3:]] if current else [0.]*6
            cols=st.columns(3);values=[]
            for i,(label,value) in enumerate(zip(('偏移 X mm','偏移 Y mm','偏移 Z mm','偏移 Rx deg','偏移 Ry deg','偏移 Rz deg'),display)):
                values.append(cols[i%3].number_input(label,value=float(value),format='%.3f'))
            if st.form_submit_button('应用工具标定',disabled=busy):
                c['tcp_offset']=[v/1000 for v in values[:3]]+[math.radians(v) for v in values[3:]]
                st.rerun()
    with st.expander('出料装置'):
        with st.form('output_settings_'+ip):
            pin=int(st.number_input('控制箱标准 DO 端口',min_value=0,max_value=7,value=int(c['output_pin'])))
            wiring=st.checkbox('已核验此端口低电平关料及控制器异常关料行为',value=bool(c['wiring_confirmed']))
            if st.form_submit_button('应用出料设置',disabled=busy):
                c['wiring_confirmed']=wiring if pin==c['output_pin'] else False
                c['output_pin']=pin;st.rerun()
    with st.expander('高级运动设置与绕障路径'):
        with st.form('motion_settings_'+ip):
            a,b=st.columns(2);updates={}
            updates['travel_mm_s']=a.number_input('进出直线速度 mm/s',min_value=.1,max_value=50.,value=float(c['travel_mm_s']))
            joint=b.number_input('进出关节速度 deg/s',min_value=.1,max_value=math.degrees(.2),value=math.degrees(c['joint_rad_s']),format='%.2f')
            updates['joint_rad_s']=math.radians(joint)
            updates['acceleration']=a.number_input('进出加速度 m/s²',min_value=.001,max_value=.2,value=float(c['acceleration']),format='%.3f')
            updates['position_tolerance_mm']=b.number_input('准备位位置容差 mm',min_value=.1,value=float(c['position_tolerance_mm']))
            updates['joint_tolerance_deg']=a.number_input('准备位关节容差 deg',min_value=.1,value=float(c['joint_tolerance_deg']))
            updates['orientation_tolerance_deg']=b.number_input('准备位姿态容差 deg',min_value=.1,value=float(c['orientation_tolerance_deg']))
            if st.form_submit_button('应用运动设置',disabled=busy):c.update(updates);st.rerun()
        st.caption('仅在有障碍时记录。进入和返回分别配置，不自动反转；每段方式明确指定，仍需试运行。')
        direction=st.selectbox('路径方向',['进入','返回'],disabled=busy)
        mode=st.selectbox('绕障段运动方式',['movel','movej'],disabled=busy)
        if st.button('读取并添加绕障点',disabled=busy):
            try:
                _,sample=read_sample(ip);c['enter' if direction=='进入' else 'exit'].append(record_waypoint(sample,mode));st.rerun()
            except Exception as exc:st.error(str(exc))
        for field,label in (('enter','进入'),('exit','返回')):
            for i,point in enumerate(c[field]):
                line,action=st.columns([5,1]);line.caption(f'{label} {i+1} · {point["mode"]} · '+_point_summary(point))
                if action.button('删除',key=f'waypoint_delete_{ip}_{field}_{i}',disabled=busy):c[field].pop(i);st.rerun()
    with st.expander('首次通信设置'):
        st.caption('外部寄存器 24–27 用于心跳、任务编号、阶段和完成标记，不得被 PLC 或其他客户端占用。')
        confirmed=st.checkbox('确认寄存器 24–27 未被其他程序占用',value=bool(c['registers_confirmed']),disabled=busy,key='teach_registers_'+ip)
        c['registers_confirmed']=confirmed
    snapshot=service.snapshot();saved=store.load()
    eligible=snapshot['state']=='completed' and snapshot.get('dry_run') and snapshot.get('route')==fingerprint(saved) and not snapshot.get('prepare_only') and not teaching_dirty(root,ip)
    observed=st.checkbox('已观察完整关料试运行，确认接近、整个绘制区上方、抬离与返回均无障碍',disabled=not eligible or busy,key='robot_route_observed_'+fingerprint(saved)+'_'+str(snapshot.get('job')))
    if st.button('确认本配置已验证',disabled=not eligible or not observed or busy):
        try:
            validate_config(saved,verified=False)
            if not saved['wiring_confirmed']:raise ValueError('请先核验并保存出料接线设置，然后重新试运行。')
            saved['dry_run']=snapshot['job'];saved['validated']=fingerprint(saved)
            store.save(saved);st.session_state[key]=copy.deepcopy(saved);st.rerun()
        except ValueError as exc:st.error(str(exc))
    if saved.get('validated')==fingerprint(saved):st.success('本配置已确认验证，可正式绘制；仍须每次检查现场。')
    return saved


