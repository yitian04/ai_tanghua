from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

from src.core.models import Curve2D, CurveList, Trajectory, TrajectoryPoint


@dataclass
class PlanningConfig:
    center_x_mm: float = 300.0
    center_y_mm: float = 0.0
    draw_z_mm: float = 50.0
    workspace_width_mm: float = 300.0
    workspace_height_mm: float = 300.0
    rotation_deg: float = 0.0
    step_mm: float = 5.0
    use_lift: bool = True
    lift_z_mm: float = 10.0
    drawing_speed_mm_s: float = 50.0
    travel_speed_mm_s: float = 150.0
    tool_orientation_deg: Tuple[float, float, float] = (0.0, 180.0, 0.0)
    optimize_curve_order: bool = True
    exact_order_limit: int = 10
    max_multistart_starts: int = 24
    two_opt_passes: int = 30
    two_opt_curve_limit: int = 120


class TrajectoryPlanner:
    def __init__(self, config: PlanningConfig | None = None):
        self.config = config or PlanningConfig()

    def plan(self, curve_list: CurveList) -> Trajectory:
        curves = [Curve2D(points=[list(p) for p in curve.points], curve_id=curve.curve_id, closed=curve.closed) for curve in curve_list.curves]
        transformed = self._transform_curves(curves)
        if self.config.optimize_curve_order:
            ordered, travel_distance, optimizer = self._optimize_curves(transformed)
        else:
            ordered = transformed
            travel_distance = self._path_travel_distance(ordered)
            optimizer = "disabled"
        points = self._sample_ordered_curves(ordered)
        drawing_length = sum(self._curve_length(curve) for curve in ordered)
        estimated = self._estimate_time_seconds(ordered, drawing_length, travel_distance)
        return Trajectory(
            points=points,
            coordinate_frame="robot_base",
            tool_orientation_deg=list(self.config.tool_orientation_deg),
            metadata={
                "source_frame": curve_list.coordinate_frame,
                "curve_count": len(ordered),
                "ordering_travel_distance_mm": travel_distance,
                "drawing_length_mm": drawing_length,
                "estimated_drawing_time_s": estimated["drawing_time_s"],
                "estimated_travel_time_s": estimated["travel_time_s"],
                "estimated_lift_time_s": estimated["lift_time_s"],
                "estimated_total_time_s": estimated["total_time_s"],
                "optimizer": optimizer,
                "planner": "trajectory_planner_v2",
            },
        )

    def _transform_curves(self, curves: List[Curve2D]) -> List[Curve2D]:
        if not curves:
            return []

        all_points = np.array([point for curve in curves for point in curve.points], dtype=float)
        if all_points.size == 0:
            return []

        source_center = all_points.mean(axis=0)
        shifted = all_points - source_center
        width = float(shifted[:, 0].max() - shifted[:, 0].min())
        height = float(shifted[:, 1].max() - shifted[:, 1].min())
        scale = min(
            self.config.workspace_width_mm / width if width > 0 else 1.0,
            self.config.workspace_height_mm / height if height > 0 else 1.0,
        ) * 0.9

        theta = math.radians(self.config.rotation_deg)
        rotation = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
        transformed: List[Curve2D] = []
        for curve in curves:
            points = []
            for raw in curve.points:
                point = (np.array(raw, dtype=float) - source_center) * scale
                point = rotation @ point
                point += np.array([self.config.center_x_mm, self.config.center_y_mm])
                points.append([float(point[0]), float(point[1])])
            transformed.append(Curve2D(points=points, curve_id=curve.curve_id, closed=curve.closed))
        return transformed

    def _order_curves(self, curves: List[Curve2D]) -> Tuple[List[Curve2D], float]:
        if not curves:
            return [], 0.0
        remaining = list(curves)
        ordered = [remaining.pop(0)]
        total_distance = 0.0

        while remaining:
            last = ordered[-1].end()
            best_idx = 0
            best_flip = False
            best_distance = float("inf")
            for idx, curve in enumerate(remaining):
                start_distance = self._distance(last, curve.start())
                end_distance = self._distance(last, curve.end())
                if start_distance < best_distance:
                    best_idx = idx
                    best_flip = False
                    best_distance = start_distance
                if end_distance < best_distance:
                    best_idx = idx
                    best_flip = True
                    best_distance = end_distance
            chosen = remaining.pop(best_idx)
            ordered.append(chosen.reversed() if best_flip else chosen)
            total_distance += best_distance
        return ordered, total_distance

    def _optimize_curves(self, curves: List[Curve2D]) -> Tuple[List[Curve2D], float, str]:
        if len(curves) < 2:
            return list(curves), 0.0, "trivial"
        exact_limit = max(0, int(self.config.exact_order_limit))
        if len(curves) <= exact_limit:
            ordered = self._exact_open_path_order(curves)
            return ordered, self._path_travel_distance(ordered), "exact_dp_open_path"

        ordered = self._multi_start_nearest_order(curves)
        if len(ordered) <= max(0, int(self.config.two_opt_curve_limit)):
            ordered = self._two_opt_order(ordered, max_passes=max(0, int(self.config.two_opt_passes)))
            optimizer = "multi_start_nearest_2opt"
        else:
            optimizer = "multi_start_nearest"
        return ordered, self._path_travel_distance(ordered), optimizer

    def _exact_open_path_order(self, curves: List[Curve2D]) -> List[Curve2D]:
        n = len(curves)
        oriented = [(curve, curve.reversed()) for curve in curves]
        dp = {}
        parent = {}

        for idx in range(n):
            for orient in (0, 1):
                dp[(1 << idx, idx, orient)] = 0.0
                parent[(1 << idx, idx, orient)] = None

        for mask in range(1, 1 << n):
            for last in range(n):
                for last_orient in (0, 1):
                    key = (mask, last, last_orient)
                    if key not in dp:
                        continue
                    current = oriented[last][last_orient]
                    for nxt in range(n):
                        if mask & (1 << nxt):
                            continue
                        for next_orient in (0, 1):
                            candidate = oriented[nxt][next_orient]
                            new_mask = mask | (1 << nxt)
                            new_key = (new_mask, nxt, next_orient)
                            cost = dp[key] + self._distance(current.end(), candidate.start())
                            if cost < dp.get(new_key, float("inf")):
                                dp[new_key] = cost
                                parent[new_key] = key

        full_mask = (1 << n) - 1
        best_key = min((key for key in dp if key[0] == full_mask), key=lambda key: dp[key])
        order = []
        key = best_key
        while key is not None:
            _, idx, orient = key
            order.append(oriented[idx][orient])
            key = parent[key]
        order.reverse()
        return order

    def _multi_start_nearest_order(self, curves: List[Curve2D]) -> List[Curve2D]:
        best_order: List[Curve2D] = []
        best_distance = float("inf")
        all_starts = [(idx, orient) for idx in range(len(curves)) for orient in (0, 1)]
        max_starts = max(1, int(self.config.max_multistart_starts))
        if len(all_starts) <= max_starts:
            starts = all_starts
        else:
            step = max(1, len(all_starts) // max_starts)
            starts = all_starts[::step][:max_starts]

        for start_idx, start_orient in starts:
            remaining = [Curve2D(points=[list(p) for p in curve.points], curve_id=curve.curve_id, closed=curve.closed) for curve in curves]
            start_curve = remaining.pop(start_idx)
            ordered = [start_curve if start_orient == 0 else start_curve.reversed()]

            while remaining:
                last = ordered[-1].end()
                best_idx = 0
                best_flip = False
                best_step = float("inf")
                for idx, curve in enumerate(remaining):
                    start_distance = self._distance(last, curve.start())
                    end_distance = self._distance(last, curve.end())
                    if start_distance < best_step:
                        best_idx = idx
                        best_flip = False
                        best_step = start_distance
                    if end_distance < best_step:
                        best_idx = idx
                        best_flip = True
                        best_step = end_distance
                chosen = remaining.pop(best_idx)
                ordered.append(chosen.reversed() if best_flip else chosen)

            distance = self._path_travel_distance(ordered)
            if distance < best_distance:
                best_order = ordered
                best_distance = distance
        return best_order

    def _two_opt_order(self, curves: List[Curve2D], max_passes: int = 30) -> List[Curve2D]:
        if len(curves) < 4 or max_passes <= 0:
            return curves
        ordered = list(curves)

        for _ in range(max_passes):
            improved = False
            current_distance = self._path_travel_distance(ordered)
            for i in range(0, len(ordered) - 2):
                for j in range(i + 1, len(ordered) - 1):
                    candidate = ordered[:i + 1] + [curve.reversed() for curve in reversed(ordered[i + 1:j + 1])] + ordered[j + 1:]
                    candidate_distance = self._path_travel_distance(candidate)
                    if candidate_distance + 1e-9 < current_distance:
                        ordered = candidate
                        current_distance = candidate_distance
                        improved = True
            if not improved:
                break
        return ordered

    def _path_travel_distance(self, curves: List[Curve2D]) -> float:
        if len(curves) < 2:
            return 0.0
        return sum(self._distance(prev.end(), nxt.start()) for prev, nxt in zip(curves, curves[1:]))

    def _curve_length(self, curve: Curve2D) -> float:
        if len(curve.points) < 2:
            return 0.0
        return sum(self._distance(start, end) for start, end in zip(curve.points, curve.points[1:]))

    def _estimate_time_seconds(self, curves: List[Curve2D], drawing_length: float, travel_distance: float) -> dict:
        drawing_speed = max(float(self.config.drawing_speed_mm_s), 0.001)
        travel_speed = max(float(self.config.travel_speed_mm_s), 0.001)
        drawing_time = drawing_length / drawing_speed
        travel_time = travel_distance / travel_speed
        lift_time = 0.0
        if self.config.use_lift:
            lift_distance = max(0.0, float(self.config.lift_z_mm)) * 2.0 * len(curves)
            lift_time = lift_distance / travel_speed
        return {
            "drawing_time_s": drawing_time,
            "travel_time_s": travel_time,
            "lift_time_s": lift_time,
            "total_time_s": drawing_time + travel_time + lift_time,
        }

    def _sample_ordered_curves(self, curves: List[Curve2D]) -> List[TrajectoryPoint]:
        output: List[TrajectoryPoint] = []
        point_id = 0
        for curve in curves:
            sampled = self._sample_polyline(curve.points)
            if not sampled:
                continue
            if self.config.use_lift:
                x, y = sampled[0]
                output.append(self._make_point(point_id, curve.curve_id, x, y, self._lift_z_mm(), self.config.travel_speed_mm_s, False))
                point_id += 1
            for x, y in sampled:
                output.append(self._make_point(point_id, curve.curve_id, x, y, self.config.draw_z_mm, self.config.drawing_speed_mm_s, True))
                point_id += 1
            if self.config.use_lift:
                x, y = sampled[-1]
                output.append(self._make_point(point_id, curve.curve_id, x, y, self._lift_z_mm(), self.config.travel_speed_mm_s, False))
                point_id += 1
        return output

    def _lift_z_mm(self) -> float:
        return float(self.config.draw_z_mm) + max(0.0, float(self.config.lift_z_mm))

    def _sample_polyline(self, points: List[List[float]]) -> List[List[float]]:
        if len(points) < 2:
            return points
        sampled = [points[0]]
        step = max(float(self.config.step_mm), 0.1)
        for start, end in zip(points, points[1:]):
            segment = self._distance(start, end)
            count = max(1, int(math.ceil(segment / step)))
            for idx in range(1, count + 1):
                t = idx / count
                sampled.append([
                    float(start[0] + (end[0] - start[0]) * t),
                    float(start[1] + (end[1] - start[1]) * t),
                ])
        return sampled

    def _make_point(self, point_id: int, curve_id: int, x: float, y: float, z: float, speed: float, drawing: bool) -> TrajectoryPoint:
        rx_deg, ry_deg, rz_deg = self.config.tool_orientation_deg
        return TrajectoryPoint(
            point_id=point_id,
            curve_id=curve_id,
            x_mm=float(x),
            y_mm=float(y),
            z_mm=float(z),
            speed_mm_s=float(speed),
            drawing=bool(drawing),
            rx_deg=float(rx_deg),
            ry_deg=float(ry_deg),
            rz_deg=float(rz_deg),
        )

    @staticmethod
    def _distance(a: List[float], b: List[float]) -> float:
        return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))
