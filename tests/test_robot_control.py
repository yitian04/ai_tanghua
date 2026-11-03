"""No real sockets or robots: controller feedback drives every transition."""
import copy
import json
import math
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from src.core.models import Trajectory,TrajectoryPoint
from src.core.validation import validate_trajectory
from src.robot.ur5.path_config import new_config,fingerprint,PathStore,validate_config,check_start,record_waypoint
from src.robot.ur5.guarded_script import build_guarded_script
from src.robot.ur5.task_service import TaskService,ProcessLease
from src.robot.ur5.ur5_adapter import UR5RobotAdapter
from src.pipeline.export.urscript_exporter import export_trajectory_urscript,load_controlled_program


def route():
    c=new_config();p={'q':[0.]*6,'tcp':[0.,0.,.01,0.,0.,0.],'timestamp':1.,'mode':'movel'}
    c.update(start=copy.deepcopy(p),prepare=copy.deepcopy(p),enter=[copy.deepcopy(p)],exit=[copy.deepcopy(p)],
             bounds=[-100,100,-100,100,0,100],draw_z_mm=0.,approach_z_mm=10.,tcp_offset=[0.]*6,
             wiring_confirmed=True,registers_confirmed=True)
    from src.robot.ur5.workspace_calibration import calibrated_config
    c['calibration']['prepare']=copy.deepcopy(p)
    pen=copy.deepcopy(p);pen['tcp'][2]=0.;c['calibration']['pen']=pen
    for name,x,y in (('top_left',-.1,-.1),('bottom_left',-.1,.1),('top_right',.1,-.1),('bottom_right',.1,.1)):
        point=copy.deepcopy(p);point['tcp'][:3]=[x,y,0.];c['calibration']['corners'][name]=point
    c['calibration']['lift_mm']=10.
    c=calibrated_config(c);c['validated']=fingerprint(c);return c


def trajectory():return Trajectory([TrajectoryPoint(0,0,0,1,True),TrajectoryPoint(10,10,0,2,True)])


class Clock:
    def __init__(self):self.value=0.
    def __call__(self):return self.value


class Controller:
    def __init__(self,mode='complete'):
        self.mode=mode;self.clock=Clock();self.started=False;self.job=0;self.count=0;self.stop=False;self.service=None;self.sent=[]
    def factory(self,ip):return Channel(self)
    def adapter(self):return Adapter(self)


class Channel:
    def __init__(self,c):self.c=c
    def open(self,control=False):return (3,15,8,0)
    def receive(self):
        c=self.c;c.clock.value+=.02;time.sleep(.001)
        if c.service and c.mode!='browser_loss':c.service.heartbeat('owner')
        if c.started:c.count+=1
        if c.started and c.mode=='disconnect':raise ConnectionError('fake disconnect')
        complete=c.started and c.mode=='complete' and c.count>5
        sample=dict(timestamp=c.clock.value,actual_q=[0.]*6,actual_qd=[0.]*6,actual_TCP_speed=[0.]*6,
                    actual_TCP_pose=[0.,0.,.01,0.,0.,0.],robot_mode=7,safety_mode=1,runtime_state=1,
                    target_speed_fraction=.1,actual_digital_output_bits=0,tcp_offset=[0.]*6,
                    output_int_register_25=0,output_int_register_26=0,output_int_register_27=0)
        if c.started and not c.stop and c.mode!='no_start':
            sample.update(output_int_register_25=c.job if c.mode!='old_job' else c.job-1,
                          output_int_register_26=4 if complete else 1,
                          output_int_register_27=c.job if complete else 0,runtime_state=1 if complete else 2)
            if not complete:sample['actual_qd']=[.01]*6
        return sample
    def send(self,heartbeat=None,job=None,stop=False,pin=None,speed=None):
        if job is not None:
            self.c.job=job;self.c.stop=False;self.c.started=False;self.c.count=0
        if stop:self.c.stop=True
    def close(self):pass


class Adapter:
    def __init__(self,c):self.c=c
    def power_on(self):return True
    def power_off(self):return True
    def brake_release(self):return True
    def check_motion_ready(self):return {'ok':True}
    def _send_script(self,script):
        self.c.sent.append(script)
        if script.startswith('def guarded_job_'):self.c.started=True
        return True
    def stop_program(self):self.c.stop=True;return True


