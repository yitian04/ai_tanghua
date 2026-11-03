import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_robot_control import route,trajectory,Controller
from src.core.preferences import PreferenceStore
from src.robot.ur5.path_config import PathStore,validate_config,fingerprint
from src.robot.ur5.workspace_calibration import derive_workspace,calibrated_config,save_planning_defaults
from src.robot.ur5.guarded_script import build_guarded_script
from src.robot.ur5.task_service import TaskService


class CalibrationTests(unittest.TestCase):
    def test_geometry_and_units(self):
        raw=route()['calibration'];raw['pen']['tcp'][3:]=[0,math.pi,0]
        g=derive_workspace(raw)
        self.assertEqual((g['width_mm'],g['height_mm'],g['draw_z_mm'],g['approach_z_mm']),(200.,200.,0.,10.))
        self.assertAlmostEqual(g['orientation_deg'][1],180)
        self.assertEqual(raw['pen']['tcp'][4],math.pi)
    def test_missing_points_name_the_problem(self):
        for key in ('prepare','pen'):
            raw=route()['calibration'];raw[key]=None
            with self.assertRaisesRegex(ValueError,'尚未记录'):derive_workspace(raw)
        raw=route()['calibration'];raw['corners'].pop('top_left')
        with self.assertRaisesRegex(ValueError,'左上角'):derive_workspace(raw)
    def test_invalid_corners_not_silently_enclosed(self):
        for kind in ('duplicate','swapped','tilted','rotated','quadrilateral','nan'):
            with self.subTest(kind=kind):
                raw=route()['calibration'];corners=raw['corners']
                if kind=='duplicate':corners['top_right']=copy.deepcopy(corners['top_left'])
                if kind=='swapped':corners['top_left'],corners['bottom_left']=corners['bottom_left'],corners['top_left']
                if kind=='tilted':corners['bottom_right']['tcp'][2]=.002
                if kind=='rotated':
                    theta=math.radians(5)
                    for p in corners.values():
                        x,y=p['tcp'][:2];p['tcp'][:2]=[x*math.cos(theta)-y*math.sin(theta),x*math.sin(theta)+y*math.cos(theta)]
                if kind=='quadrilateral':corners['bottom_right']['tcp'][0]+=.005
                if kind=='nan':corners['top_left']['tcp'][0]=float('nan')
                with self.assertRaises(ValueError):derive_workspace(raw)
    def test_negative_lift_rejected(self):
        for value in (0,-1,float('inf'),True):
            raw=route()['calibration'];raw['lift_mm']=value
            with self.assertRaises(ValueError):derive_workspace(raw)
    def test_optional_detours_and_clearance_anchor(self):
        c=route();c['enter']=[];c['exit']=[];c['validated']=fingerprint(c)
        validate_config(c)
        script=build_guarded_script(trajectory(),c,123)
        self.assertIn('0.010000000',script)
        self.assertNotIn(', True)',build_guarded_script(trajectory(),c,123,dry_run=True))
        # Only the normal completion branch contains the return route; watchdog
        # abort kills motion and does not insert retreat movements.
        abort=script[script.index('    if stale_cycles'):]
        self.assertIn('stopj(1.0)',abort);self.assertNotIn('movel(',abort)
    def test_planning_defaults_patch_is_selective_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            store=PreferenceStore(directory)
            store.remember('planning',{'绘制速度 mm/s':33.,'旋转角 deg':20.})
            t=trajectory();before=t.to_dict();values=save_planning_defaults(directory,route())
            fresh=PreferenceStore(directory)
            self.assertEqual(fresh.current('planning')['工作区宽 mm'],200.)
            self.assertEqual(fresh.current('planning')['绘制速度 mm/s'],33.)
            self.assertEqual(fresh.current('planning')['旋转角 deg'],20.)
            self.assertEqual(fresh.values('planning','defaults')['绘制 Z mm'],0.)
            self.assertNotIn('output_pin',values);self.assertEqual(t.to_dict(),before)
    def test_legacy_route_migration_keeps_original_and_revokes_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            store=PathStore(directory,'127.0.0.80');old=route()
            for key in ('schema_version','calibration','workspace'):old.pop(key)
            store.path.parent.mkdir(parents=True);store.path.write_text(json.dumps(old),encoding='utf-8')
            migrated=store.load()
            self.assertEqual(migrated['legacy_route'],old)
            self.assertEqual(migrated['calibration']['prepare'],old['prepare'])
            self.assertIsNone(migrated['validated'])
            with self.assertRaisesRegex(ValueError,'落笔'):validate_config(migrated)
            self.assertEqual(json.loads(store.path.read_text()),old)
    def test_saved_geometry_change_revokes_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            store=PathStore(directory,'127.0.0.80');c=route();store.save(c)
            c['calibration']['lift_mm']=20
            changed=store.save(calibrated_config(c))
            self.assertIsNone(changed['validated']);self.assertIsNone(changed['dry_run'])


