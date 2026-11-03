"""Deterministic XY layout and ordered composition of project trajectories."""
from __future__ import annotations

import csv
import io
import json
import math
import uuid
from dataclasses import asdict, dataclass, field

from src.core.models import Trajectory, TrajectoryPoint


@dataclass
class Plane:
    width_mm: float = 300.0
    height_mm: float = 300.0
    center_x_mm: float = 300.0
    center_y_mm: float = 0.0
    draw_z_mm: float = 50.0
    lift_mm: float = 10.0
    travel_speed_mm_s: float = 150.0
    orientation: list[float] = field(default_factory=lambda: [0.0, 180.0, 0.0])


@dataclass
class LayoutItem:
    id: str
    name: str
    trajectory: Trajectory
    x_mm: float
    y_mm: float
    scale: float = 1.0
    rotation_deg: float = 0.0


@dataclass
class Composition:
    plane: Plane = field(default_factory=Plane)
    items: list[LayoutItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"type": "trajectory_composition", "version": 1, "plane": asdict(self.plane),
                "items": [{**asdict(i), "trajectory": i.trajectory.to_dict()} for i in self.items]}

    @classmethod
    def from_dict(cls, data: dict) -> "Composition":
        if data.get("type") != "trajectory_composition" or data.get("version") != 1:
            raise ValueError("不是受支持的轨迹合成工程。")
        result = cls(plane=Plane(**data["plane"]))
        validate_plane(result.plane)
        for item in data["items"]:
            item = dict(item)
            item["trajectory"] = import_trajectory(json.dumps(item["trajectory"]).encode(), "source.json")
            result.items.append(LayoutItem(**item))
        if len({i.id for i in result.items}) != len(result.items):
            raise ValueError("工程对象编号重复。")
        for item in result.items:
            transformed_runs(item)
        return result


def import_trajectory(content: bytes, filename: str) -> Trajectory:
    text = content.decode("utf-8-sig")
    if filename.lower().endswith(".json"):
        data = json.loads(text)
        if not isinstance(data, dict) or "points" not in data:
            raise ValueError("需要轨迹 JSON；曲线 JSON 请先到轨迹规划页面处理。")
        if data.get("coordinate_frame", "robot_base") != "robot_base":
            raise ValueError("只接受 robot_base 毫米轨迹。")
        rows = data["points"]
    elif filename.lower().endswith(".csv"):
        rows = list(csv.DictReader(io.StringIO(text)))
        data = {}
    else:
        raise ValueError("只支持项目轨迹 JSON / CSV。")
    if not isinstance(rows, list) or not rows:
        raise ValueError("轨迹为空。")
    parsed = []
    required = {"x_mm", "y_mm", "z_mm", "drawing", "speed_mm_s", "curve_id", "point_id"}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not required.issubset(row):
            raise ValueError(f"轨迹点 {index} 缺少项目标准字段。")
        row = dict(row)
        if isinstance(row["drawing"], str) and row["drawing"].lower() in {"true", "false", "1", "0"}:
            row["drawing"] = row["drawing"].lower() in {"true", "1"}
        if not isinstance(row["drawing"], bool):
            raise ValueError(f"轨迹点 {index} 的 drawing 必须为布尔值。")
        for key in required - {"drawing"}:
            if isinstance(row[key], bool) or not math.isfinite(float(row[key])):
                raise ValueError(f"轨迹点 {index} 的 {key} 无效。")
        point = TrajectoryPoint.from_dict(row)
        if point.speed_mm_s <= 0 or not all(math.isfinite(v) for v in (point.rx_deg, point.ry_deg, point.rz_deg)):
            raise ValueError(f"轨迹点 {index} 速度或姿态无效。")
        parsed.append(point)
    trajectory = Trajectory(points=parsed, metadata=data.get("metadata", {}))
    drawing_runs(trajectory)
    return trajectory


def drawing_runs(trajectory: Trajectory) -> list[list[TrajectoryPoint]]:
    runs, current = [], []
    for point in trajectory.points:
        if not point.drawing or (current and current[-1].curve_id != point.curve_id):
            if current:
                runs.append(current)
                current = []
        if point.drawing:
            current.append(point)
    if current:
        runs.append(current)
    if not runs:
        raise ValueError("轨迹没有绘制段。")
    return runs