class RobotTests(unittest.TestCase):
    def service(self,directory,mode='complete'):
        c=Controller(mode);s=TaskService(directory,'127.0.0.77',c.factory,c.clock);c.service=s;return s,c
    def wait(self,s):
        s.worker.join(3);self.assertFalse(s.worker.is_alive())
    def test_response_failure_is_not_success(self):
        r=UR5RobotAdapter()
        for response in ('Failed to execute: brake release','Unknown command: brake release','','OK','Brake'):
            with patch.object(r,'_send_dashboard_command',return_value=response):self.assertFalse(r.brake_release())
        with patch.object(r,'_send_dashboard_command',return_value='Brake releasing'):self.assertTrue(r.brake_release())
        with patch.object(r,'_send_dashboard_command') as send:
            self.assertFalse(r.set_speed_fraction(.1)['ok']);send.assert_not_called()
    def test_unknown_or_paused_program_blocked(self):
        r=UR5RobotAdapter()
        for state in ('unknown','PAUSED program.urp','Error','PLAYING'):
            with patch.object(r,'get_robot_info',return_value={'dashboard_ok':True,'robot_mode':'Robotmode: RUNNING','safety_status':'Safetymode: NORMAL','program_state':state}):
                self.assertFalse(r.check_motion_ready()['ok'])
    def test_dashboard_line_reader_preserves_separate_lines(self):
        class Peer:
            def __init__(self):self.data=bytearray(b'Stopped\nRobotmode: RUNNING\n')
            def recv(self,size):
                part=bytes(self.data[:size]);del self.data[:size];return part
        peer=Peer();robot=UR5RobotAdapter()
        self.assertEqual(robot._read_line(peer),'Stopped')
        self.assertEqual(robot._read_line(peer),'Robotmode: RUNNING')
        class Partial:
            def __init__(self):self.data=[b'S',b't',b'o',b'p',b'p',b'e',b'd',b'']
            def recv(self,size):return self.data.pop(0)
        self.assertEqual(robot._read_line(Partial()),'')
    def test_unmonitored_compatibility_entrypoints_cannot_move(self):
        robot=UR5RobotAdapter()
        with patch.object(robot,'_send_script') as send:
            self.assertFalse(robot.execute_trajectory(trajectory()).ok)
            self.assertFalse(robot.execute_script('movej([0,0,0,0,0,0])'))
            self.assertFalse(robot.movej_degrees([0]*6)['ok'])
            send.assert_not_called()
    def test_invalid_execution_options_rejected(self):
        from src.robot.ur5.execution_profile import URScriptExecutionProfile
        for options in ({'max_speed_mm_s':float('nan')},{'output_on_delay_ms':-1},{'acceleration_m_s2':0},{'output_pin':9}):
            with self.assertRaises(ValueError):URScriptExecutionProfile(**options)
    def test_robot_page_renders_without_network_and_requires_route(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as directory:
            code=f"import importlib\nfrom apps.gui.views import robot_page\nimportlib.reload(robot_page)\nrobot_page.render({{}}, {directory!r})"
            with patch('socket.create_connection',side_effect=AssertionError('Rendering must not connect')) as network:
                app=AppTest.from_string(code).run(timeout=20)
                self.assertFalse(app.exception,list(app.exception))
                network.assert_not_called()
                buttons={b.label:b for b in app.button}
                self.assertFalse(buttons['停止并关料'].disabled)
                self.assertTrue(buttons['正式绘制'].disabled)
                self.assertTrue(buttons['关料试运行'].disabled)
    def test_nan_coordinates_and_frame_rejected(self):
        for field in ('x_mm','rx_deg','speed_mm_s'):
            t=trajectory();setattr(t.points[0],field,float('nan'));self.assertTrue(validate_trajectory(t))
        t=trajectory();t.coordinate_frame='image_px';self.assertTrue(validate_trajectory(t))
    def test_script_has_controller_guards_and_taught_return(self):
        c=route();script=build_guarded_script(trajectory(),c,123)
        self.assertIn('set_runstate_standard_digital_output_to_value(0, 1)',script)
        self.assertIn('waiting_cycles >= 250',script)
        self.assertIn('stale_cycles >= 250',script)
        self.assertIn('read_input_integer_register(26) != 0',script)
        self.assertLess(script.index('get_tcp_offset()'),script.index('local motion = run'))
        self.assertIn('write_output_integer_register(27, 123)',script)
        self.assertNotIn('45.000000',script)
        dry=build_guarded_script(trajectory(),c,124,dry_run=True)
        self.assertNotIn(', True)',dry)
    def test_unvalidated_route_never_builds_live_script(self):
        c=route();c['output_pin']=1
        with self.assertRaises(ValueError):build_guarded_script(trajectory(),c,5)
        self.assertIn('set_standard_digital_out(1, False)',build_guarded_script(trajectory(),c,5,dry_run=True))
    def test_config_change_revokes_validation_and_wiring(self):
        with tempfile.TemporaryDirectory() as directory:
            store=PathStore(directory,'127.0.0.77');c=route();store.save(c)
            c['approach_z_mm']=15;updated=store.save(c);self.assertIsNone(updated['validated'])
            c=route();c['output_pin']=2;updated=store.save(c);self.assertFalse(updated['wiring_confirmed'])
    def test_wrong_start_and_moving_record_rejected(self):
        c=route();controller=Controller();sample=controller.factory('').receive();sample['actual_q'][0]=1
        with self.assertRaises(ValueError):check_start(c,sample)
        sample['actual_qd'][0]=1
        with self.assertRaises(ValueError):record_waypoint(sample)
    def test_real_completion_requires_matching_marker_and_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            s,c=self.service(directory);s.submit(c.adapter(),trajectory(),route(),{},'owner');self.wait(s)
            self.assertEqual(s.snapshot()['state'],'completed');self.assertIsNone(s.lease)
            self.assertEqual(sum(x.startswith('def guarded_job_') for x in c.sent),1)
    def test_send_is_not_completion_and_stop_remains_available(self):
        with tempfile.TemporaryDirectory() as directory:
            s,c=self.service(directory,'running');s.submit(c.adapter(),trajectory(),route(),{},'owner')
            end=time.monotonic()+1
            while s.snapshot()['state']!='running' and time.monotonic()<end:time.sleep(.005)
            self.assertEqual(s.snapshot()['state'],'running')
            with self.assertRaises(RuntimeError):s.submit(c.adapter(),trajectory(),route(),{},'another')
            s.request_stop();self.wait(s);self.assertEqual(s.snapshot()['state'],'stopped')
            self.assertTrue(any(x.startswith('sec close_material') for x in c.sent))
    def test_browser_loss_stops_no_automatic_return(self):
        with tempfile.TemporaryDirectory() as directory:
            s,c=self.service(directory,'browser_loss');s.submit(c.adapter(),trajectory(),route(),{},'owner');self.wait(s)
            self.assertEqual(s.snapshot()['state'],'stopped')
            self.assertIn('网页',s.snapshot()['message'] if s.snapshot()['state']=='unknown' else '网页')
            self.assertEqual(sum(x.startswith('def guarded_job_') for x in c.sent),1)
    def test_old_marker_and_start_timeout_retain_lock(self):
        for mode in ('old_job','no_start','disconnect'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                s,c=self.service(directory,mode);s.submit(c.adapter(),trajectory(),route(),{},'owner');self.wait(s)
                self.assertEqual(s.snapshot()['state'],'unknown');self.assertIsNotNone(s.lease)
                # Fresh read-only feedback is required to release ownership.
                c.mode='complete';c.stop=True;s.reconcile(c.adapter(),0)
                self.assertEqual(s.snapshot()['state'],'stopped');self.assertIsNone(s.lease)
    def test_restart_retains_unknown_not_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            s,c=self.service(directory);s._set('running','old',job=55,motion_send_attempted=True)
            fresh,_=self.service(directory)
            self.assertEqual(fresh.snapshot()['state'],'unknown');self.assertFalse(c.sent)
    def test_stop_can_be_retried_without_replaying_motion(self):
        with tempfile.TemporaryDirectory() as directory:
            s,c=self.service(directory);s.adapter=c.adapter()
            try:
                s.request_stop();s.stop_worker.join(1)
                s.request_stop();s.stop_worker.join(1)
                self.assertEqual(len(c.sent),2)
                self.assertTrue(all(script.startswith('sec close_material') for script in c.sent))
            finally:
                if s.lease:s.lease.close();s.lease=None
    def test_process_lock_prevents_second_controller(self):
        lease=ProcessLease('127.0.0.78')
        try:
            with self.assertRaises(RuntimeError):ProcessLease('127.0.0.78')
        finally:lease.close()
    def test_urp_roundtrip_requires_validated_route(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'job.urp'
            with self.assertRaises(ValueError):export_trajectory_urscript(trajectory(),path)
            self.assertFalse(path.exists())
            export_trajectory_urscript(trajectory(),path,path_config=route())
            t,c,opts=load_controlled_program(path)
            self.assertEqual(t.to_dict(),trajectory().to_dict());self.assertEqual(fingerprint(c),fingerprint(route()))
            self.assertIn('cachedContents',path.read_text(encoding='utf-8'))


if __name__=='__main__':unittest.main()
