"""Loopback browser fixture: every robot operation is a deterministic substitute."""
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import streamlit as st
from test_robot_control import Controller,route,trajectory
from src.core.assets import AssetLibrary
from src.robot.ur5.path_config import PathStore
from src.robot.ur5.task_service import TaskService,_SERVICES
from apps.gui.views import robot_page
from apps.gui import robot_task_ui


st.set_page_config(layout='wide')
@st.cache_resource
def resources():
    temporary=tempfile.TemporaryDirectory(prefix='tanghua-robot-browser-')
    root=temporary.name;ip='127.0.0.79';controller=Controller('running')
    service=TaskService(root,ip,controller.factory)
    original=controller.factory
    def factory(address):
        channel=original(address);receive=channel.receive
        def slow_receive():time.sleep(.01);return receive()
        channel.receive=slow_receive;return channel
    service.factory=factory
    _SERVICES[(str(Path(root).resolve()),ip)]=service
    store=PathStore(root,ip);store.save(route())
    import json
    item=AssetLibrary(root).import_file(json.dumps(trajectory().to_dict()).encode(),'browser_trajectory.json')
    return temporary,root,ip,controller,service,item


temporary,root,ip,controller,service,item=resources()
st.session_state.setdefault('robot_ip',ip)
st.session_state.setdefault('asset_selected_robot',[str(AssetLibrary(root).path(item['id']))])
from src.robot.ur5.workspace_calibration import CORNERS
import copy
sample_roles={'准备姿态':'prepare','落笔姿态':'pen',**{label:key for key,label in CORNERS.items()}}
selected=st.selectbox('替身读取位置',list(sample_roles))
buttons=st.columns(4)
if buttons[0].button('模拟离线'):controller.offline=True
if buttons[1].button('模拟在线'):controller.offline=False
if buttons[2].button('模拟正常完成'):controller.mode='complete'
if buttons[3].button('模拟持续运行'):
    controller.mode='running'
    if service.snapshot()['state'] not in {'checking','sending','waiting','running','stopping','unknown'}:
        controller.started=False;controller.stop=False;controller.count=0
def adapter(address):
    value=controller.adapter()
    original_send=value._send_script;original_stop=value.stop_program
    value._send_script=lambda script:False if getattr(controller,'offline',False) else original_send(script)
    value.stop_program=lambda:False if getattr(controller,'offline',False) else original_stop()
    return value
robot_page._adapter=adapter
service.adapter=adapter(ip)
def sample(address):
    if getattr(controller,'offline',False):raise ConnectionError('替身离线')
    config=PathStore(root,ip).load()['calibration'];role=sample_roles[selected]
    point=config['corners'][role] if role in CORNERS else config[role]
    controller.clock.value+=1
    return (3,15,8,0),dict(actual_q=point['q'],actual_qd=[0.]*6,actual_TCP_pose=point['tcp'],tcp_offset=[0.]*6,timestamp=controller.clock.value)
robot_task_ui.read_sample=sample
robot_page.read_sample=sample
with patch('socket.create_connection',side_effect=AssertionError('No real connection permitted')):
    robot_page.render({},root)