def bounds(points) -> tuple[float, float, float, float]:
    points = list(points)
    return min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)


def source_bounds(item: LayoutItem):
    return bounds((p.x_mm, p.y_mm) for run in drawing_runs(item.trajectory) for p in run)


def make_item(trajectory: Trajectory, name: str, plane: Plane) -> LayoutItem:
    return LayoutItem(uuid.uuid4().hex, name, trajectory, plane.width_mm / 2, plane.height_mm / 2)


def transformed_runs(item: LayoutItem) -> list[list[tuple[float, float, float]]]:
    if not all(math.isfinite(v) for v in (item.x_mm, item.y_mm, item.scale, item.rotation_deg)) or item.scale <= 0:
        raise ValueError("对象变换必须为有限数值且缩放大于零。")
    x0, y0, x1, y1 = source_bounds(item)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    theta = math.radians(item.rotation_deg)
    c, s = math.cos(theta), math.sin(theta)
    output = []
    for run in drawing_runs(item.trajectory):
        path = []
        for point in run:
            x, y = (point.x_mm - cx) * item.scale, (point.y_mm - cy) * item.scale
            path.append((item.x_mm + x*c - y*s, item.y_mm + x*s + y*c, point.speed_mm_s))
        output.append(path)
    return output


def validate_plane(plane: Plane) -> None:
    numbers = [v for k, v in asdict(plane).items() if k != "orientation"] + list(plane.orientation)
    if not all(math.isfinite(v) for v in numbers) or len(plane.orientation) != 3:
        raise ValueError("画布和姿态参数必须为有限数值。")
    if min(plane.width_mm, plane.height_mm, plane.travel_speed_mm_s, plane.lift_mm) <= 0:
        raise ValueError("画布尺寸、空走速度和抬笔高度须大于零。")


def out_of_bounds(item: LayoutItem, plane: Plane) -> bool:
    return any(x < -1e-7 or y < -1e-7 or x > plane.width_mm+1e-7 or y > plane.height_mm+1e-7
               for run in transformed_runs(item) for x, y, _ in run)


def compose(document: Composition) -> Trajectory:
    plane = document.plane
    validate_plane(plane)
    if not document.items:
        raise ValueError("请先添加轨迹。")
    points, ranges = [], []
    curve_id = 0
    dx, dy = plane.center_x_mm-plane.width_mm/2, plane.center_y_mm-plane.height_mm/2

    def append(x, y, z, speed, drawing):
        points.append(TrajectoryPoint(x+dx, y+dy, z, speed, drawing,
                                     *plane.orientation, curve_id, len(points)))

    for item in document.items:
        if out_of_bounds(item, plane):
            raise ValueError(f"对象「{item.name}」超出画布，请移动或缩小。")
        first = len(points)
        for run in transformed_runs(item):
            x, y, _ = run[0]
            # Travel and descent are explicitly non-drawing, including the very first run.
            append(x, y, plane.draw_z_mm+plane.lift_mm, plane.travel_speed_mm_s, False)
            append(x, y, plane.draw_z_mm, plane.travel_speed_mm_s, False)
            for x, y, speed in run:
                append(x, y, plane.draw_z_mm, speed, True)
            append(x, y, plane.draw_z_mm+plane.lift_mm, plane.travel_speed_mm_s, False)
            curve_id += 1
        ranges.append({"id": item.id, "name": item.name, "point_start": first, "point_end_exclusive": len(points)})
    length = sum(math.hypot(b.x_mm-a.x_mm, b.y_mm-a.y_mm) for a, b in zip(points, points[1:])
                 if a.drawing and b.drawing and a.curve_id == b.curve_id)
    return Trajectory(points=points, tool_orientation_deg=list(plane.orientation), metadata={
        "generator": "trajectory_composition_v1", "objects": ranges, "plane": asdict(plane),
        "curve_count": curve_id, "drawing_length_mm": length, "optimizer": "preserved",
    })
