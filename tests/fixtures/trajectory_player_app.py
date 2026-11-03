"""Isolated browser-test surface; not part of the application's navigation."""
import json
from pathlib import Path
import sys
import streamlit as st

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.gui.trajectory_player import render_trajectory_player
from src.core.models import Trajectory,TrajectoryPoint as P
from src.core.assets import AssetLibrary
from src.pipeline.trajectory_composition.composer import import_trajectory

st.set_page_config(layout='wide')


@st.cache_data
def samples():
    data={
        '指令检查':Trajectory([P(0,0,10,1,False),P(0,0,0,1,False),P(0,0,0,1,True),P(10,0,0,1,True),P(10,0,10,1,False),P(10,5,10,1,False),P(10,5,0,1,False),P(10,5,0,1,True,curve_id=2),P(20,5,0,1,True,curve_id=2)]),
        '压力样本':Trajectory([P((i%100)*.5,(i//100)*.5,1 if i%10 else 5,10,bool(i%10),curve_id=i//10) for i in range(10000)]),
        '零时长':Trajectory([P(0,0,0,1,False),P(0,0,0,1,True),P(0,0,0,1,False),P(0,0,0,1,True)]),
    }
    lib=AssetLibrary(ROOT);real=[]
    for asset in lib.scan():
        if asset['kind']=='trajectory' and not asset['name'].startswith('SIM'):
            real.append(import_trajectory(lib.read(asset),asset['name']))
    if real:data['真实轨迹']=max(real,key=lambda t:len(t.points))
    return data


available=samples()
choice=st.selectbox('测试样本',list(available))
st.checkbox('触发页面重绘')
if st.button('重新显示预览' if st.session_state.get('hide_player') else '收起预览'):
    st.session_state['hide_player']=not st.session_state.get('hide_player',False);st.rerun()
if not st.session_state.get('hide_player'):
    st.caption(f'{len(available[choice].points)} 个轨迹点')
    render_trajectory_player(available[choice],'runtime_test')
