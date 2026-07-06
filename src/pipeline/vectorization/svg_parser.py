from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

from src.core.models import Curve2D, CurveList


Point = tuple[float, float]
Matrix = tuple[float, float, float, float, float, float]

IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
TOKEN_RE = re.compile(r"[AaCcHhLlMmQqSsTtVvZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
TRANSFORM_RE = re.compile(r"([a-zA-Z]+)\(([^)]*)\)")


def parse_svg_to_curve_list(
    svg_path: str | Path,
    *,
    sample_tolerance_px: float = 2.0,
    min_curve_length_px: float = 0.0,
    source_image: str | None = None,
    metadata: dict | None = None,
) -> CurveList:
    path = Path(svg_path)
    root = ET.parse(path).getroot()
    curves: list[Curve2D] = []
    _collect_curves(
        root,
        transform=IDENTITY,
        curves=curves,
        sample_tolerance_px=max(0.2, float(sample_tolerance_px)),
        min_curve_length_px=max(0.0, float(min_curve_length_px)),
    )
    for idx, curve in enumerate(curves):
        curve.curve_id = idx
    return CurveList(
        curves=curves,
        coordinate_frame="image_px",
        metadata={
            "source_image": source_image,
            "source_svg": str(path),
            "svg_parser": "stdlib_svg_path_sampler_v1",
            **(metadata or {}),
        },
    )


def _collect_curves(
    element: ET.Element,
    *,
    transform: Matrix,
    curves: list[Curve2D],
    sample_tolerance_px: float,
    min_curve_length_px: float,
) -> None:
    if _hidden(element):
        return
    local_transform = _multiply(transform, _parse_transform(element.attrib.get("transform", "")))
    tag = _strip_namespace(element.tag)

    produced: list[tuple[list[Point], bool]] = []
    if tag == "path" and element.attrib.get("d"):
        produced = _parse_path_d(element.attrib["d"], sample_tolerance_px)
    elif tag in {"polyline", "polygon"} and element.attrib.get("points"):
        points = _parse_points(element.attrib["points"])
        produced = [(points + ([points[0]] if tag == "polygon" and points else []), tag == "polygon")]
    elif tag == "line":
        produced = [(_line_points(element), False)]
    elif tag == "rect":
        produced = [(_rect_points(element), True)]
    elif tag == "circle":
        produced = [(_ellipse_points(element, circle=True), True)]
    elif tag == "ellipse":
        produced = [(_ellipse_points(element, circle=False), True)]

    for points, closed in produced:
        transformed = [_apply(local_transform, point) for point in points if _finite_point(point)]
        transformed = _dedupe_adjacent(transformed)
        if len(transformed) >= 2 and _curve_length(transformed) >= min_curve_length_px:
            curves.append(
                Curve2D(
                    points=[[float(x), float(y)] for x, y in transformed],
                    closed=closed or _endpoint_distance(transformed) <= 1.5,
                )
            )

    for child in list(element):
        _collect_curves(
            child,
            transform=local_transform,
            curves=curves,
            sample_tolerance_px=sample_tolerance_px,
            min_curve_length_px=min_curve_length_px,
        )


def _parse_path_d(d: str, sample_tolerance_px: float) -> list[tuple[list[Point], bool]]:
    tokens = TOKEN_RE.findall(d.replace(",", " "))
    idx = 0
    command = ""
    current = (0.0, 0.0)
    start = (0.0, 0.0)
    last_cubic_control: Point | None = None
    last_quad_control: Point | None = None
    current_points: list[Point] = []
    paths: list[tuple[list[Point], bool]] = []

    def has_number() -> bool:
        return idx < len(tokens) and not _is_command(tokens[idx])

    def read_number() -> float:
        nonlocal idx
        value = float(tokens[idx])
        idx += 1
        return value

    def read_point(relative: bool) -> Point:
        x = read_number()
        y = read_number()
        return (current[0] + x, current[1] + y) if relative else (x, y)

    def append_point(point: Point) -> None:
        if not current_points:
            current_points.append(current)
        current_points.append(point)

    def finish_path(closed: bool = False) -> None:
        nonlocal current_points
        points = _dedupe_adjacent(current_points)
        if len(points) >= 2:
            paths.append((points, closed))
        current_points = []

    while idx < len(tokens):
        if _is_command(tokens[idx]):
            command = tokens[idx]
            idx += 1
        if not command:
            break

        relative = command.islower()
        op = command.upper()

        if op == "M":
            first = True
            while has_number():
                point = read_point(relative)
                if first:
                    finish_path(False)
                    current = point
                    start = point
                    current_points = [point]
                    first = False
                else:
                    append_point(point)
                    current = point
                last_cubic_control = None
                last_quad_control = None
            command = "l" if relative else "L"
        elif op == "L":
            while has_number():
                point = read_point(relative)
                append_point(point)
                current = point
            last_cubic_control = None
            last_quad_control = None
        elif op == "H":
            while has_number():
                x = read_number()
                point = (current[0] + x, current[1]) if relative else (x, current[1])
                append_point(point)
                current = point
            last_cubic_control = None
            last_quad_control = None
        elif op == "V":
            while has_number():
                y = read_number()
                point = (current[0], current[1] + y) if relative else (current[0], y)
                append_point(point)
                current = point
            last_cubic_control = None
            last_quad_control = None
        elif op == "C":
            while has_number():
                c1 = read_point(relative)
                c2 = read_point(relative)
                end = read_point(relative)
                append_points = _sample_cubic(current, c1, c2, end, sample_tolerance_px)
                for point in append_points[1:]:
                    append_point(point)
                current = end
                last_cubic_control = c2
                last_quad_control = None
        elif op == "S":
            while has_number():
                c1 = _reflect(current, last_cubic_control) if last_cubic_control else current
                c2 = read_point(relative)
                end = read_point(relative)
                append_points = _sample_cubic(current, c1, c2, end, sample_tolerance_px)
                for point in append_points[1:]:
                    append_point(point)
                current = end
                last_cubic_control = c2
                last_quad_control = None
        elif op == "Q":
            while has_number():
                control = read_point(relative)
                end = read_point(relative)
                append_points = _sample_quadratic(current, control, end, sample_tolerance_px)
                for point in append_points[1:]:
                    append_point(point)
                current = end
                last_quad_control = control
                last_cubic_control = None
        elif op == "T":
            while has_number():
                control = _reflect(current, last_quad_control) if last_quad_control else current
                end = read_point(relative)
                append_points = _sample_quadratic(current, control, end, sample_tolerance_px)
                for point in append_points[1:]:
                    append_point(point)
                current = end
                last_quad_control = control
                last_cubic_control = None
        elif op == "A":
            while has_number():
                _rx = read_number()
                _ry = read_number()
                _rotation = read_number()
                _large_arc = read_number()
                _sweep = read_number()
                end = read_point(relative)
                # CLI tracers normally emit cubic paths. Arc fallback keeps geometry connected.
                append_point(end)
                current = end
            last_cubic_control = None
            last_quad_control = None
        elif op == "Z":
            if current_points and _endpoint_distance([current_points[-1], start]) > 0:
                current_points.append(start)
            current = start
            finish_path(True)
            last_cubic_control = None
            last_quad_control = None
            command = ""
        else:
            break

    finish_path(False)
    return paths


def _sample_cubic(p0: Point, p1: Point, p2: Point, p3: Point, tolerance: float) -> list[Point]:
    control_length = _distance(p0, p1) + _distance(p1, p2) + _distance(p2, p3)
    count = max(4, min(96, int(math.ceil(control_length / max(1.0, tolerance * 3.0)))))
    return [
        (
            (1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * p1[0] + 3 * (1 - t) * t**2 * p2[0] + t**3 * p3[0],
            (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * p1[1] + 3 * (1 - t) * t**2 * p2[1] + t**3 * p3[1],
        )
        for t in (idx / count for idx in range(count + 1))
    ]


def _sample_quadratic(p0: Point, p1: Point, p2: Point, tolerance: float) -> list[Point]:
    control_length = _distance(p0, p1) + _distance(p1, p2)
    count = max(4, min(96, int(math.ceil(control_length / max(1.0, tolerance * 3.0)))))
    return [
        (
            (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t**2 * p2[0],
            (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t**2 * p2[1],
        )
        for t in (idx / count for idx in range(count + 1))
    ]


def _parse_transform(value: str) -> Matrix:
    matrix = IDENTITY
    for name, args_text in TRANSFORM_RE.findall(value or ""):
        args = [float(item) for item in re.split(r"[\s,]+", args_text.strip()) if item]
        name = name.lower()
        if name == "matrix" and len(args) >= 6:
            local = (args[0], args[1], args[2], args[3], args[4], args[5])
        elif name == "translate":
            tx = args[0] if args else 0.0
            ty = args[1] if len(args) > 1 else 0.0
            local = (1.0, 0.0, 0.0, 1.0, tx, ty)
        elif name == "scale":
            sx = args[0] if args else 1.0
            sy = args[1] if len(args) > 1 else sx
            local = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        elif name == "rotate":
            angle = math.radians(args[0] if args else 0.0)
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            rotate = (cos_a, sin_a, -sin_a, cos_a, 0.0, 0.0)
            if len(args) >= 3:
                cx, cy = args[1], args[2]
                local = _multiply(_multiply((1.0, 0.0, 0.0, 1.0, cx, cy), rotate), (1.0, 0.0, 0.0, 1.0, -cx, -cy))
            else:
                local = rotate
        else:
            continue
        matrix = _multiply(matrix, local)
    return matrix


def _multiply(first: Matrix, second: Matrix) -> Matrix:
    a1, b1, c1, d1, e1, f1 = first
    a2, b2, c2, d2, e2, f2 = second
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _apply(matrix: Matrix, point: Point) -> Point:
    a, b, c, d, e, f = matrix
    x, y = point
    return (a * x + c * y + e, b * x + d * y + f)


def _parse_points(value: str) -> list[Point]:
    numbers = [float(item) for item in re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", value)]
    return [(numbers[idx], numbers[idx + 1]) for idx in range(0, len(numbers) - 1, 2)]


def _line_points(element: ET.Element) -> list[Point]:
    return [(_attr_float(element, "x1"), _attr_float(element, "y1")), (_attr_float(element, "x2"), _attr_float(element, "y2"))]


def _rect_points(element: ET.Element) -> list[Point]:
    x = _attr_float(element, "x")
    y = _attr_float(element, "y")
    width = _attr_float(element, "width")
    height = _attr_float(element, "height")
    return [(x, y), (x + width, y), (x + width, y + height), (x, y + height), (x, y)]


def _ellipse_points(element: ET.Element, *, circle: bool) -> list[Point]:
    cx = _attr_float(element, "cx")
    cy = _attr_float(element, "cy")
    rx = _attr_float(element, "r" if circle else "rx")
    ry = rx if circle else _attr_float(element, "ry")
    count = 96
    return [(cx + rx * math.cos(2 * math.pi * idx / count), cy + ry * math.sin(2 * math.pi * idx / count)) for idx in range(count + 1)]


def _attr_float(element: ET.Element, name: str, default: float = 0.0) -> float:
    raw = element.attrib.get(name)
    if raw is None:
        return default
    match = re.search(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", raw)
    return float(match.group(0)) if match else default


def _hidden(element: ET.Element) -> bool:
    style = element.attrib.get("style", "")
    return (
        element.attrib.get("display") == "none"
        or element.attrib.get("visibility") == "hidden"
        or "display:none" in style.replace(" ", "")
        or "visibility:hidden" in style.replace(" ", "")
    )


def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _is_command(token: str) -> bool:
    return len(token) == 1 and token.isalpha()


def _reflect(origin: Point, control: Point | None) -> Point:
    if control is None:
        return origin
    return (2 * origin[0] - control[0], 2 * origin[1] - control[1])


def _finite_point(point: Point) -> bool:
    return math.isfinite(point[0]) and math.isfinite(point[1])


def _dedupe_adjacent(points: Iterable[Point]) -> list[Point]:
    output: list[Point] = []
    for point in points:
        if not output or _distance(output[-1], point) > 1e-6:
            output.append(point)
    return output


def _curve_length(points: list[Point]) -> float:
    return sum(_distance(points[idx - 1], points[idx]) for idx in range(1, len(points)))


def _endpoint_distance(points: list[Point]) -> float:
    if len(points) < 2:
        return float("inf")
    return _distance(points[0], points[-1])


def _distance(first: Point, second: Point) -> float:
    return float(math.hypot(first[0] - second[0], first[1] - second[1]))
