"""Commissioned robot routes. Nothing in this module moves a robot."""
from __future__ import annotations
import copy
import hashlib
import json
import math
from pathlib import Path
import time
import uuid


def finite_vector(value, size=6):
    return isinstance(value,(list,tuple)) and len(value)==size and all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in value)


def new_config():
    from .workspace_calibration import empty_calibration
    return dict(schema_version=2,calibration=empty_calibration(),workspace=None,start=None,prepare=None,enter=[],exit=[],tcp_offset=None,
                bounds=[-300,300,-800,-300,0,500],draw_z_mm=250.,approach_z_mm=280.,
                joint_tolerance_deg=1.,position_tolerance_mm=2.,orientation_tolerance_deg=1.,
                travel_mm_s=20.,joint_rad_s=.105,acceleration=.05,output_pin=0,
                registers_confirmed=False,wiring_confirmed=False,registers=[24,25,26,27],
                validated=None,dry_run=None)


def fingerprint(config):
    data={k:v for k,v in config.items() if k not in {'validated','dry_run'}}
    return hashlib.sha256(json.dumps(data,sort_keys=True,allow_nan=False).encode()).hexdigest()


def validate_config(c, verified=True):
    from .workspace_calibration import calibrated_config
    derived=calibrated_config(c)
    for field in ('start','prepare','bounds','draw_z_mm','approach_z_mm','workspace'):
        if c.get(field)!=derived[field]:raise ValueError('工作区数据已改变，请重新保存工作区配置。')
    for name in ('start','prepare'):
        validate_waypoint(c.get(name))
    for name in ('enter','exit'):
        if not isinstance(c.get(name),list): raise ValueError('绕障路径格式无效。')
        for point in c[name]: validate_waypoint(point)
    if not finite_vector(c.get('tcp_offset')): raise ValueError('请配置工具 TCP 偏移（m、rad）。')
    if not finite_vector(c.get('bounds')): raise ValueError('工作区范围无效。')
    for i in (0,2,4):
        if c['bounds'][i]>=c['bounds'][i+1]: raise ValueError('工作区最小值必须小于最大值。')
    for key in ('draw_z_mm','approach_z_mm','joint_tolerance_deg','position_tolerance_mm','orientation_tolerance_deg','travel_mm_s','joint_rad_s','acceleration'):
        if not isinstance(c.get(key),(float,int)) or not math.isfinite(c[key]): raise ValueError('路径参数必须为有限数值。')
    if any(c[k]<=0 for k in ('joint_tolerance_deg','position_tolerance_mm','orientation_tolerance_deg','travel_mm_s','joint_rad_s','acceleration')): raise ValueError('速度和容差必须为正数。')
    if c['travel_mm_s']>50 or c['joint_rad_s']>.2 or c['acceleration']>.2: raise ValueError('示教进出路径速度/加速度超过本软件低速上限。')
    if not c['bounds'][4]<=c['draw_z_mm']<c['approach_z_mm']<=c['bounds'][5]: raise ValueError('接近高度必须高于绘制平面，且在工作区内。')
    if type(c.get('output_pin')) is not int or not 0<=c['output_pin']<=7: raise ValueError('标准 DO 端口必须为 0–7。')
    if c.get('registers')!=[24,25,26,27] or not c.get('registers_confirmed'): raise ValueError('请确认外部寄存器 24–27 未被其他客户端占用。')
    if verified and (c.get('validated')!=fingerprint(c) or not c.get('wiring_confirmed')): raise ValueError('路径或接线尚未验证，请先关料试运行并确认。')


def validate_waypoint(p):
    if not isinstance(p,dict) or p.get('mode') not in {'movej','movel'} or not finite_vector(p.get('q')) or not finite_vector(p.get('tcp')):
        raise ValueError('请读取完整的关节/TCP位置，并指定 movej 或 movel。')
    if not isinstance(p.get('timestamp'),(int,float)) or not math.isfinite(p['timestamp']): raise ValueError('示教点缺少控制器时间。')


def record_waypoint(sample,mode='movel'):
    point=dict(q=list(sample['actual_q']),tcp=list(sample['actual_TCP_pose']),timestamp=sample['timestamp'],mode=mode)
    validate_waypoint(point)
    if max(abs(v) for v in sample['actual_qd'])>.002: raise ValueError('请先停稳，再记录示教点。')
    return point


def check_start(c,sample):
    for a,b in zip(sample['actual_q'],c['start']['q']):
        if abs(a-b)>math.radians(c['joint_tolerance_deg']): raise ValueError('当前位置与允许启动位置不符，请用示教器定位。')
    for i,(a,b) in enumerate(zip(sample['actual_TCP_pose'],c['start']['tcp'])):
        limit=c['position_tolerance_mm']/1000 if i<3 else math.radians(c['orientation_tolerance_deg'])
        if abs(a-b)>limit: raise ValueError('当前 TCP 与允许启动位置不符。')


def check_trajectory(c,t):
    from src.core.validation import validate_trajectory
    errors=validate_trajectory(t)
    if errors: raise ValueError('; '.join(errors))
    if not any(p.drawing for p in t.points): raise ValueError('轨迹没有绘制段。')
    for p in t.points:
        for i,v in enumerate((p.x_mm,p.y_mm,p.z_mm)):
            if not c['bounds'][2*i]<=v<=c['bounds'][2*i+1]: raise ValueError('轨迹超出已验证工作区。')
        if p.z_mm>c['approach_z_mm']: raise ValueError('轨迹高度高于已验证接近高度。')
        if p.drawing and abs(p.z_mm-c['draw_z_mm'])>c['position_tolerance_mm']: raise ValueError('绘制高度与已验证平面不符。')
    for point in c['enter']+c['exit']:validate_waypoint(point)



class PathStore:
    def __init__(self,root,ip):
        import ipaddress
        self.path=Path(root)/'data'/'.robot_config'/(str(ipaddress.ip_address(ip)).replace(':','_')+'.json')
    def load(self):
        if not self.path.exists(): return new_config()
        data=json.loads(self.path.read_text(encoding='utf-8'))
        if data.get('schema_version')!=2:
            result={**new_config(),**data,'schema_version':2,'validated':None,'dry_run':None}
            result['legacy_route']=copy.deepcopy(data)
            from .workspace_calibration import empty_calibration
            result['calibration']=empty_calibration()
            result['calibration']['prepare']=copy.deepcopy(data.get('prepare'))
            result['start']=copy.deepcopy(data.get('prepare'))
            result['workspace']=None
            return result
        return {**new_config(),**data}
    def save(self,c):
        c=copy.deepcopy(c)
        old=self.load()
        if old['output_pin']!=c['output_pin']:c['wiring_confirmed']=False
        if c.get('validated')!=fingerprint(c): c['validated']=None;c['dry_run']=None
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        temp.write_text(json.dumps(c,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');temp.replace(self.path)
        return c
