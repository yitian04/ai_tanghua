from __future__ import annotations

import unittest

import numpy as np

from src.modules.image_process_module import create_binary_preview, vectorize_image_to_curve_list


class LineOnlyVectorizationTests(unittest.TestCase):
    def test_filled_and_close_regions_are_forced_to_line_components(self) -> None:
        image = np.full((160, 160, 3), 255, dtype=np.uint8)
        image[30:130, 35:75] = 0
        image[30:130, 80:120] = 0

        _, analysis = create_binary_preview(
            image,
            input_mode="line_only",
            blur_size=0,
            bridge_gap_px=0,
            min_component_area=5,
        )

        self.assertEqual(analysis["input_mode"], "line_only")
        self.assertEqual(analysis["area_component_count"], 0)
        self.assertEqual(analysis["line_component_count"], analysis["component_count"])
        self.assertTrue(all(item["content_type"] == "line" for item in analysis["components"]))

    def test_close_parallel_hatching_stays_as_separate_curves(self) -> None:
        image = np.full((120, 180, 3), 255, dtype=np.uint8)
        image[45:48, 25:155] = 0
        image[52:55, 25:155] = 0

        curves = vectorize_image_to_curve_list(
            image,
            blur_size=0,
            bridge_gap_px=0,
            min_component_area=2,
            min_curve_length_ratio=0.0,
            min_path_length=2,
            line_simplify_epsilon=0.5,
            vectorizer="skeleton_stroke_svg",
        )

        self.assertEqual(len(curves.curves), 2)
        mean_y = sorted(sum(point[1] for point in curve.points) / len(curve.points) for curve in curves.curves)
        self.assertGreater(mean_y[1] - mean_y[0], 4.0)


if __name__ == "__main__":
    unittest.main()
