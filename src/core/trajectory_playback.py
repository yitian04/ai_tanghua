"""Read-only, storage-independent timeline for nominal trajectory playback."""
from __future__ import annotations

import hashlib
import json
import math

from src.core.models import Trajectory


def build_playback(trajectory: Trajectory) -> dict:
    if trajectory.coordinate_frame != 'robot_base':
        raise ValueError('模拟只支持 robot_base 毫米轨迹。')
    if not trajectory.points:
        raise ValueError('轨迹为空。')
    points, times, strokes, point_strokes = [], [0.0], [], []
    previous = None
    bridges = 0
    for index, point in enumerate(trajectory.points):
        values = (point.x_mm, point.y_mm, point.z_mm, point.speed_mm_s)
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
            raise ValueError(f'轨迹点 {index} 的坐标或速度无效。')
        if point.speed_mm_s <= 0 or not isinstance(point.drawing, bool):
            raise ValueError(f'轨迹点 {index} 的速度或出料状态无效。')
        points.append([float(point.x_mm), float(point.y_mm), float(point.z_mm), point.drawing])
        if point.drawing:
            if previous is None or not previous.drawing or previous.curve_id != point.curve_id:
                strokes.append({'start': index, 'end': index, 'number': len(strokes) + 1})
            else:
                strokes[-1]['end'] = index
            point_strokes.append(len(strokes))
        else:
            point_strokes.append(0)
        if previous is not None:
            distance = math.dist(points[-2][:3], points[-1][:3])
            duration = distance / point.speed_mm_s
            total = times[-1] + duration
            if not math.isfinite(total): raise ValueError('轨迹名义时间超出可模拟范围。')
            times.append(total)
            if previous.drawing and point.drawing and previous.curve_id != point.curve_id and distance > 0:
                bridges += 1
        previous = point
    if not strokes: raise ValueError('轨迹没有绘制段。')
    # A travel point identifies the upcoming stroke; trailing travel uses the last.
    upcoming = len(strokes)
    for index in range(len(point_strokes) - 1, -1, -1):
        if point_strokes[index]: upcoming = point_strokes[index]
        else: point_strokes[index] = upcoming
    bounds = [min(p[0] for p in points), min(p[1] for p in points),
              max(p[0] for p in points), max(p[1] for p in points)]
    content = {'points': points, 'times': times, 'strokes': strokes, 'point_strokes': point_strokes}
    fingerprint = hashlib.sha256(json.dumps(content, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return {**content, 'version': 1, 'fingerprint': fingerprint, 'bounds': bounds,
            'duration_s': times[-1], 'warning': f'{bridges} 处跨笔移动未收料，按原轨迹显示。' if bridges else ''}
