import numpy as np
from scipy.interpolate import splprep, splev
from typing import List, Tuple, Dict, Optional
import json


class PathPoint:
    def __init__(self, x: float, y: float, z: float, 
                 rx: float = 0.0, ry: float = 0.0, rz: float = 0.0,
                 speed: float = 0.1, acceleration: float = 0.3,
                 is_drawing: bool = True, curve_id: int = 0):
        self.x = x
        self.y = y
        self.z = z
        self.rx = rx
        self.ry = ry
        self.rz = rz
        self.speed = speed
        self.acceleration = acceleration
        self.is_drawing = is_drawing
        self.curve_id = curve_id
    
    def to_dict(self) -> Dict:
        return {
            'x': self.x, 'y': self.y, 'z': self.z,
            'rx': self.rx, 'ry': self.ry, 'rz': self.rz,
            'speed': self.speed, 'acceleration': self.acceleration,
            'is_drawing': self.is_drawing, 'curve_id': self.curve_id
        }
    
    def to_urscript(self) -> str:
        return f"p[{self.x}, {self.y}, {self.z}, {self.rx}, {self.ry}, {self.rz}]"


class Curve:
    def __init__(self, points: List[Tuple[float, float, float]], curve_id: int = 0):
        self.points = points
        self.curve_id = curve_id
        self.length = 0.0
        self.calculate_length()
    
    def calculate_length(self):
        if len(self.points) < 2:
            self.length = 0.0
            return
        self.length = sum(
            np.linalg.norm(np.array(self.points[i]) - np.array(self.points[i-1]))
            for i in range(1, len(self.points))
        )
    
    def get_start_point(self) -> Tuple[float, float, float]:
        return self.points[0] if self.points else (0, 0, 0)
    
    def get_end_point(self) -> Tuple[float, float, float]:
        return self.points[-1] if self.points else (0, 0, 0)


