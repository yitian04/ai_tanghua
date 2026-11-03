from __future__ import annotations

import json
import math
import unittest
from unittest.mock import patch
from pathlib import Path

from src.core.models import Curve2D, CurveList, Trajectory, TrajectoryPoint
from src.pipeline.planning.planner import PlanningConfig, TrajectoryPlanner
from src.pipeline.text_trajectory import TextLayout, generate_text_curves, generate_text_trajectory
from src.pipeline.trajectory_composition.composer import (
    Composition, Plane, compose, drawing_runs, import_trajectory, make_item, transformed_runs,
)

ROOT = Path(__file__).resolve().parents[1]


def source():
    return Trajectory(points=[
        TrajectoryPoint(10, 20, 40, 100, False, curve_id=0),
        TrajectoryPoint(10, 20, 30, 12, True, curve_id=0),
        TrajectoryPoint(20, 20, 30, 13, True, curve_id=0),
        TrajectoryPoint(20, 20, 40, 100, False, curve_id=0),
        TrajectoryPoint(20, 30, 30, 14, True, curve_id=1),
        TrajectoryPoint(10, 30, 30, 15, True, curve_id=1),
    ])


class TextTests(unittest.TestCase):
    def test_chinese_without_ascii_dependency(self):
        with patch.dict("sys.modules", {"HersheyFonts": None}):
            self.assertTrue(generate_text_curves("生日快乐", ROOT).curves)
            with self.assertRaisesRegex(ValueError, "pip install Hershey-Fonts==2.1.0"):
                generate_text_curves("小林22岁", ROOT)

    def test_fixed_em_and_order(self):
        c = generate_text_curves("生日快乐", ROOT, TextLayout(20,2,5))
        self.assertEqual(c.metadata["layout_width_mm"],86)
        data=json.loads((ROOT/"node_modules/hanzi-writer-data/生.json").read_text())
        p=data["medians"][0][0]
        self.assertEqual(c.curves[0].points[0], [p[0]/1024*20,(900-p[1])/1024*20])
        t=generate_text_trajectory(c,PlanningConfig(center_x_mm=100, center_y_mm=200,step_mm=.5))
        self.assertEqual(t.metadata["optimizer"],"disabled")
        self.assertEqual([r[0].curve_id for r in drawing_runs(t)],list(range(len(c.curves))))
        first=drawing_runs(t)[0][0]
        self.assertAlmostEqual(first.x_mm,c.curves[0].points[0][0]+100-43)
        self.assertFalse(t.points[0].drawing)
        self.assertFalse(t.points[1].drawing)

    def test_mixed_multiline_and_missing(self):
        for text in ("小林22岁","Happy Birthday","生日快乐\nLin 22!", "一 一"):
            c=generate_text_curves(text,ROOT)
            self.assertTrue(c.curves)
            self.assertTrue(all(math.isfinite(v) for curve in c.curves for p in curve.points for v in p))
        c=generate_text_curves("A\nA",ROOT)
        runs=[curve for curve in c.curves if curve.curve_id in (0,3)]
        self.assertAlmostEqual(runs[1].points[0][1]-runs[0].points[0][1],25)
        self.assertAlmostEqual(c.curves[0].points[0][1],2.5)
        for text in ("", "   ", "你好！", "🙂"):
            with self.assertRaises(ValueError): generate_text_curves(text,ROOT)

    def test_preserve_mm_is_opt_in(self):
        c=CurveList([Curve2D([[0,0],[10,0]],curve_id=4)])
        t=TrajectoryPlanner(PlanningConfig(coordinate_mode="preserve_mm",center_x_mm=5,center_y_mm=7,optimize_curve_order=False)).plan(c)
        self.assertEqual((drawing_runs(t)[0][0].x_mm,drawing_runs(t)[0][-1].x_mm),(5,15))
        legacy=TrajectoryPlanner(PlanningConfig()).plan(c)
        # The legacy fitter's zero-height handling is intentionally unchanged.
        self.assertAlmostEqual(drawing_runs(legacy)[0][-1].x_mm-drawing_runs(legacy)[0][0].x_mm,9)


class CompositionTests(unittest.TestCase):
    def test_transform_and_reopen(self):
        doc=Composition(Plane(width_mm=100,height_mm=100,center_x_mm=200,center_y_mm=300,draw_z_mm=60,lift_mm=8))
        item=make_item(source(),"图形",doc.plane)
        item.x_mm,item.y_mm,item.scale,item.rotation_deg=30,40,2,90
        doc.items.append(item)
        runs=transformed_runs(item)
        self.assertAlmostEqual(runs[0][0][0],40)
        self.assertAlmostEqual(runs[0][0][1],30)
        doc.items.append(make_item(source(),"同一文件再导入",doc.plane))
        restored=Composition.from_dict(json.loads(json.dumps(doc.to_dict())))
        t=compose(restored)
        groups=drawing_runs(t)
        self.assertEqual(len(groups),4)
        self.assertEqual([p.speed_mm_s for p in groups[0]],[12,13])
        self.assertAlmostEqual(groups[0][0].x_mm,190)
        self.assertAlmostEqual(groups[0][0].y_mm,280)
        self.assertTrue(all(p.z_mm==60 for p in t.points if p.drawing))
        self.assertTrue(all(p.z_mm in (60,68) for p in t.points))
        self.assertEqual([p.point_id for p in t.points],list(range(len(t.points))))
        boundary=t.metadata["objects"][1]["point_start"]
        self.assertFalse(t.points[boundary-1].drawing)
        self.assertFalse(t.points[boundary].drawing)
        self.assertFalse(t.points[boundary+1].drawing)
        self.assertEqual(source().points[1].x_mm,10)

    def test_import_and_reject(self):
        content=json.dumps(source().to_dict()).encode()
        self.assertEqual(len(import_trajectory(content,"a.json").points),6)
        import csv,io
        buf=io.StringIO(); writer=csv.DictWriter(buf,fieldnames=list(source().points[0].to_dict()))
        writer.writeheader();writer.writerows(p.to_dict() for p in source().points)
        self.assertEqual(len(import_trajectory(buf.getvalue().encode(),"a.csv").points),6)
        for data in ({"curves":[]},{"points":[]}, {"points":[{**source().points[1].to_dict(),"x_mm":float('nan')}]},
                     {"points":[source().points[0].to_dict()]},
                     {**source().to_dict(),"coordinate_frame":"image_px"}):
            with self.assertRaises(ValueError): import_trajectory(json.dumps(data).encode(),"a.json")
        with self.assertRaises(ValueError): import_trajectory(b"G1 X0","a.gcode")

    def test_bounds_empty_and_new_stroke_boundary(self):
        doc=Composition()
        with self.assertRaises(ValueError): compose(doc)
        item=make_item(source(),"out",doc.plane); doc.items=[item];item.x_mm=-100
        with self.assertRaises(ValueError): compose(doc)
        item.x_mm=150;item.scale=float('inf')
        with self.assertRaises(ValueError): compose(doc)
        t=source();t.points=[p for p in t.points if p.drawing]
        self.assertEqual(len(drawing_runs(t)),2)


if __name__ == "__main__": unittest.main()
