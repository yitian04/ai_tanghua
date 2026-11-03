from __future__ import annotations
from pathlib import Path
import uuid
import yaml
from apps.gui.parameter_ui import ui as st
from apps.gui.asset_library import file_input
from apps.gui.views.ur_execution_controls import render_urscript_execution_profile,execution_profile_caption
from apps.gui.robot_task_ui import task_panel,render_path_settings,owner_id,read_sample
from src.robot.ur5 import UR5RobotAdapter
from src.robot.ur5.path_config import PathStore,validate_config
from src.robot.ur5.task_service import get_service,ACTIVE
from src.robot.job_loader import load_trajectory_file


def _init_state(config):
    st.session_state.setdefault('robot_ip',config.get('robot',{}).get('ip','192.168.1.100'))
    try:
        state=get_service(st.session_state.get('robot_root','.'),st.session_state.robot_ip).snapshot() if st.session_state.get('robot_root') else {}
        if state.get('job')!=st.session_state.get('robot_last_accepted_job'):
            st.session_state['robot_execute_confirmed']=False
            st.session_state['robot_last_accepted_job']=state.get('job')
    except ValueError:pass
    # Construction and rendering do not open network connections.
    if 'ur5_robot' not in st.session_state:st.session_state['ur5_robot']=UR5RobotAdapter(timeout=1.)


def _adapter(ip):
    robot=UR5RobotAdapter(timeout=1.);robot.set_ip(ip);return robot


def _save_tcp_orientation_as_planning_default(root_dir: str, tcp_pose_mm_deg) -> Path:
    if not tcp_pose_mm_deg or len(tcp_pose_mm_deg) < 6:
        raise ValueError("current TCP pose does not contain rotation vector")
    rx_deg, ry_deg, rz_deg = [float(value) for value in tcp_pose_mm_deg[3:6]]
    config_path = Path(root_dir) / "config" / "settings.yaml"
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        config = {}
    if not isinstance(config, dict):
        config = {}
    planning = config.get("planning")
    if not isinstance(planning, dict):
        planning = {}
    planning["tool_rx_deg"] = rx_deg
    planning["tool_ry_deg"] = ry_deg
    planning["tool_rz_deg"] = rz_deg
    config["planning"] = planning
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    st.session_state["planning_tool_rx_deg"] = rx_deg
    st.session_state["planning_tool_ry_deg"] = ry_deg
    st.session_state["planning_tool_rz_deg"] = rz_deg
    from src.core.preferences import PreferenceStore
    PreferenceStore(root_dir).patch_defaults('planning',dict(zip(('工具姿态 Rx deg','工具姿态 Ry deg','工具姿态 Rz deg'),(rx_deg,ry_deg,rz_deg))))
    return config_path



def _render_ur5_control(config,root_dir):
    st.subheader('UR5 控制')
    ip=st.text_input('机器人 IP 地址',value=st.session_state.get('robot_ip','192.168.1.100'),key='robot_ip_input')
    try:
        service=get_service(root_dir,ip)
    except ValueError:
        st.error('请输入有效 IP 地址。');return
    st.session_state['robot_ip']=ip
    robot=_adapter(ip)
    if service.adapter is None:service.adapter=robot
    task_panel(root_dir,ip)
    busy=service.snapshot()['state'] in ACTIVE
    with st.expander('诊断与电源（仅点击时连接）'):
        if st.button('读取版本与状态',disabled=busy):
            try:
                version,sample=read_sample(ip)
                st.session_state['robot_diagnostic']={'ip':ip,'version':version,'sample':sample}
                st.success('CB3 '+'.'.join(map(str,version)))
            except Exception as exc:st.error(str(exc))
        diagnostic=st.session_state.get('robot_diagnostic')
        if diagnostic and diagnostic['ip']==ip:st.json(diagnostic)
        if st.button('使用当前TCP姿态作为规划默认',disabled=busy):
            try:
                import math
                _,fresh=read_sample(ip)
                pose=fresh['actual_TCP_pose']
                _save_tcp_orientation_as_planning_default(root_dir,[v*1000 for v in pose[:3]]+[math.degrees(v) for v in pose[3:]])
                st.success('已保存规划默认姿态；未修改当前轨迹或路径。')
            except Exception as exc:st.error(str(exc))
        a,b,c=st.columns(3)
        for col,label,method in ((a,'上电 Power On',robot.power_on),(b,'使能/松刹车',robot.brake_release),(c,'下电 Power Off',robot.power_off)):
            if col.button(label,disabled=busy):
                if method():st.success('命令已确认；请重新读取状态。')
                else:st.error('命令失败或未确认：'+robot.last_dashboard_response)
    render_path_settings(root_dir,ip)
    st.caption('停止按钮与心跳不属于安全认证功能。现场实体急停和阀门失效行为必须单独核验。')


