from typing import List, Tuple, Optional
import numpy as np
from scipy.interpolate import splprep, splev


def image_to_curves(image_array: np.ndarray,
                    binary_threshold: int = 128,
                    simplify_tolerance: float = 1.0,
                    min_contour_area: int = 50,
                    approximate_epsilon: float = 2.0) -> Optional[List[List[Tuple[float, float]]]]:
    """
    图像处理模块：将输入图像转为有序多段曲线
    
    Args:
        image_array: 输入图像数组（RGB或灰度）
        binary_threshold: 二值化阈值（0-255）
        simplify_tolerance: 简化容差
        min_contour_area: 最小轮廓面积
        approximate_epsilon: 近似精度（Douglas-Peucker算法）
        
    Returns:
        多段曲线列表，每条曲线是二维坐标点的列表
    """
    try:
        import cv2

        if len(image_array.shape) == 3:
            gray = cv2.cvtColor(image_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = image_array.copy()

        _, binary = cv2.threshold(gray, binary_threshold, 255, cv2.THRESH_BINARY_INV)

        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        curves = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_contour_area:
                continue

            contour = contour.reshape(-1, 2)

            if len(contour) > 2:
                simplified = _simplify_curve_dp(contour, approximate_epsilon)
                if len(simplified) >= 3:
                    scaled = [(float(x), float(y)) for x, y in simplified]
                    curves.append(scaled)

        return curves if curves else None

    except Exception as e:
        print(f"图像处理错误: {e}")
        return None


def _simplify_curve_dp(points: np.ndarray, epsilon: float) -> List[Tuple[int, int]]:
    """
    Douglas-Peucker曲线简化算法
    
    Args:
        points: 输入点集
        epsilon: 简化容差
        
    Returns:
        简化后的点集
    """
    if len(points) <= 2:
        return [(int(x), int(y)) for x, y in points]

    d_max = 0.0
    index = 0
    end = len(points) - 1

    for i in range(1, end):
        d = _point_to_segment_distance(points[i], points[0], points[end])
        if d > d_max:
            index = i
            d_max = d

    if d_max > epsilon:
        rec_results1 = _simplify_curve_dp(points[:index+1], epsilon)
        rec_results2 = _simplify_curve_dp(points[index:], epsilon)
        return rec_results1[:-1] + rec_results2
    else:
        return [(int(points[0][0]), int(points[0][1])), (int(points[end][0]), int(points[end][1]))]


def _point_to_segment_distance(point: np.ndarray,
                                line_start: np.ndarray,
                                line_end: np.ndarray) -> float:
    """计算点到线段的距离"""
    px, py = point
    lx1, ly1 = line_start
    lx2, ly2 = line_end

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