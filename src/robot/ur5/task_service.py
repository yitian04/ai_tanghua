"""Single-process task ownership, independent stop and controller feedback.

No Streamlit calls, connections or movements occur at import/construction time.
"""
from __future__ import annotations
import copy
import ipaddress
import json
import os
from pathlib import Path
import secrets
import tempfile
from threading import RLock,Thread,Event
import time

from .rtde_channel import RTDEChannel,stationary,output_off
from .path_config import validate_config,check_start,check_trajectory,fingerprint
from .guarded_script import build_guarded_script

ACTIVE={'checking','sending','waiting','running','stopping','unknown'}
LABELS={'checking':'检查中','sending':'发送中','waiting':'等待启动','running':'运行中',
        'stopping':'停止中','completed':'已完成','stopped':'已停止','failed':'失败','unknown':'结果未知','idle':'未运行'}


class ProcessLease:
    """OS lock shared by app instances, including instances using another root."""
    def __init__(self,ip):
        folder=Path(tempfile.gettempdir())/'tanghua_robot_locks';folder.mkdir(exist_ok=True)
        self.file=(folder/(ip.replace(':','_')+'.lock')).open('a+b')
        self.file.seek(0);self.file.write(b'0');self.file.flush();self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close();raise RuntimeError('另一控制服务进程已占用这台机器人。')
    def close(self):
        if self.file:
            self.file.close();self.file=None