def _render_job_execution(config,root_dir):
    st.divider();st.markdown('### 数字轨迹执行')
    path=file_input(root_dir,'robot','轨迹输入',{'trajectory','program'},candidate=st.session_state.get('latest_trajectory_path'))
    profile=render_urscript_execution_profile(config,root_dir)
    ip=st.session_state.get('robot_ip','192.168.1.100')
    try:service=get_service(root_dir,ip);route=PathStore(root_dir,ip).load()
    except ValueError:st.info('请先填写有效 IP。');return
    from dataclasses import replace
    profile=replace(profile,output_pin=route['output_pin'])
    st.caption(execution_profile_caption(profile))
    busy=service.snapshot()['state'] in ACTIVE
    st.caption(f"路径出料端口：DO{route['output_pin']}；路径设置为唯一执行端口来源。进出路径使用独立低速参数；首版整个任务固定 10% 控制器倍率（包含绘制），实际速度还受加速度与安全限制影响。")
    st.caption('导入本项目 URP/脚本时使用其导出时的执行参数，并重新核对当前路径；上方参数用于标准轨迹。')
    from apps.gui.robot_task_ui import execution_requirements,teaching_dirty
    trial_issues=execution_requirements(route)
    formal_issues=execution_requirements(route,formal=True)
    if teaching_dirty(root_dir,ip):
        trial_issues.append('有未保存的示教设置，请先保存工作区配置。')
        formal_issues.append('有未保存的示教设置，请先保存工作区配置。')
    if not path:
        trial_issues.append('尚未导入轨迹。');formal_issues.append('尚未导入轨迹。')
    if formal_issues:
        st.info('正式绘制尚缺：\n\n'+'\n\n'.join('• '+text for text in dict.fromkeys(formal_issues)))
    if trial_issues:st.caption('关料试运行尚缺：'+'；'.join(dict.fromkeys(trial_issues)))
    confirmed=st.checkbox('我已核对轨迹、工作区示教、TCP、接线与现场条件，允许本次任务',disabled=busy,key='robot_execute_confirmed')
    def launch(dry_run):
        try:
            if Path(path).suffix.lower() in {'.urp','.script'}:
                from src.pipeline.export.urscript_exporter import load_controlled_program
                from src.robot.ur5.path_config import fingerprint
                trajectory,export_route,options=load_controlled_program(path)
                if fingerprint(export_route)!=fingerprint(route):raise ValueError('导出程序的工作区配置与当前配置不同，请重新导出。')
            else:trajectory=load_trajectory_file(path);options=profile.compile_options()
            service.submit(_adapter(ip),trajectory,route,options,owner_id(),dry_run=dry_run)
            st.rerun()
        except Exception as exc:st.error(str(exc))
    trial,formal=st.columns(2)
    if trial.button('关料试运行',disabled=busy or not confirmed or bool(trial_issues),width='stretch'):
        launch(True)
    if formal.button('正式绘制',type='primary',disabled=busy or not confirmed or bool(formal_issues),width='stretch'):
        launch(False)
    st.caption('关料试运行会驱动真实机械臂，全程不出料；首次或配置改变后试运行并确认即可，不要求每次重复。停止后不会自动抬笔或返回。')



def render(config,root_dir):
    st.session_state["robot_root"]=root_dir
    _init_state(config)
    _render_ur5_control(config,root_dir)
    _render_job_execution(config,root_dir)
