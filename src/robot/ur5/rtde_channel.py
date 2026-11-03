"""Official UR RTDE client boundary; construction never connects to a robot."""
from __future__ import annotations
import math
from threading import RLock
import time

BASE_FIELDS={'timestamp':'DOUBLE','actual_q':'VECTOR6D','actual_qd':'VECTOR6D',
             'actual_TCP_pose':'VECTOR6D','actual_TCP_speed':'VECTOR6D',
             'robot_mode':'INT32','safety_mode':'INT32','runtime_state':'UINT32',
             'actual_digital_output_bits':'UINT64','speed_scaling':'DOUBLE',
             'target_speed_fraction':'DOUBLE',
             **{f'output_int_register_{n}':'INT32' for n in (25,26,27)}}


class RTDEChannel:
    def __init__(self,ip):
        self.ip=ip;self.conn=None;self.inputs=None;self.lock=RLock();self.version=None
    def open(self,control=False):
        try:
            from rtde.rtde import RTDE
        except ImportError as exc: raise RuntimeError('缺少 UR 官方 RTDE 客户端，请安装项目依赖。') from exc
        self.conn=RTDE(self.ip,30004)
        try:
            self.conn.connect();self.version=tuple(self.conn.get_controller_version())
            if self.version[0]!=3 or self.version[1] is None or self.version[1]<9: raise ValueError('仅支持 CB3 PolyScope 3.9+；当前版本仅可诊断。')
            fields=dict(BASE_FIELDS)
            if self.version[:3]>=(3,12,3):fields['tcp_offset']='VECTOR6D'
            if not self.conn.send_output_setup(list(fields),list(fields.values()),frequency=125):raise RuntimeError('所需 RTDE 状态字段不可用。')
            if control:
                names=['input_int_register_24','input_int_register_25','input_int_register_26',
                       'standard_digital_output_mask','standard_digital_output','speed_slider_mask','speed_slider_fraction']
                self.inputs=self.conn.send_input_setup(names,['INT32','INT32','INT32','UINT8','UINT8','UINT32','DOUBLE'])
                if self.inputs is None:raise RuntimeError('RTDE 输入字段不可用或已被占用。')
                self.inputs.input_int_register_24=0;self.inputs.input_int_register_25=0;self.inputs.input_int_register_26=0
                self.inputs.standard_digital_output_mask=0;self.inputs.standard_digital_output=0
                self.inputs.speed_slider_mask=0;self.inputs.speed_slider_fraction=.1
            if not self.conn.send_start():raise RuntimeError('RTDE 无法启动。')
            return self.version
        except SystemExit as exc:
            self.close();raise ValueError('控制器版本低于官方客户端支持范围，禁止运动。') from exc
        except BaseException:
            self.close();raise
    def receive(self):
        data=self.conn.receive()
        if data is None:raise ConnectionError('RTDE 已断开。')
        result={k:getattr(data,k) for k in BASE_FIELDS}
        if hasattr(data,'tcp_offset'):result['tcp_offset']=data.tcp_offset
        if not math.isfinite(result['timestamp']):raise ValueError('控制器时间无效。')
        for key in ('actual_q','actual_qd','actual_TCP_pose','actual_TCP_speed'):
            if len(result[key])!=6 or not all(math.isfinite(x) for x in result[key]):raise ValueError('RTDE 位姿或速度无效。')
        return result
    def send(self,heartbeat=None,job=None,stop=False,pin=None,speed=None):
        with self.lock:
            if self.inputs is None:raise RuntimeError('尚未建立控制输入通道。')
            if heartbeat is not None:self.inputs.input_int_register_24=int(heartbeat)
            if job is not None:self.inputs.input_int_register_25=int(job)
            if stop:self.inputs.input_int_register_26=1
            if pin is not None:
                self.inputs.standard_digital_output_mask=1<<pin;self.inputs.standard_digital_output=0
            if speed is not None:
                if not math.isfinite(speed) or not 0<speed<=1:raise ValueError('倍率必须为 (0,1]。')
                self.inputs.speed_slider_mask=1;self.inputs.speed_slider_fraction=speed
            if not self.conn.send(self.inputs):raise ConnectionError('RTDE 输入发送失败。')
    def close(self):
        if self.conn:
            self.conn.disconnect();self.conn=None


def stationary(sample):
    return max(abs(x) for x in sample['actual_qd'])<.002 and max(abs(x) for x in sample['actual_TCP_speed'])<.002


def output_off(sample,pin):return not bool(int(sample['actual_digital_output_bits']) & (1<<pin))
