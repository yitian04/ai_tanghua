import copy
import math
import unittest

from src.core.models import Trajectory, TrajectoryPoint as P
from src.core.trajectory_playback import build_playback


class PlaybackTimelineTests(unittest.TestCase):
    def test_target_speed_3d_motion_and_immutable_source(self):
        trajectory=Trajectory([P(0,0,10,99,False,point_id=80),P(0,0,0,5,False,point_id=2),P(0,0,0,10,True),P(30,40,0,25,True)])
        original=copy.deepcopy(trajectory.to_dict())
        data=build_playback(trajectory)
        self.assertEqual(data['times'],[0,2,2,4])
        self.assertEqual(data['strokes'],[{'start':2,'end':3,'number':1}])
        self.assertEqual(data['point_strokes'],[1,1,1,1])
        self.assertEqual(data['duration_s'],4)
        self.assertEqual(trajectory.to_dict(),original)
        trajectory.points[-1].speed_mm_s=50
        self.assertNotEqual(data['fingerprint'],build_playback(trajectory)['fingerprint'])

    def test_repeated_ids_single_points_and_real_cross_stroke_commands(self):
        trajectory=Trajectory([P(0,0,0,1,True,curve_id=7),P(1,0,0,1,True,curve_id=9),P(2,0,0,1,False),P(3,0,0,1,True,curve_id=7)])
        data=build_playback(trajectory)
        self.assertEqual([s['start'] for s in data['strokes']],[0,1,3])
        self.assertEqual([s['number'] for s in data['strokes']],[1,2,3])
        self.assertEqual(data['point_strokes'],[1,2,3,3])
        self.assertIn('1 处跨笔移动未收料',data['warning'])
        self.assertTrue(data['points'][1][3])

    def test_all_coincident_and_travel_bounds(self):
        data=build_playback(Trajectory([P(4,5,6,10,False),P(4,5,6,10,True),P(4,5,6,10,False),P(4,5,6,10,True)]))
        self.assertEqual(data['duration_s'],0)
        self.assertEqual(data['times'],[0,0,0,0])
        self.assertEqual([s['start'] for s in data['strokes']],[1,3])
        trajectory=Trajectory([P(-100,-200,50,10,False),P(0,0,0,10,True)])
        self.assertEqual(build_playback(trajectory)['bounds'],[-100,-200,0,0])
        self.assertEqual(len(build_playback(Trajectory([P(0,0,0,10,True)]))['strokes']),1)

    def test_invalid_data(self):
        examples=[Trajectory([]),Trajectory([P(0,0,0,1,False)]),Trajectory([P(math.nan,0,0,1,True)]),Trajectory([P(0,0,0,0,True)]),Trajectory([P(0,0,0,-1,True)]),Trajectory([P(0,0,0,1,'False')]),Trajectory([P(0,0,0,1,True)],coordinate_frame='image_px'),Trajectory([P(0,0,0,1,True),P(1e308,0,0,1e-308,True)])]
        for trajectory in examples:
            with self.subTest(trajectory=trajectory):
                with self.assertRaises(ValueError):build_playback(trajectory)


if __name__=='__main__':unittest.main()
