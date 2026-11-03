"""Real application routing with a temporary library and a text-model substitute."""
from pathlib import Path
import sys,tempfile
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import streamlit as st
from test_svg_generation import SVG
from src.pipeline.svg_generation.service import ChatClient,Credentials
from src.core.assets import AssetLibrary
from apps.gui import app
@st.cache_resource
def data():return tempfile.TemporaryDirectory(prefix='svg-browser-'),[]
temp,calls=data()
def response(self,endpoint,payload=None):
    if endpoint=='/models':return {'data':[{'id':'fixture'}]}
    calls.append(payload['model'])
    return {'choices':[{'message':{'content':SVG.replace('0 0 100 100','0 0 1024 1024')},'finish_reason':'stop'}],'model':'fixture','usage':{'total_tokens':10}}
ChatClient.request=response
Credentials.load=lambda self:{'base':'https://api.chatanywhere.tech/v1','api_key':'fixture'}
st.session_state.setdefault('main_navigation','AI SVG 曲线')
app.ROOT_DIR=temp.name
app.main()
st.caption('替身生成次数：'+str(len(calls)))
st.caption('已入库数量：'+str(len(AssetLibrary(temp.name).scan())))