class PathPlanner:
    def __init__(self):
        self.curves: List[Curve] = []
        self.all_points: List[PathPoint] = []
        
        self.workspace_bounds = {
            'x_min': -0.85, 'x_max': 0.85,
            'y_min': -0.85, 'y_max': 0.85,
            'z_min': 0.0, 'z_max': 0.926
        }
        
        self.base_position = (0.0, 0.0, 0.0)
        self.scale_factor = 1.0
        self.rotation_angle = 0.0
        
        self.default_speed = 0.1
        self.default_acceleration = 0.3
        self.travel_speed = 0.3
        self.travel_acceleration = 0.5
        self.default_orientation = (3.14, 0, 0)
        
        self.drawing_height = 0.1
        self.lift_height = 0.15
        self.output_pin = 0
        
        self.start_delay = 0.2
        self.end_delay = 0.2
        
        self.use_curvature_speed = True
        self.max_curvature_speed = 0.15
        self.min_curvature_speed = 0.03
        
        self.simplify_tolerance = 0.001
    
    def load_default_shape(self) -> None:
        self.curves = []
        
        # 第一笔：圆形（兔子头部）
        circle_points = []
        for angle in np.linspace(0, 2 * np.pi, 50):
            x = 0.5 + 0.08 * np.cos(angle)
            y = 0.15 + 0.08 * np.sin(angle)
            z = self.drawing_height
            circle_points.append((x, y, z))
        self.curves.append(Curve(circle_points, curve_id=0))
        
        # 第二笔：左耳
        ear1_points = []
        for t in np.linspace(0, 1, 20):
            x = 0.45 + 0.03 * np.cos(t * np.pi)
            y = 0.23 - 0.12 * t
            z = self.drawing_height
            ear1_points.append((x, y, z))
        self.curves.append(Curve(ear1_points, curve_id=1))
        
        # 第三笔：右耳
        ear2_points = []
        for t in np.linspace(0, 1, 20):
            x = 0.55 + 0.03 * np.cos(t * np.pi)
            y = 0.23 - 0.12 * t
            z = self.drawing_height
            ear2_points.append((x, y, z))
        self.curves.append(Curve(ear2_points, curve_id=2))
        
        # 第四笔：身体
        body_points = []
        for t in np.linspace(0, 1, 30):
            x = 0.5 + 0.02 * np.sin(t * np.pi)
            y = 0.15 - 0.15 * t
            z = self.drawing_height
            body_points.append((x, y, z))
        self.curves.append(Curve(body_points, curve_id=3))
        
        # 第五笔：左前腿
        leg1_points = []
        for t in np.linspace(0, 1, 15):
            x = 0.47 - 0.03 * t
            y = 0.02 - 0.08 * t
            z = self.drawing_height
            leg1_points.append((x, y, z))
        self.curves.append(Curve(leg1_points, curve_id=4))
        
        # 第六笔：右前腿
        leg2_points = []
        for t in np.linspace(0, 1, 15):
            x = 0.53 + 0.03 * t
            y = 0.02 - 0.08 * t
            z = self.drawing_height
            leg2_points.append((x, y, z))
        self.curves.append(Curve(leg2_points, curve_id=5))
    
    def add_curve(self, points: List[Tuple[float, float, float]]) -> None:
        curve_id = len(self.curves)
        self.curves.append(Curve(points, curve_id=curve_id))
    
    def set_workspace_bounds(self, x_min: float, x_max: float, 
                            y_min: float, y_max: float, 
                            z_min: float, z_max: float) -> None:
        self.workspace_bounds = {
            'x_min': x_min, 'x_max': x_max,
            'y_min': y_min, 'y_max': y_max,
            'z_min': z_min, 'z_max': z_max
        }
    
    def set_base_position(self, x: float, y: float, z: float) -> None:
        self.base_position = (x, y, z)
    
    def set_scale_factor(self, scale: float) -> None:
        self.scale_factor = scale
    
    def set_rotation_angle(self, angle_deg: float) -> None:
        self.rotation_angle = np.radians(angle_deg)
    
    def set_curvature_speed_params(self, enable: bool, max_speed: float, min_speed: float) -> None:
        self.use_curvature_speed = enable
        self.max_curvature_speed = max_speed
        self.min_curvature_speed = min_speed
    
    def set_simplify_tolerance(self, tolerance: float) -> None:
        self.simplify_tolerance = tolerance
    
    def _rotate_point(self, x: float, y: float, cx: float = 0, cy: float = 0) -> Tuple[float, float]:
        cos_theta = np.cos(self.rotation_angle)
        sin_theta = np.sin(self.rotation_angle)
        dx = x - cx
        dy = y - cy
        new_x = dx * cos_theta - dy * sin_theta + cx
        new_y = dx * sin_theta + dy * cos_theta + cy
        return new_x, new_y
    
    def _simplify_curve_rdp(self, points: List[Tuple[float, float, float]], epsilon: float) -> List[Tuple[float, float, float]]:
        if len(points) <= 2:
            return points
        
        d_max = 0.0
        index = 0
        end = len(points) - 1
        
        for i in range(1, end):
            d = self._point_to_segment_distance(points[i], points[0], points[end])
            if d > d_max:
                index = i
                d_max = d
        
        if d_max > epsilon:
            rec_results1 = self._simplify_curve_rdp(points[:index+1], epsilon)
            rec_results2 = self._simplify_curve_rdp(points[index:], epsilon)
            return rec_results1[:-1] + rec_results2
        else:
            return [points[0], points[end]]
    
    def _point_to_segment_distance(self, point: Tuple[float, float, float], 
                                   line_start: Tuple[float, float, float], 
                                   line_end: Tuple[float, float, float]) -> float:
        px, py, _ = point
        lx1, ly1, _ = line_start
        lx2, ly2, _ = line_end
        
        A = px - lx1
        B = py - ly1
        C = lx2 - lx1
        D = ly2 - ly1
        
        dot = A * C + B * D
        len_sq = C * C + D * D
        param = -1.0
        
        if len_sq != 0:
            param = dot / len_sq
        
        if param < 0:
            xx, yy = lx1, ly1
        elif param > 1:
            xx, yy = lx2, ly2
        else:
            xx = lx1 + param * C
            yy = ly1 + param * D
        
        dx = px - xx
        dy = py - yy
        return np.sqrt(dx * dx + dy * dy)
    
    def _estimate_curvature(self, points: np.ndarray, index: int) -> float:
        if len(points) < 3:
            return 0.0
        
        if index <= 0 or index >= len(points) - 1:
            return 0.0
        
        p_prev = points[index - 1]
        p_curr = points[index]
        p_next = points[index + 1]
        
        v1 = p_curr - p_prev
        v2 = p_next - p_curr
        
        len_v1 = np.linalg.norm(v1)
        len_v2 = np.linalg.norm(v2)
        
        if len_v1 == 0 or len_v2 == 0:
            return 0.0
        
        cross = np.cross(v1[:2], v2[:2])
        dot = np.dot(v1, v2)
        
        sin_theta = cross / (len_v1 * len_v2)
        cos_theta = dot / (len_v1 * len_v2)
        
        theta = np.arctan2(sin_theta, cos_theta)
        
        if abs(theta) < 1e-10:
            return 0.0
        
        chord_length = np.linalg.norm(p_next - p_prev)
        curvature = 2 * abs(np.sin(theta / 2)) / chord_length if chord_length > 0 else 0.0
        
        return curvature
    
    def _update_speed_by_curvature(self, points: List[PathPoint]) -> None:
        if not self.use_curvature_speed:
            return
        
        points_array = np.array([[p.x, p.y, p.z] for p in points])
        
        for i, point in enumerate(points):
            curvature = self._estimate_curvature(points_array, i)
            
            max_curvature = 50.0
            normalized_curvature = min(curvature / max_curvature, 1.0)
            
            speed_range = self.max_curvature_speed - self.min_curvature_speed
            point.speed = self.max_curvature_speed - normalized_curvature * speed_range
            point.speed = max(self.min_curvature_speed, min(self.max_curvature_speed, point.speed))
    
    def simplify_curves(self) -> None:
        for curve in self.curves:
            if len(curve.points) > 2:
                simplified = self._simplify_curve_rdp(curve.points, self.simplify_tolerance)
                curve.points = simplified
                curve.calculate_length()
    
    def transform_to_workspace(self) -> None:
        for curve in self.curves:
            transformed_points = []
            for (x, y, z) in curve.points:
                scaled_x = x * self.scale_factor
                scaled_y = y * self.scale_factor
                
                if self.rotation_angle != 0:
                    cx = self.base_position[0]
                    cy = self.base_position[1]
                    scaled_x, scaled_y = self._rotate_point(scaled_x, scaled_y, cx, cy)
                
                new_x = self.base_position[0] + scaled_x
                new_y = self.base_position[1] + scaled_y
                new_z = self.base_position[2] + z * self.scale_factor
                
                new_x = max(self.workspace_bounds['x_min'], min(new_x, self.workspace_bounds['x_max']))
                new_y = max(self.workspace_bounds['y_min'], min(new_y, self.workspace_bounds['y_max']))
                new_z = max(self.workspace_bounds['z_min'], min(new_z, self.workspace_bounds['z_max']))
                
                transformed_points.append((new_x, new_y, new_z))
            curve.points = transformed_points
            curve.calculate_length()
    
    def sort_curves_by_proximity(self) -> None:
        if len(self.curves) < 2:
            return
        
        sorted_curves = [self.curves.pop(0)]
        
        while self.curves:
            last_end = sorted_curves[-1].get_end_point()
            min_distance = float('inf')
            closest_idx = -1
            
            for i, curve in enumerate(self.curves):
                start_dist = np.linalg.norm(np.array(curve.get_start_point()) - np.array(last_end))
                end_dist = np.linalg.norm(np.array(curve.get_end_point()) - np.array(last_end))
                
                if start_dist < min_distance:
                    min_distance = start_dist
                    closest_idx = i
                    flip = False
                if end_dist < min_distance:
                    min_distance = end_dist
                    closest_idx = i
                    flip = True
            
            if closest_idx >= 0:
                curve = self.curves.pop(closest_idx)
                if flip:
                    curve.points = curve.points[::-1]
                sorted_curves.append(curve)
        
        self.curves = sorted_curves
    
    def sample_curve(self, curve: Curve, step_size: float = 0.005) -> List[PathPoint]:
        points_array = np.array(curve.points)
        
        if len(curve.points) == 2:
            tck, _ = splprep([points_array[:, 0], points_array[:, 1], points_array[:, 2]], k=1, s=0)
        else:
            tck, _ = splprep([points_array[:, 0], points_array[:, 1], points_array[:, 2]], 
                            k=min(3, len(curve.points)-1), s=0)
        
        total_length = curve.length
        num_points = max(2, int(total_length / step_size))
        t_values = np.linspace(0, 1, num_points)
        
        rx, ry, rz = self.default_orientation
        sampled_points = []
        
        for t in t_values:
            x, y, z = splev(t, tck)
            sampled_points.append(PathPoint(x, y, z, rx, ry, rz, curve_id=curve.curve_id))
        
        return sampled_points
    
    def generate_all_points(self, step_size: float = 0.005) -> None:
        self.all_points = []
        
        rx, ry, rz = self.default_orientation
        
        start_lift = PathPoint(
            self.curves[0].get_start_point()[0],
            self.curves[0].get_start_point()[1],
            self.lift_height,
            rx, ry, rz,
            speed=self.travel_speed,
            acceleration=self.travel_acceleration,
            is_drawing=False,
            curve_id=-1
        )
        self.all_points.append(start_lift)
        
        for i, curve in enumerate(self.curves):
            sampled = self.sample_curve(curve, step_size)
            
            if i > 0:
                prev_end = self.all_points[-1]
                curr_start = sampled[0]
                
                if prev_end.z != self.lift_height:
                    lift_point = PathPoint(
                        prev_end.x, prev_end.y, self.lift_height,
                        rx, ry, rz,
                        speed=self.travel_speed,
                        acceleration=self.travel_acceleration,
                        is_drawing=False,
                        curve_id=-1
                    )
                    self.all_points.append(lift_point)
                
                move_point = PathPoint(
                    curr_start.x, curr_start.y, self.lift_height,
                    rx, ry, rz,
                    speed=self.travel_speed,
                    acceleration=self.travel_acceleration,
                    is_drawing=False,
                    curve_id=-1
                )
                self.all_points.append(move_point)
            
            first_point = sampled[0]
            first_point.speed = self.default_speed
            first_point.acceleration = self.default_acceleration
            first_point.is_drawing = True
            self.all_points.append(first_point)
            
            for point in sampled[1:]:
                point.speed = self.default_speed
                point.acceleration = self.default_acceleration
                point.is_drawing = True
                self.all_points.append(point)
        
        last_point = self.all_points[-1]
        end_lift = PathPoint(
            last_point.x, last_point.y, self.lift_height,
            rx, ry, rz,
            speed=self.travel_speed,
            acceleration=self.travel_acceleration,
            is_drawing=False,
            curve_id=-1
        )
        self.all_points.append(end_lift)
    
    def optimize_path(self) -> None:
        self.sort_curves_by_proximity()
        self.simplify_curves()
        self.transform_to_workspace()
        self.generate_all_points()
    
    def generate_urscript(self, script_name: str = "draw_path") -> str:
        lines = [f"def {script_name}():"]
        lines.append(f"    set_digital_out({self.output_pin}, False)")
        
        for i, point in enumerate(self.all_points):
            if not point.is_drawing:
                lines.append(f"    set_digital_out({self.output_pin}, False)")
                if i > 0:
                    lines.append(f"    movel({point.to_urscript()}, a={point.acceleration}, v={point.speed})")
                else:
                    lines.append(f"    movej({point.to_urscript()}, a={point.acceleration}, v={point.speed})")
            else:
                if i == 0 or not self.all_points[i-1].is_drawing:
                    lines.append(f"    movel({point.to_urscript()}, a={point.acceleration}, v={point.speed})")
                    lines.append(f"    sleep({self.start_delay})")
                    lines.append(f"    set_digital_out({self.output_pin}, True)")
                else:
                    lines.append(f"    set_digital_out({self.output_pin}, True)")
                    lines.append(f"    movel({point.to_urscript()}, a={point.acceleration}, v={point.speed})")
        
        lines.append(f"    sleep({self.end_delay})")
        lines.append(f"    set_digital_out({self.output_pin}, False)")
        lines.append("end")
        lines.append(f"{script_name}()")
        
        return "\n".join(lines)
    
    def save_path_data(self, filepath: str) -> None:
        data = [point.to_dict() for point in self.all_points]
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
    
    def get_trajectory(self) -> List[Dict]:
        return [point.to_dict() for point in self.all_points]
    
    def get_point_count(self) -> int:
        return len(self.all_points)
    
    def get_curve_count(self) -> int:
        return len(self.curves)
    
    def get_total_length(self) -> float:
        return sum(curve.length for curve in self.curves)
    
    def get_bounding_box(self) -> Dict[str, float]:
        if not self.curves:
            return {'min_x': 0, 'max_x': 0, 'min_y': 0, 'max_y': 0, 'min_z': 0, 'max_z': 0}
        
        all_x = []
        all_y = []
        all_z = []
        for curve in self.curves:
            for (x, y, z) in curve.points:
                all_x.append(x)
                all_y.append(y)
                all_z.append(z)
        
        return {
            'min_x': min(all_x), 'max_x': max(all_x),
            'min_y': min(all_y), 'max_y': max(all_y),
            'min_z': min(all_z), 'max_z': max(all_z)
        }