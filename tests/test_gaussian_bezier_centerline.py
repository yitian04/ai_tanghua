"""Centerline behavior the sugar-painting UI and the trajectory planner share.

The fitter follows the solid-line stage of Chen et al., SIGGRAPH 2026
(DOI 10.1145/3799902.3811211): a constant-width Bézier stroke rendered by
2D Gaussians. These tests lock the image-to-curve contract rather than
the paper's texture or video stages.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from src.modules.curve_process_module import CurveProcessor
from src.modules.image_process_module import vectorize_image_to_curve_list
from src.pipeline.export.json_exporter import export_curves_json, load_curves_json
from src.pipeline.vectorization.gaussian_bezier import (
    LINE_FIT_ID,
    PAPER_DOI,
    RHO,
    fit_solid_stroke,
    gaussian_sigma,
)


def _ink(width: int, height: int) -> np.ndarray:
    return np.full((height, width, 3), 255, np.uint8)


class GaussianScaleTests(unittest.TestCase):
    def test_scale_follows_the_paper_formula(self) -> None:
        width = 4.0
        center = gaussian_sigma(width, 0.0, 0.4)
        self.assertAlmostEqual(center, width / RHO)
        # s > 0 and positive curvature enlarges the splat; the opposite side shrinks.
        self.assertGreater(gaussian_sigma(width, 0.5, 0.1), center)
        self.assertLess(gaussian_sigma(width, -0.5, 0.1), center)
        # A tight bend cannot produce a negative scale.
        self.assertGreaterEqual(gaussian_sigma(width, -1.0, 5.0), 0.35)


class SolidStrokeFitTests(unittest.TestCase):
    def test_isolated_straight_strand_moves_onto_the_medial_axis(self) -> None:
        mask = np.zeros((80, 140), np.uint8)
        mask[40:53, 10:110] = 1
        fitted = fit_solid_stroke([[10.0, 42.0], [110.0, 42.0]], mask)
        self.assertEqual(len(fitted), 2)
        self.assertEqual(fitted[0][0], 10.0)
        self.assertEqual(fitted[1][0], 110.0)
        self.assertAlmostEqual(fitted[0][1], fitted[1][1])
        self.assertLess(abs(fitted[0][1] - 46.0), 0.15)
        self.assertLess(abs(fitted[0][1] - 46.0), abs(42.0 - 46.0))

    def test_biased_arc_keeps_endpoints_and_returns_to_the_medial_radius(self) -> None:
        mask = np.zeros((180, 180), np.uint8)
        cv2.ellipse(mask, (90, 90), (50, 50), 0, 200, 340, 1, 11)
        angles = np.linspace(np.deg2rad(200), np.deg2rad(340), 50)
        biased = np.stack([90.0 + 49.0 * np.cos(angles), 90.0 + 49.0 * np.sin(angles)], axis=1)
        start = [float(biased[0, 0]), float(biased[0, 1])]
        end = [float(biased[-1, 0]), float(biased[-1, 1])]
        fitted = fit_solid_stroke(biased, mask, fix_start=True, fix_end=True)
        again = fit_solid_stroke(biased, mask, fix_start=True, fix_end=True)

        self.assertEqual(fitted, again)
        self.assertEqual(fitted[0], start)
        self.assertEqual(fitted[-1], end)
        radii = np.linalg.norm(np.asarray(fitted) - (90.0, 90.0), axis=1)
        # Pinned ends stay on the biased radius; the free samples sit on the ink.
        self.assertLess(abs(float(np.median(radii)) - 50.0), 0.35)
        self.assertLess(float(np.mean(np.abs(radii - 50.0))), 0.4)

    def test_empty_mask_falls_back_without_raising(self) -> None:
        fitted = fit_solid_stroke([[0.0, 0.0], [8.0, 0.2], [16.0, 0.0]], np.zeros((8, 24), np.uint8))
        self.assertGreaterEqual(len(fitted), 2)
        self.assertEqual(fitted[0], [0.0, 0.0])
        self.assertEqual(fitted[-1], [16.0, 0.0])


class VectorizedCurveContractTests(unittest.TestCase):
    def test_open_arc_and_closed_ring_stay_on_the_medial_axis(self) -> None:
        arc_image = _ink(180, 180)
        cv2.ellipse(arc_image, (90, 90), (50, 50), 0, 200, 340, (0, 0, 0), 9)
        arc = vectorize_image_to_curve_list(arc_image, blur_size=0, bridge_gap_px=0, min_curve_length_ratio=0.0)
        self.assertEqual(arc.coordinate_frame, "image_px")
        self.assertEqual(arc.metadata["line_fit"], LINE_FIT_ID)
        self.assertEqual(arc.metadata["line_fit_reference"], PAPER_DOI)
        self.assertEqual(len(arc.curves), 1)
        self.assertFalse(arc.curves[0].closed)
        arc_error = [abs(np.hypot(x - 90.0, y - 90.0) - 50.0) for x, y in arc.curves[0].points]
        self.assertLess(max(arc_error), 1.25)
        self.assertLess(float(np.mean(arc_error)), 0.35)

        ring_image = _ink(140, 140)
        cv2.circle(ring_image, (70, 70), 40, (0, 0, 0), 7)
        ring = vectorize_image_to_curve_list(ring_image, blur_size=0, bridge_gap_px=0, min_curve_length_ratio=0.0)
        self.assertEqual(len(ring.curves), 1)
        self.assertTrue(ring.curves[0].closed)
        self.assertEqual(ring.curves[0].points[0], ring.curves[0].points[-1])
        ring_error = [abs(np.hypot(x - 70.0, y - 70.0) - 40.0) for x, y in ring.curves[0].points]
        self.assertLess(max(ring_error), 1.25)

    def test_junctions_meet_and_gaps_are_not_bridged(self) -> None:
        tee = _ink(160, 140)
        cv2.line(tee, (20, 40), (140, 40), (0, 0, 0), 7)
        cv2.line(tee, (80, 40), (80, 120), (0, 0, 0), 7)
        curves = vectorize_image_to_curve_list(tee, blur_size=0, bridge_gap_px=0, min_curve_length_ratio=0.0)
        self.assertEqual(len(curves.curves), 2)
        bar = max(curves.curves, key=lambda curve: max(point[0] for point in curve.points) - min(point[0] for point in curve.points))
        stem = min(curves.curves, key=lambda curve: max(point[0] for point in curve.points) - min(point[0] for point in curve.points))
        self.assertIn([80.0, 40.0], bar.points)
        self.assertEqual(stem.points[0], [80.0, 40.0])
        self.assertTrue(all(abs(point[1] - 40.0) <= 1.0 for point in bar.points))
        self.assertTrue(all(abs(point[0] - 80.0) <= 1.0 for point in stem.points))

        gap = _ink(180, 80)
        cv2.line(gap, (15, 40), (70, 40), (0, 0, 0), 7)
        cv2.line(gap, (86, 40), (150, 40), (0, 0, 0), 7)
        separated = vectorize_image_to_curve_list(gap, blur_size=0, bridge_gap_px=0, min_curve_length_ratio=0.0)
        self.assertEqual(len(separated.curves), 2)
        spans = []
        for curve in separated.curves:
            xs = [point[0] for point in curve.points]
            spans.append((min(xs), max(xs)))
        spans.sort()
        self.assertGreater(spans[1][0] - spans[0][1], 8.0)

    def test_sharp_corner_is_not_rounded_into_a_fillet(self) -> None:
        image = _ink(140, 140)
        cv2.line(image, (20, 30), (90, 30), (0, 0, 0), 7)
        cv2.line(image, (90, 30), (90, 110), (0, 0, 0), 7)
        curves = vectorize_image_to_curve_list(image, blur_size=0, bridge_gap_px=0, min_curve_length_ratio=0.0)
        points = [point for curve in curves.curves for point in curve.points]
        corner_distance = min(np.hypot(x - 90.0, y - 30.0) for x, y in points)
        self.assertLess(corner_distance, 2.0)
        horizontal = [point for point in points if point[0] < 60.0]
        vertical = [point for point in points if point[1] > 50.0]
        self.assertTrue(horizontal)
        self.assertTrue(vertical)
        self.assertLess(max(abs(point[1] - 30.0) for point in horizontal), 1.5)
        self.assertLess(max(abs(point[0] - 90.0) for point in vertical), 1.5)

    def test_curve_json_roundtrip_feeds_the_trajectory_planner(self) -> None:
        image = _ink(180, 180)
        cv2.ellipse(image, (90, 90), (50, 50), 0, 200, 340, (0, 0, 0), 9)
        curves = vectorize_image_to_curve_list(
            image,
            blur_size=0,
            bridge_gap_px=0,
            min_curve_length_ratio=0.0,
            vectorizer="opencv_fallback",
        )
        self.assertEqual(curves.metadata["line_fit"], LINE_FIT_ID)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "curves.json"
            export_curves_json(curves, path)
            loaded = load_curves_json(path)
        self.assertEqual(loaded.coordinate_frame, "image_px")
        self.assertEqual(loaded.metadata["line_fit_reference"], PAPER_DOI)
        self.assertEqual(loaded.curves[0].points, curves.curves[0].points)

        processor = CurveProcessor()
        processor.set_workspace_size(160.0, 160.0)
        for curve in loaded.curves:
            processor.add_curve([(point[0], point[1]) for point in curve.points])
        result = processor.process()
        self.assertEqual(result["num_curves"], len(loaded.curves))
        self.assertGreater(result["num_points"], len(loaded.curves))
        self.assertTrue(any(point.drawing for point in result["trajectory"].points))
        self.assertEqual(result["trajectory"].metadata["source_frame"], "image_px")
        self.assertGreater(result["trajectory"].metadata["drawing_length_mm"], 0.0)


if __name__ == "__main__":
    unittest.main()