class OfflineStopTests(unittest.TestCase):
    def test_idle_stop_without_device_does_not_lock_or_connect(self):
        with tempfile.TemporaryDirectory() as directory:
            service=TaskService(directory,'127.0.0.81')
            with patch('socket.create_connection',side_effect=AssertionError('not connected')) as connection:
                service.request_stop();service.stop_worker.join(1)
                connection.assert_not_called()
            value=service.snapshot();self.assertEqual(value['state'],'idle')
            self.assertIn('未连接',value['stop_notice']);self.assertIsNone(service.lease)
            service.clear_stop_notice();self.assertFalse(service.snapshot()['stop_notice'])
    def test_offline_stop_failure_retains_idle_and_can_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            service=TaskService(directory,'127.0.0.81');controller=Controller();adapter=controller.adapter()
            adapter._send_script=lambda script:False;adapter.stop_program=lambda:False
            service.adapter=adapter;service.request_stop();service.stop_worker.join(1)
            self.assertEqual(service.snapshot()['state'],'idle');service.clear_stop_notice()
    def test_old_empty_stop_is_recoverable_but_uncertain_task_is_not(self):
        for job in (None,42):
            with self.subTest(job=job),tempfile.TemporaryDirectory() as directory:
                service=TaskService(directory,'127.0.0.81')
                service.path.parent.mkdir(parents=True);service.path.write_text(json.dumps({'state':'stopping','job':job,'message':'old'}))
                fresh=TaskService(directory,'127.0.0.81')
                self.assertEqual(fresh.snapshot()['state'],'idle' if job is None else 'unknown')
                if job is None:fresh.clear_stop_notice()
                else:
                    with self.assertRaises(ValueError):fresh.clear_stop_notice()
    def test_send_attempt_is_persisted_before_socket_sender(self):
        with tempfile.TemporaryDirectory() as directory:
            controller=Controller('complete')
            service=TaskService(directory,'127.0.0.81',controller.factory,controller.clock)
            controller.service=service;adapter=controller.adapter();original=adapter._send_script
            observed=[]
            def send(script):
                if script.startswith('def guarded_job_'):
                    observed.append(json.loads(service.path.read_text(encoding='utf-8'))['motion_send_attempted'])
                return original(script)
            adapter._send_script=send
            service.submit(adapter,trajectory(),route(),{},'owner');service.worker.join(3)
            self.assertEqual(observed,[True]);self.assertEqual(service.snapshot()['state'],'completed')
    def test_persisted_send_attempt_stays_unknown_and_stop_cannot_clear_it(self):
        with tempfile.TemporaryDirectory() as directory:
            service=TaskService(directory,'127.0.0.81');service._set('sending','attempt',job=9,motion_send_attempted=True)
            fresh=TaskService(directory,'127.0.0.81');self.assertEqual(fresh.snapshot()['state'],'unknown')
            fresh.request_stop();fresh.stop_worker.join(1)
            self.assertEqual(fresh.snapshot()['state'],'unknown')
            with self.assertRaises(ValueError):fresh.clear_stop_notice()
            if fresh.lease:fresh.lease.close()


if __name__=='__main__':unittest.main()