class TaskService:
    def __init__(self,root,ip,channel_factory=RTDEChannel,clock=time.monotonic):
        self.root=Path(root);self.ip=str(ipaddress.ip_address(ip));self.factory=channel_factory;self.clock=clock
        self.lock=RLock();self.channel=None;self.lease=None;self.cancel=Event();self.adapter=None;self.worker=None;self.stop_worker=None
        self.last_browser=0.;self.owner=None;self.observation=None;self.last_controller=None
        self.path=self.root/'data'/'.robot_state'/(self.ip.replace(':','_')+'.json')
        self.value={'state':'idle','message':'未提交任务','job':None,'motion_send_attempted':False}
        if self.path.exists():
            try:
                old=json.loads(self.path.read_text(encoding='utf-8'))
                if old.get('state') in ACTIVE:
                    never_sent=old.get('motion_send_attempted') is False or ('motion_send_attempted' not in old and old.get('job') is None)
                    self.value={**old,'state':'idle' if never_sent else 'unknown','message':'未发送过运动，可清除离线停止提示。' if never_sent else '上次控制服务退出时任务未确认结束；请只核对状态，禁止重发。'}
                    if never_sent:
                        self.value.update(motion_send_attempted=False,stop_errors=[],stop_notice='旧的离线停止记录：未发送过运动，可清除此提示；未确认设备状态。')
                else:self.value=old
            except (ValueError,OSError):self.value={'state':'unknown','message':'任务记录无法读取，请核对设备状态。','job':None}
    def _set(self,state,message,**extra):
        with self.lock:
            self.value.update(state=state,message=message,**extra)
            self.path.parent.mkdir(parents=True,exist_ok=True)
            temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(self.value,ensure_ascii=False,allow_nan=False),encoding='utf-8');temp.replace(self.path)
    def snapshot(self):
        with self.lock:
            if self.value['state'] not in ACTIVE and self.lease and not (self.worker and self.worker.is_alive()) and not (self.stop_worker and self.stop_worker.is_alive()):
                self.lease.close();self.lease=None
            return copy.deepcopy(self.value)
    def heartbeat(self,owner):
        with self.lock:
            if owner==self.owner:self.last_browser=self.clock()
    def submit(self,adapter,trajectory,config,options,owner,dry_run=False,prepare_only=False):
        config=copy.deepcopy(config);trajectory=copy.deepcopy(trajectory)
        validate_config(config,verified=not dry_run)
        if not prepare_only:check_trajectory(config,trajectory)
        with self.lock:
            if self.value['state'] in ACTIVE:raise RuntimeError('当前任务尚未结束或状态未知。')
            if self.worker and self.worker.is_alive():raise RuntimeError('上一任务正在清理通信通道。')
            if self.stop_worker and self.stop_worker.is_alive():raise RuntimeError('上一停止请求仍在处理。')
            if self.lease is None:self.lease=ProcessLease(self.ip)
            self.cancel=Event();self.owner=owner;self.last_browser=self.clock()
            self.adapter=adapter;self.config=config
            self._set('checking','核对控制器、路径和输出状态',job=secrets.randbelow(2147483645)+1,
                      route=fingerprint(config),dry_run=dry_run,prepare_only=prepare_only,output_pin=config['output_pin'],stop_errors=[],stop_notice='',motion_send_attempted=False)
            self.worker=Thread(target=self._run,args=(trajectory,config,dict(options),dry_run,prepare_only),daemon=True,name='ur5-task-'+self.ip)
            self.worker.start()
            return self.snapshot()
    def _cancelled(self):
        if self.cancel.is_set():raise InterruptedError('任务已请求停止。')
        if self.clock()-self.last_browser>3:raise InterruptedError('网页在线报告超时。')
    def _run(self,trajectory,c,options,dry_run,prepare_only):
        sent=False
        try:
            channel=self.factory(self.ip);self.channel=channel
            version=channel.open(control=True)
            ready=self.adapter.check_motion_ready()
            if not ready.get('ok'):raise ValueError(ready.get('message','设备未就绪'))
            self._cancelled()
            sample=channel.receive();check_start(c,sample)
            if not stationary(sample) or sample['runtime_state']!=1 or sample['robot_mode']!=7 or sample['safety_mode']!=1:raise ValueError('机器人未停稳、程序未停止或安全模式非 NORMAL。')
            if sample.get('tcp_offset') and any(abs(a-b)>1e-4 for a,b in zip(sample['tcp_offset'],c['tcp_offset'])):raise ValueError('TCP 偏移与路径配置不同。')
            job=self.value['job'];channel.send(heartbeat=1,job=job,pin=c['output_pin'],speed=.1)
            deadline=self.clock()+2
            while True:
                self._cancelled();sample=channel.receive()
                if output_off(sample,c['output_pin']) and abs(sample['target_speed_fraction']-.1)<.005:break
                if self.clock()>deadline:raise ValueError('无法确认关料和 10% 速度倍率，未发送运动程序。')
            script=build_guarded_script(trajectory,c,job,options,dry_run,prepare_only)
            self._cancelled();self._set('sending','正在发送；尚未确认机器人启动',motion_send_attempted=True)
            # Once send is attempted, partial delivery is possible: any error
            # must retain an unknown/stopping state rather than release ownership.
            sent=True
            if not self.adapter._send_script(script):raise ConnectionError('脚本发送失败，是否部分送达未知。')
            self._set('waiting','脚本已发送，等待当前任务启动确认')
            started=self.clock();last_hb=0.;counter=1;stable=0;last_timestamp=sample['timestamp'];last_new=self.clock()
            while True:
                now=self.clock()
                if now-self.last_browser>3 and not self.cancel.is_set():self.request_stop('网页关闭或失联')
                if now-last_hb>=.25:
                    counter=(counter+1)%2147483647;channel.send(heartbeat=counter,stop=self.cancel.is_set(),pin=c['output_pin'] if self.cancel.is_set() else None);last_hb=now
                sample=channel.receive();now=self.clock()
                if sample['timestamp']>last_timestamp:last_new=now;last_timestamp=sample['timestamp']
                elif now-last_new>1:raise ConnectionError('控制器状态时间未更新。')
                self.observation=sample
                ours=sample['output_int_register_25']==job
                phase=sample['output_int_register_26'] if ours else None
                stopped=stationary(sample) and output_off(sample,c['output_pin']) and sample['runtime_state']==1
                stable=stable+1 if stopped else 0
                if self.cancel.is_set():
                    if stable>=3:self._set('stopped','已确认停稳及关料；重新运行需重新确认路径');return
                    if now-self.stop_time>5:raise RuntimeError('停止未得到反馈确认，请使用实体停止装置。')
                    continue
                if ours and phase==1 and self.value['state']=='waiting':self._set('running','已收到当前任务运行标记')
                if ours and phase==4 and sample['output_int_register_27']==job and stable>=3:
                    self._set('completed','已确认当前任务完成、停稳及关料',finished_at=time.time());return
                if ours and phase==-1:raise RuntimeError('控制器预检或心跳保护终止了任务。')
                if sample['safety_mode']!=1:raise RuntimeError('机器人进入非 NORMAL 安全模式。')
                if self.value['state']=='waiting' and now-started>5:raise TimeoutError('未收到当前任务启动标记，禁止重发。')
                if self.value['state']=='running' and stable>=3:raise RuntimeError('任务停止但没有当前任务完成标记。')
        except Exception as exc:
            if sent:
                self.request_stop(str(exc));self._set('unknown',str(exc)+'；结果未知，禁止启动新任务。')
            elif self.cancel.is_set():self._set('idle','启动前已取消，未发送运动。',motion_send_attempted=False)
            else:self._set('failed',str(exc))
        finally:
            if self.channel:
                try:self.channel.close()
                except Exception:pass
                self.channel=None
            if self.value['state'] not in ACTIVE and self.lease and not (self.stop_worker and self.stop_worker.is_alive()):self.lease.close();self.lease=None
    def clear_stop_notice(self):
        with self.lock:
            if self.value['state'] in ACTIVE or (self.worker and self.worker.is_alive()) or (self.stop_worker and self.stop_worker.is_alive()):
                raise ValueError('任务仍在处理或结果未知，不能清除运动锁。')
            self._set(self.value['state'],self.value['message'],stop_notice='',stop_errors=[])
    def request_stop(self,reason='操作者请求停止'):
        with self.lock:
            if self.stop_worker and self.stop_worker.is_alive():return
            self.cancel.set();self.stop_time=self.clock()
            worker_alive=bool(self.worker and self.worker.is_alive())
            uncertain=self.value['state'] in ACTIVE and self.value.get('motion_send_attempted') is not False
            track=worker_alive or uncertain
            if track and self.lease is None:
                try:self.lease=ProcessLease(self.ip)
                except RuntimeError:pass
            if track:self._set('stopping',reason+'；正在核对关料与停稳')
            else:
                self._set('idle','本应用未运行运动任务。',stop_notice='正在尝试发送停止请求，未确认设备状态。',stop_errors=[])
                if self.lease:self.lease.close();self.lease=None
            pin=getattr(self,'config',{}).get('output_pin',self.value.get('output_pin',0))
            self.stop_worker=Thread(target=self._stop_io,args=(self.channel,self.adapter,pin,track),daemon=True,name='ur5-stop-'+self.ip)
            self.stop_worker.start()
    def _stop_io(self,channel,adapter,pin,track):
        errors=[]
        try:
            if channel:channel.send(stop=True,pin=pin)
        except Exception as exc:errors.append(str(exc))
        if adapter:
            if not adapter._send_script(f'sec close_material():\n  set_standard_digital_out({pin}, False)\nend'):
                errors.append('关料请求未送达')
            if not adapter.stop_program():errors.append('停止命令未确认')
        else:errors.append('未连接设备')
        with self.lock:
            if track:
                if errors:self._set(self.value['state'],self.value['message'],stop_errors=errors)
                if not (self.worker and self.worker.is_alive()):
                    self._set('unknown','停止请求尚未得到设备反馈确认，请连接后核对停稳与关料。',stop_errors=errors)
            else:
                notice='未连接，停止请求未确认。' if errors else '停止请求已发送；没有运行中的应用任务，未核对设备状态。'
                self._set('idle','本应用未运行运动任务。',stop_notice=notice,stop_errors=[])
    def reconcile(self,adapter,pin):
        """Read-only inspection; never re-send a motion or re-arm heartbeats."""
        with self.lock:
            if self.value['state'] not in {'unknown','stopping'}:raise ValueError('只可核对未知/停止中的任务。')
            if self.worker and self.worker.is_alive():raise ValueError('后台仍在监测停止，请稍后核对。')
        channel=self.factory(self.ip)
        try:
            channel.open(control=False);samples=[channel.receive() for _ in range(3)]
            if not all(a['timestamp']<b['timestamp'] for a,b in zip(samples,samples[1:])):raise ValueError('控制器时间未更新，不能解除运动锁。')
            if not all(stationary(s) and output_off(s,pin) and s['runtime_state']==1 for s in samples):raise ValueError('尚未确认停稳、程序停止和关料。')
            self._set('stopped','只读核对已确认停稳及关料；原任务不恢复')
            if self.lease:self.lease.close();self.lease=None
        finally:channel.close()


_SERVICES={};_LOCK=RLock()
def get_service(root,ip):
    ip=str(ipaddress.ip_address(ip))
    with _LOCK:
        key=(str(Path(root).resolve()),ip)
        if key not in _SERVICES:_SERVICES[key]=TaskService(root,ip)
        return _SERVICES[key]
