import unittest
import cv2
import numpy as np
from src.pipeline.vectorization.centerline import thin, trace, regularize, refine_network, join_continuations
from src.modules.image_process_module import vectorize_image_to_curve_list


class CenterlineQualityTests(unittest.TestCase):
    def test_shared_wall_nodes_snap_to_one_straight_run(self):
        paths=[[[0.,10.],[10.,10.4],[20.,11.]],[[20.,11.],[30.,10.5],[40.,10.]],
               [[20.,11.],[20.2,20.],[20.,40.]]]
        result=refine_network(paths)
        self.assertEqual(result[0][-1],result[1][0])
        self.assertEqual(result[0][-1],result[2][0])
        self.assertEqual(result[0][0][1],result[1][-1][1])
        self.assertEqual(result[0][0][1],result[0][-1][1])
        merged=join_continuations(result)
        self.assertEqual(len(merged),2)
        self.assertEqual(sum(len(p)-1 for p in merged),3)

    def test_continuation_never_bridges_separate_endpoints(self):
        paths=[[[0.,0.],[20.,0.]],[[21.,0.],[40.,0.]]]
        self.assertEqual(len(join_continuations(paths)),2)

    def test_thinning_preserves_cropped_boundary_and_holes(self):
        mask=np.zeros((80,100),np.uint8)
        cv2.rectangle(mask,(0,0),(99,79),1,7)
        sk=thin(mask)
        self.assertEqual(cv2.connectedComponents(sk.astype('uint8'))[0],2)
        self.assertGreater(sk.sum(),250)
        self.assertFalse(sk[40,50])

    def test_all_lattice_edges_survive_default_filtering(self):
        image=np.full((180,240,3),255,np.uint8)
        for x in range(20,221,20):cv2.line(image,(x,20),(x,160),(0,0,0),7)
        for y in (20,75,83,160):cv2.line(image,(20,y),(220,y),(0,0,0),7)
        curves=vectorize_image_to_curve_list(image)
        raster=np.zeros(image.shape[:2],np.uint8)
        for c in curves.curves:cv2.polylines(raster,[np.rint(c.points).astype('int32')],c.closed,255,1)
        sk=thin(image[:,:,0]<128)
        dist=cv2.distanceTransform(255-raster,cv2.DIST_L2,5)
        self.assertGreater((dist[sk]<=2).mean(),.995)
        self.assertEqual(cv2.connectedComponents(raster)[0],2)

    def test_separate_loops_stay_separate(self):
        mask=np.zeros((100,180),np.uint8)
        cv2.circle(mask,(45,50),25,1,7);cv2.circle(mask,(115,50),25,1,7)
        paths=trace(thin(mask))
        self.assertEqual(len(paths),2)
        self.assertTrue(all(p[0]==p[-1] for p in paths))

    def test_regularization_straightens_and_fixes_junctions(self):
        straight=[[float(i),20.+.2*(i%2)] for i in range(40)]
        self.assertEqual(regularize(straight),[straight[0],straight[-1]])
        arc=[[50+30*np.cos(t),50+30*np.sin(t)] for t in np.linspace(0,np.pi,80)]
        smooth=regularize(arc)
        np.testing.assert_allclose(smooth[0],arc[0],atol=1e-5)
        np.testing.assert_allclose(smooth[-1],arc[-1],atol=1e-5)
        self.assertLess(max(abs(np.linalg.norm(np.array(p)-50)-30) for p in smooth),1)
