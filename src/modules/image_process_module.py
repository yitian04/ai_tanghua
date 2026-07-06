from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Callable, Literal

import cv2
import numpy as np

from src.core.models import Curve2D, CurveList
from src.pipeline.vectorization import parse_svg_to_curve_list, vectorize_binary_with_cli


Point = tuple[float, float]
Curve = list[Point]
ThresholdMethod = Literal["otsu", "adaptive", "manual"]
VectorizerMethod = Literal["mixed_stroke_svg", "skeleton_stroke_svg", "outline_svg", "opencv_fallback"]
OutlineEngine = Literal["auto", "vtracer", "potrace"]
TraceInputMode = Literal["auto", "line_only", "area_only"]
ProgressCallback = Callable[[float, str], None]
DEFAULT_MAX_PROCESS_DIM = 1024


def image_to_curves(
    image: np.ndarray,
    threshold_method: ThresholdMethod = "otsu",
    binary_threshold: int = 128,
    blur_size: int = 3,
    adaptive_block_size: int = 31,
    adaptive_c: int = 5,
    min_component_area: int = 20,
    bridge_gap_px: int = 2,
    min_curve_length_ratio: float = 0.01,
    line_simplify_epsilon: float = 1.2,
    area_simplify_epsilon: float = 2.0,
    min_path_length: int = 8,
    smooth_iterations: int = 0,
    max_vectorize_dim: int = DEFAULT_MAX_PROCESS_DIM,
    stroke_max_width_px: float = 18.0,
    progress_callback: ProgressCallback | None = None,
) -> list[Curve]:
    curve_list = vectorize_image_to_curve_list(
        image=image,
        threshold_method=threshold_method,
        binary_threshold=binary_threshold,
        blur_size=blur_size,
        adaptive_block_size=adaptive_block_size,
        adaptive_c=adaptive_c,
        min_component_area=min_component_area,
        bridge_gap_px=bridge_gap_px,
        min_curve_length_ratio=min_curve_length_ratio,
        line_simplify_epsilon=line_simplify_epsilon,
        area_simplify_epsilon=area_simplify_epsilon,
        min_path_length=min_path_length,
        smooth_iterations=smooth_iterations,
        max_vectorize_dim=max_vectorize_dim,
        stroke_max_width_px=stroke_max_width_px,
        progress_callback=progress_callback,
    )
    return [[(float(x), float(y)) for x, y in curve.points] for curve in curve_list.curves]


def vectorize_image_to_curve_list(
    image: np.ndarray,
    threshold_method: ThresholdMethod = "otsu",
    binary_threshold: int = 128,
    blur_size: int = 3,
    adaptive_block_size: int = 31,
    adaptive_c: int = 5,
    min_component_area: int = 20,
    bridge_gap_px: int = 2,
    min_curve_length_ratio: float = 0.01,
    line_simplify_epsilon: float = 1.2,
    area_simplify_epsilon: float = 2.0,
    min_path_length: int = 8,
    smooth_iterations: int = 0,
    max_vectorize_dim: int = DEFAULT_MAX_PROCESS_DIM,
    stroke_max_width_px: float = 18.0,
    source_image: str | None = None,
    vectorizer: VectorizerMethod = "opencv_fallback",
    outline_engine: OutlineEngine = "auto",
    svg_output_path: str | Path | None = None,
    work_dir: str | Path | None = None,
    cli_timeout_s: int = 45,
    progress_callback: ProgressCallback | None = None,
) -> CurveList:
    if vectorizer in {"mixed_stroke_svg", "skeleton_stroke_svg"}:
        return _vectorize_image_with_mixed_stroke_backend(
            image=image,
            input_mode="line_only" if vectorizer == "skeleton_stroke_svg" else "auto",
            outline_engine=outline_engine,
            threshold_method=threshold_method,
            binary_threshold=binary_threshold,
            blur_size=blur_size,
            adaptive_block_size=adaptive_block_size,
            adaptive_c=adaptive_c,
            min_component_area=min_component_area,
            bridge_gap_px=bridge_gap_px,
            min_curve_length_ratio=min_curve_length_ratio,
            line_simplify_epsilon=line_simplify_epsilon,
            area_simplify_epsilon=area_simplify_epsilon,
            min_path_length=min_path_length,
            smooth_iterations=smooth_iterations,
            max_vectorize_dim=max_vectorize_dim,
            stroke_max_width_px=stroke_max_width_px,
            source_image=source_image,
            svg_output_path=svg_output_path,
            work_dir=work_dir,
            cli_timeout_s=cli_timeout_s,
            progress_callback=progress_callback,
        )

    if vectorizer == "outline_svg":
        return _vectorize_image_with_svg_backend(
            image=image,
            vectorizer=vectorizer,
            outline_engine=outline_engine,
            threshold_method=threshold_method,
            binary_threshold=binary_threshold,
            blur_size=blur_size,
            adaptive_block_size=adaptive_block_size,
            adaptive_c=adaptive_c,
            bridge_gap_px=bridge_gap_px,
            min_curve_length_ratio=min_curve_length_ratio,
            line_simplify_epsilon=line_simplify_epsilon,
            source_image=source_image,
            svg_output_path=svg_output_path,
            work_dir=work_dir,
            cli_timeout_s=cli_timeout_s,
            max_vectorize_dim=max_vectorize_dim,
            progress_callback=progress_callback,
        )

    _report(progress_callback, 0.05, "二值化")
    work_image, coordinate_scale = _resize_for_vectorization(image, max_vectorize_dim=max_vectorize_dim)
    binary = threshold_image(
        work_image,
        method=threshold_method,
        binary_threshold=binary_threshold,
        blur_size=blur_size,
        adaptive_block_size=adaptive_block_size,
        adaptive_c=adaptive_c,
    )
    binary = bridge_small_gaps(binary, bridge_gap_px=bridge_gap_px)
    analysis = analyze_binary_content(binary, min_component_area=min_component_area)
    components = analysis["components"]
    curves: list[Curve2D] = []
    min_curve_length_px = _image_min_curve_length_px(work_image, min_curve_length_ratio)
    _report(progress_callback, 0.25, "线/面分类完成")

    for idx, component in enumerate(components):
        mask = component["mask"]
        x0 = int(component["x"])
        y0 = int(component["y"])
        if component["content_type"] == "line":
            raw_curves = _line_component_to_curves(
                mask,
                offset=(x0, y0),
                simplify_epsilon=line_simplify_epsilon,
                min_path_length=min_path_length,
                min_curve_length_px=min_curve_length_px,
                smooth_iterations=smooth_iterations,
                force_single_path=float(component["bbox_aspect"]) >= 2.8,
            )
            closed = False
        else:
            raw_curves = _area_component_to_curves(
                mask,
                offset=(x0, y0),
                simplify_epsilon=area_simplify_epsilon,
                min_curve_length_px=min_curve_length_px,
            )
            closed = True

        for raw in raw_curves:
            if len(raw) >= 2 and _curve_length(raw) >= min_curve_length_px:
                if coordinate_scale != 1.0:
                    raw = [(x * coordinate_scale, y * coordinate_scale) for x, y in raw]
                curves.append(
                    Curve2D(
                        points=[[float(x), float(y)] for x, y in raw],
                        curve_id=len(curves),
                        closed=closed,
                    )
                )
        _report(progress_callback, 0.25 + 0.7 * ((idx + 1) / max(1, len(components))), "曲线提取")

    min_output_length_px = _image_min_curve_length_px(image, min_curve_length_ratio)
    curves = _postprocess_curve2d(curves, min_length_px=min_output_length_px, overlap_tolerance_px=max(2.0, min_output_length_px * 0.18))

    metadata = {
        "source_image": source_image,
        "vectorizer": "connected_component_skeleton_diameter_v1",
        "threshold_method": threshold_method,
        "binary_threshold": int(binary_threshold),
        "blur_size": int(blur_size),
        "adaptive_block_size": int(adaptive_block_size),
        "adaptive_c": int(adaptive_c),
        "min_component_area": int(min_component_area),
        "bridge_gap_px": int(bridge_gap_px),
        "min_curve_length_ratio": float(min_curve_length_ratio),
        "min_curve_length_px": float(min_curve_length_px),
        "line_simplify_epsilon": float(line_simplify_epsilon),
        "area_simplify_epsilon": float(area_simplify_epsilon),
        "min_path_length": int(min_path_length),
        "smooth_iterations": int(smooth_iterations),
        "max_vectorize_dim": int(max_vectorize_dim),
        "coordinate_scale": float(coordinate_scale),
        "original_image_size": [int(image.shape[1]), int(image.shape[0])],
        "processing_image_size": [int(work_image.shape[1]), int(work_image.shape[0])],
        "component_count": int(analysis["component_count"]),
        "line_component_count": int(analysis["line_component_count"]),
        "area_component_count": int(analysis["area_component_count"]),
    }
    _report(progress_callback, 1.0, "曲线生成完成")
    return CurveList(curves=curves, coordinate_frame="image_px", metadata=metadata)


def _vectorize_image_with_mixed_stroke_backend(
    image: np.ndarray,
    *,
    input_mode: TraceInputMode,
    outline_engine: OutlineEngine,
    threshold_method: ThresholdMethod,
    binary_threshold: int,
    blur_size: int,
    adaptive_block_size: int,
    adaptive_c: int,
    min_component_area: int,
    bridge_gap_px: int,
    min_curve_length_ratio: float,
    line_simplify_epsilon: float,
    area_simplify_epsilon: float,
    min_path_length: int,
    smooth_iterations: int,
    max_vectorize_dim: int,
    stroke_max_width_px: float,
    source_image: str | None,
    svg_output_path: str | Path | None,
    work_dir: str | Path | None,
    cli_timeout_s: int,
    progress_callback: ProgressCallback | None,
) -> CurveList:
    _report(progress_callback, 0.05, "resize and threshold")
    work_image, coordinate_scale = _resize_for_vectorization(image, max_vectorize_dim=max_vectorize_dim)
    binary = threshold_image(
        work_image,
        method=threshold_method,
        binary_threshold=binary_threshold,
        blur_size=blur_size,
        adaptive_block_size=adaptive_block_size,
        adaptive_c=adaptive_c,
    )
    binary = bridge_small_gaps(binary, bridge_gap_px=bridge_gap_px)
    components = _classify_components_by_mode(
        binary,
        min_component_area=min_component_area,
        input_mode=input_mode,
        stroke_max_width_px=stroke_max_width_px,
    )
    line_components = [component for component in components if component["content_type"] == "line"]
    area_components = [component for component in components if component["content_type"] == "area"]
    min_curve_length_px = _image_min_curve_length_px(work_image, min_curve_length_ratio)

    curves: list[Curve2D] = []
    _report(progress_callback, 0.2, "extract centerline strokes")
    for idx, component in enumerate(line_components):
        raw_curves = _line_component_to_curves(
            component["mask"],
            offset=(int(component["x"]), int(component["y"])),
            simplify_epsilon=line_simplify_epsilon,
            min_path_length=min_path_length,
            min_curve_length_px=min_curve_length_px,
            smooth_iterations=smooth_iterations,
            force_single_path=float(component["bbox_aspect"]) >= 2.8,
        )
        for raw in raw_curves:
            if len(raw) >= 2 and _curve_length(raw) >= min_curve_length_px:
                curves.append(Curve2D(points=[[float(x), float(y)] for x, y in raw], curve_id=len(curves), closed=False))
        _report(progress_callback, 0.2 + 0.35 * ((idx + 1) / max(1, len(line_components))), "extract centerline strokes")

    area_backend = "none"
    area_warning = ""
    if area_components:
        _report(progress_callback, 0.6, "extract outlined areas")
        area_binary = _components_to_binary(area_components, binary.shape)
        try:
            area_svg = vectorize_binary_with_cli(
                area_binary,
                vectorizer="outline_svg",
                outline_engine=outline_engine,
                work_dir=work_dir,
                svg_output_path=None,
                timeout_s=cli_timeout_s,
                speckle_size=max(1, int(round(min_curve_length_px * 0.25))),
            )
            area_curve_list = parse_svg_to_curve_list(
                area_svg,
                sample_tolerance_px=max(0.5, float(area_simplify_epsilon)),
                min_curve_length_px=min_curve_length_px,
                source_image=source_image,
                metadata={},
            )
            for curve in area_curve_list.curves:
                curve.closed = True if curve.closed or _endpoint_distance(_curve_points(curve)) <= 3.0 else curve.closed
                curves.append(Curve2D(points=curve.points, curve_id=len(curves), closed=curve.closed))
            area_backend = "outline_svg"
        except Exception as exc:
            area_warning = str(exc)
            area_backend = "opencv_contour_fallback"
            for component in area_components:
                raw_curves = _area_component_to_curves(
                    component["mask"],
                    offset=(int(component["x"]), int(component["y"])),
                    simplify_epsilon=area_simplify_epsilon,
                    min_curve_length_px=min_curve_length_px,
                )
                for raw in raw_curves:
                    if len(raw) >= 2 and _curve_length(raw) >= min_curve_length_px:
                        curves.append(Curve2D(points=[[float(x), float(y)] for x, y in raw], curve_id=len(curves), closed=True))

    if coordinate_scale != 1.0:
        curves = [_scale_curve2d(curve, coordinate_scale) for curve in curves]
    min_output_length_px = _image_min_curve_length_px(image, min_curve_length_ratio)
    curves = _postprocess_curve2d(curves, min_length_px=min_output_length_px, overlap_tolerance_px=max(2.0, min_output_length_px * 0.18))
    for idx, curve in enumerate(curves):
        curve.curve_id = idx

    metadata = {
        "source_image": source_image,
        "vectorizer": "mixed_stroke_skeleton_v1",
        "input_mode": input_mode,
        "outline_engine": outline_engine,
        "area_backend": area_backend,
        "area_warning": area_warning,
        "threshold_method": threshold_method,
        "binary_threshold": int(binary_threshold),
        "blur_size": int(blur_size),
        "adaptive_block_size": int(adaptive_block_size),
        "adaptive_c": int(adaptive_c),
        "min_component_area": int(min_component_area),
        "bridge_gap_px": int(bridge_gap_px),
        "stroke_max_width_px": float(stroke_max_width_px),
        "min_curve_length_ratio": float(min_curve_length_ratio),
        "line_simplify_epsilon": float(line_simplify_epsilon),
        "area_simplify_epsilon": float(area_simplify_epsilon),
        "min_path_length": int(min_path_length),
        "smooth_iterations": int(smooth_iterations),
        "max_vectorize_dim": int(max_vectorize_dim),
        "coordinate_scale": float(coordinate_scale),
        "original_image_size": [int(image.shape[1]), int(image.shape[0])],
        "processing_image_size": [int(work_image.shape[1]), int(work_image.shape[0])],
        "component_count": int(len(components)),
        "line_component_count": int(len(line_components)),
        "area_component_count": int(len(area_components)),
    }
    curve_list = CurveList(curves=curves, coordinate_frame="image_px", metadata=metadata)
    if svg_output_path is not None:
        _export_stroke_svg(curve_list, svg_output_path, width=int(image.shape[1]), height=int(image.shape[0]))
        curve_list.metadata["stroke_svg_output_path"] = str(svg_output_path)
    _report(progress_callback, 1.0, "curves generated")
    return curve_list

def _vectorize_image_with_svg_backend(
    image: np.ndarray,
    *,
    vectorizer: VectorizerMethod,
    outline_engine: OutlineEngine,
    threshold_method: ThresholdMethod,
    binary_threshold: int,
    blur_size: int,
    adaptive_block_size: int,
    adaptive_c: int,
    bridge_gap_px: int,
    min_curve_length_ratio: float,
    line_simplify_epsilon: float,
    source_image: str | None,
    svg_output_path: str | Path | None,
    work_dir: str | Path | None,
    cli_timeout_s: int,
    max_vectorize_dim: int,
    progress_callback: ProgressCallback | None,
) -> CurveList:
    _report(progress_callback, 0.05, "缩放并二值化")
    work_image, coordinate_scale = _resize_for_vectorization(image, max_vectorize_dim=max_vectorize_dim)
    binary = threshold_image(
        work_image,
        method=threshold_method,
        binary_threshold=binary_threshold,
        blur_size=blur_size,
        adaptive_block_size=adaptive_block_size,
        adaptive_c=adaptive_c,
    )
    binary = bridge_small_gaps(binary, bridge_gap_px=bridge_gap_px)
    min_curve_length_px = _image_min_curve_length_px(work_image, min_curve_length_ratio)

    _report(progress_callback, 0.25, "调用 SVG 向量化后端")
    svg_path = vectorize_binary_with_cli(
        binary,
        vectorizer=vectorizer,  # type: ignore[arg-type]
        outline_engine=outline_engine,
        work_dir=work_dir,
        svg_output_path=svg_output_path,
        timeout_s=cli_timeout_s,
        speckle_size=max(1, int(round(min_curve_length_px * 0.25))),
    )

    _report(progress_callback, 0.75, "解析 SVG 曲线")
    curve_list = parse_svg_to_curve_list(
        svg_path,
        sample_tolerance_px=max(0.5, float(line_simplify_epsilon)),
        min_curve_length_px=min_curve_length_px,
        source_image=source_image,
        metadata={
            "vectorizer": vectorizer,
            "outline_engine": outline_engine,
            "threshold_method": threshold_method,
            "binary_threshold": int(binary_threshold),
            "blur_size": int(blur_size),
            "adaptive_block_size": int(adaptive_block_size),
            "adaptive_c": int(adaptive_c),
            "bridge_gap_px": int(bridge_gap_px),
            "min_curve_length_ratio": float(min_curve_length_ratio),
            "min_curve_length_px": float(min_curve_length_px),
            "svg_output_path": str(svg_path),
        },
    )
    if coordinate_scale != 1.0:
        curve_list.curves = [_scale_curve2d(curve, coordinate_scale) for curve in curve_list.curves]
    min_output_length_px = _image_min_curve_length_px(image, min_curve_length_ratio)
    curves = _postprocess_curve2d(
        curve_list.curves,
        min_length_px=min_output_length_px,
        overlap_tolerance_px=max(2.0, min_output_length_px * 0.18),
    )
    curve_list.curves = curves
    if svg_output_path is not None:
        _export_stroke_svg(curve_list, svg_output_path, width=int(image.shape[1]), height=int(image.shape[0]))
        curve_list.metadata["stroke_svg_output_path"] = str(svg_output_path)
    curve_list.metadata["max_vectorize_dim"] = int(max_vectorize_dim)
    curve_list.metadata["coordinate_scale"] = float(coordinate_scale)
    curve_list.metadata["original_image_size"] = [int(image.shape[1]), int(image.shape[0])]
    curve_list.metadata["processing_image_size"] = [int(work_image.shape[1]), int(work_image.shape[0])]
    curve_list.metadata["curve_count_after_postprocess"] = len(curves)
    _report(progress_callback, 1.0, "曲线生成完成")
    return curve_list


def create_binary_preview(
    image: np.ndarray,
    threshold_method: ThresholdMethod = "otsu",
    binary_threshold: int = 128,
    blur_size: int = 3,
    adaptive_block_size: int = 31,
    adaptive_c: int = 5,
    min_component_area: int = 20,
    bridge_gap_px: int = 2,
    max_preview_dim: int = DEFAULT_MAX_PROCESS_DIM,
    input_mode: TraceInputMode = "auto",
    stroke_max_width_px: float = 18.0,
) -> tuple[np.ndarray, dict]:
    work_image, coordinate_scale = _resize_for_vectorization(image, max_vectorize_dim=max_preview_dim)
    binary = threshold_image(
        work_image,
        method=threshold_method,
        binary_threshold=binary_threshold,
        blur_size=blur_size,
        adaptive_block_size=adaptive_block_size,
        adaptive_c=adaptive_c,
    )
    binary = bridge_small_gaps(binary, bridge_gap_px=bridge_gap_px)
    analysis = analyze_binary_content(binary, min_component_area=min_component_area)
    analysis["components"] = _classify_components_by_mode(binary, min_component_area=min_component_area, input_mode=input_mode, stroke_max_width_px=stroke_max_width_px)
    preview = np.full((*binary.shape, 3), 255, dtype=np.uint8)
    for component in analysis["components"]:
        color = (0, 0, 0) if component["content_type"] == "line" else (150, 150, 150)
        x = int(component["x"])
        y = int(component["y"])
        mask = component["mask"] > 0
        preview[y : y + mask.shape[0], x : x + mask.shape[1]][mask] = color
    public_analysis = _public_analysis(analysis)
    public_analysis["max_preview_dim"] = int(max_preview_dim)
    public_analysis["input_mode"] = input_mode
    public_analysis["stroke_max_width_px"] = float(stroke_max_width_px)
    public_analysis["line_component_count"] = sum(1 for item in public_analysis["components"] if item["content_type"] == "line")
    public_analysis["area_component_count"] = sum(1 for item in public_analysis["components"] if item["content_type"] == "area")
    public_analysis["coordinate_scale"] = float(coordinate_scale)
    public_analysis["original_image_size"] = [int(image.shape[1]), int(image.shape[0])] if image is not None and image.size else [0, 0]
    public_analysis["processing_image_size"] = [int(work_image.shape[1]), int(work_image.shape[0])] if work_image is not None and work_image.size else [0, 0]
    return preview, public_analysis


def threshold_image(
    image: np.ndarray,
    method: ThresholdMethod = "otsu",
    binary_threshold: int = 128,
    blur_size: int = 3,
    adaptive_block_size: int = 31,
    adaptive_c: int = 5,
) -> np.ndarray:
    if image is None or image.size == 0:
        return np.empty((0, 0), dtype=np.uint8)

    if image.ndim == 2:
        gray = image
    elif image.shape[2] == 4:
        gray = cv2.cvtColor(image, cv2.COLOR_RGBA2GRAY)
    else:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)

    if blur_size and blur_size > 1:
        kernel = _odd_at_least(blur_size, 3)
        gray = cv2.GaussianBlur(gray, (kernel, kernel), 0)

    if method == "adaptive":
        block = _odd_at_least(adaptive_block_size, 3)
        return cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            block,
            int(adaptive_c),
        )

    if method == "manual":
        threshold = max(0, min(255, int(binary_threshold)))
        _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)
        return binary

    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    return binary


def bridge_small_gaps(binary: np.ndarray, bridge_gap_px: int = 2) -> np.ndarray:
    gap = max(0, int(bridge_gap_px))
    if gap <= 0 or binary.size == 0:
        return binary
    kernel_size = gap * 2 + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    return closed


def _resize_for_vectorization(image: np.ndarray, max_vectorize_dim: int) -> tuple[np.ndarray, float]:
    if image is None or image.size == 0:
        return image, 1.0
    max_dim = max(image.shape[:2])
    limit = max(128, int(max_vectorize_dim))
    if max_dim <= limit:
        return image, 1.0
    scale = limit / float(max_dim)
    width = max(1, int(round(image.shape[1] * scale)))
    height = max(1, int(round(image.shape[0] * scale)))
    resized = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    return resized, 1.0 / scale


def analyze_binary_content(binary: np.ndarray, min_component_area: int = 20) -> dict:
    components = _extract_components(binary, min_component_area=min_component_area)
    line_count = sum(1 for item in components if item["content_type"] == "line")
    area_count = sum(1 for item in components if item["content_type"] == "area")
    if not components:
        content_type = "empty"
        label = "空图"
    elif line_count and area_count:
        content_type = "mixed"
        label = "线/面混合"
    elif line_count:
        content_type = "line"
        label = "线稿"
    else:
        content_type = "area"
        label = "面/填充图形"

    widths = [float(item["p90_stroke_width_px"]) for item in components]
    return {
        "content_type": content_type,
        "content_type_label": label,
        "component_count": len(components),
        "line_component_count": line_count,
        "area_component_count": area_count,
        "p90_stroke_width_px": float(np.median(widths)) if widths else 0.0,
        "components": components,
    }


def _extract_components(binary: np.ndarray, min_component_area: int) -> list[dict]:
    if binary is None or binary.size == 0:
        return []

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats((binary > 0).astype(np.uint8), connectivity=8)
    components: list[dict] = []
    for label_id in range(1, num_labels):
        x, y, width, height, area = [int(value) for value in stats[label_id]]
        if area < min_component_area or width <= 0 or height <= 0:
            continue
        mask = (labels[y : y + height, x : x + width] == label_id).astype(np.uint8) * 255
        features = _component_features(mask, width=width, height=height, area=area)
        components.append(
            {
                "label_id": label_id,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "area": area,
                "mask": mask,
                **features,
            }
        )
    components.sort(key=lambda item: (int(item["y"]), int(item["x"])))
    return components


def _component_features(mask: np.ndarray, width: int, height: int, area: int) -> dict:
    padded = np.pad(mask > 0, pad_width=1, mode="constant", constant_values=False)
    distance = cv2.distanceTransform((padded.astype(np.uint8) * 255), cv2.DIST_L2, 3).astype(np.float32)
    radii = distance[padded].astype(np.float32)
    median_width = float(np.median(radii) * 2.0) if radii.size else 0.0
    p90_width = float(np.percentile(radii, 90) * 2.0) if radii.size else 0.0
    max_width = float(np.max(radii) * 2.0) if radii.size else 0.0
    major = float(max(width, height))
    minor = float(max(1, min(width, height)))
    aspect = major / minor
    fill_ratio = float(area / max(1, width * height))
    stroke_to_major = p90_width / max(1.0, major)

    is_line = (
        aspect >= 2.8
        or (stroke_to_major <= 0.20 and fill_ratio <= 0.78)
        or (p90_width <= 14.0 and fill_ratio <= 0.72)
    )
    return {
        "content_type": "line" if is_line else "area",
        "content_type_label": "线稿" if is_line else "面/填充图形",
        "fill_ratio": fill_ratio,
        "bbox_aspect": aspect,
        "median_stroke_width_px": median_width,
        "p90_stroke_width_px": p90_width,
        "max_stroke_width_px": max_width,
    }


def _classify_components_by_mode(
    binary: np.ndarray,
    *,
    min_component_area: int,
    input_mode: TraceInputMode,
    stroke_max_width_px: float,
) -> list[dict]:
    components = _extract_components(binary, min_component_area=min_component_area)
    classified: list[dict] = []
    max_width = max(0.0, float(stroke_max_width_px))
    for component in components:
        item = dict(component)
        if input_mode == "line_only":
            is_line = True
        elif input_mode == "area_only":
            is_line = False
        else:
            is_line = float(item.get("p90_stroke_width_px", 0.0)) <= max_width
        item["content_type"] = "line" if is_line else "area"
        item["content_type_label"] = "line" if is_line else "area"
        classified.append(item)
    return classified


def _components_to_binary(components: list[dict], shape: tuple[int, int]) -> np.ndarray:
    output = np.zeros(shape, dtype=np.uint8)
    for component in components:
        x = int(component["x"])
        y = int(component["y"])
        mask = component["mask"] > 0
        output[y : y + mask.shape[0], x : x + mask.shape[1]][mask] = 255
    return output


def _export_stroke_svg(curve_list: CurveList, path: str | Path, *, width: int, height: int) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<g fill="none" stroke="#000000" stroke-width="1" stroke-linecap="round" stroke-linejoin="round">',
    ]
    for curve in curve_list.curves:
        if len(curve.points) < 2:
            continue
        d = _curve_to_svg_path_d(curve)
        if d:
            lines.append(f'<path d="{d}" data-curve-id="{int(curve.curve_id)}" data-closed="{str(bool(curve.closed)).lower()}"/>')
    lines.extend(['</g>', '</svg>'])
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def _curve_to_svg_path_d(curve: Curve2D) -> str:
    points = _curve_points(curve)
    if len(points) < 2:
        return ""
    parts = [f'M {points[0][0]:.3f} {points[0][1]:.3f}']
    parts.extend(f'L {point[0]:.3f} {point[1]:.3f}' for point in points[1:])
    if curve.closed:
        parts.append('Z')
    return " ".join(parts)

def _image_min_curve_length_px(image: np.ndarray, min_curve_length_ratio: float) -> float:
    if image is None or image.size == 0:
        return 0.0
    height, width = image.shape[:2]
    diagonal = float(np.hypot(width, height))
    return max(0.0, diagonal * max(0.0, float(min_curve_length_ratio)))


def _line_component_to_curves(
    mask: np.ndarray,
    offset: tuple[int, int],
    simplify_epsilon: float,
    min_path_length: int,
    min_curve_length_px: float,
    smooth_iterations: int,
    force_single_path: bool,
) -> list[Curve]:
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8))
    skeleton = _thin_binary(closed > 0)
    branch_count = _skeleton_branch_count(skeleton)
    effective_min_path_length = max(int(min_path_length), int(np.ceil(min_curve_length_px)))
    if _skeleton_is_cycle_like(skeleton):
        paths = _skeleton_to_cycle_paths(skeleton, min_path_length=effective_min_path_length)
    elif force_single_path or branch_count == 0:
        paths = _skeleton_to_diameter_paths(skeleton, min_path_length=effective_min_path_length)
        paths = [max(paths, key=len)] if paths else []
    else:
        paths = _skeleton_to_branch_paths(skeleton, min_path_length=effective_min_path_length)
    curves: list[Curve] = []
    for path in paths:
        points = [(float(x + offset[0]), float(y + offset[1])) for y, x in path]
        points = _simplify_curve(points, simplify_epsilon)
        points = _chaikin(points, iterations=smooth_iterations)
        if len(points) >= 2 and _curve_length(points) >= min_curve_length_px:
            curves.append(points)
    return curves


def _area_component_to_curves(
    mask: np.ndarray,
    offset: tuple[int, int],
    simplify_epsilon: float,
    min_curve_length_px: float,
) -> list[Curve]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    curves: list[Curve] = []
    for contour in contours:
        if len(contour) < 2:
            continue
        points = [(float(point[0][0] + offset[0]), float(point[0][1] + offset[1])) for point in contour]
        points = _simplify_curve(points, simplify_epsilon)
        if len(points) >= 3 and _curve_length(points) >= min_curve_length_px:
            curves.append(points)
    return curves


def _thin_binary(binary: np.ndarray) -> np.ndarray:
    ximgproc = getattr(cv2, "ximgproc", None)
    if ximgproc is not None and hasattr(ximgproc, "thinning"):
        return ximgproc.thinning((binary > 0).astype(np.uint8) * 255) > 0
    return _zhang_suen_thinning(binary)


def _morphological_skeleton(binary: np.ndarray) -> np.ndarray:
    image = (binary > 0).astype(np.uint8) * 255
    skeleton = np.zeros(image.shape, dtype=np.uint8)
    element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    max_iter = int(image.shape[0] + image.shape[1])
    for _ in range(max_iter):
        opened = cv2.morphologyEx(image, cv2.MORPH_OPEN, element)
        temp = cv2.subtract(image, opened)
        skeleton = cv2.bitwise_or(skeleton, temp)
        image = cv2.erode(image, element)
        if cv2.countNonZero(image) == 0:
            break
    return skeleton > 0


def _skeleton_branch_count(skeleton: np.ndarray) -> int:
    pixels = {tuple(point) for point in np.argwhere(skeleton)}
    return sum(1 for pixel in pixels if _degree(pixel, pixels) >= 3)


def _skeleton_has_endpoints(skeleton: np.ndarray) -> bool:
    pixels = {tuple(point) for point in np.argwhere(skeleton)}
    return any(_degree(pixel, pixels) <= 1 for pixel in pixels)


def _skeleton_is_cycle_like(skeleton: np.ndarray) -> bool:
    pixels = {tuple(point) for point in np.argwhere(skeleton)}
    if len(pixels) < 12:
        return False
    degrees = [_degree(pixel, pixels) for pixel in pixels]
    degree_two_ratio = sum(1 for degree in degrees if degree == 2) / len(degrees)
    weak_endpoint_count = sum(1 for degree in degrees if degree <= 1)
    branch_count = sum(1 for degree in degrees if degree >= 3)
    return degree_two_ratio >= 0.75 and weak_endpoint_count <= 6 and branch_count <= max(80, int(len(pixels) * 0.25))


def _zhang_suen_thinning(binary: np.ndarray) -> np.ndarray:
    image = (binary > 0).astype(np.uint8)
    changed = True
    while changed:
        changed = False
        for step in (0, 1):
            remove: list[tuple[int, int]] = []
            rows, cols = image.shape
            for y in range(1, rows - 1):
                for x in range(1, cols - 1):
                    if image[y, x] == 0:
                        continue
                    p2, p3, p4, p5, p6, p7, p8, p9 = _ordered_neighbors(image, y, x)
                    neighbor_count = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
                    if neighbor_count < 2 or neighbor_count > 6:
                        continue
                    if _zero_to_one_transitions((p2, p3, p4, p5, p6, p7, p8, p9)) != 1:
                        continue
                    if step == 0 and (p2 * p4 * p6 != 0 or p4 * p6 * p8 != 0):
                        continue
                    if step == 1 and (p2 * p4 * p8 != 0 or p2 * p6 * p8 != 0):
                        continue
                    remove.append((y, x))
            if remove:
                changed = True
                for y, x in remove:
                    image[y, x] = 0
    return image.astype(bool)


def _skeleton_to_diameter_paths(skeleton: np.ndarray, min_path_length: int) -> list[list[tuple[int, int]]]:
    pixels = {tuple(point) for point in np.argwhere(skeleton)}
    paths: list[list[tuple[int, int]]] = []
    while pixels:
        component = _take_pixel_component(pixels)
        remaining = set(component)
        component_size = len(component)
        while remaining:
            path = _diameter_path(remaining)
            if len(path) < max(2, min_path_length):
                break
            paths.append(path)
            remaining.difference_update(path)
            remaining = _largest_remaining_component(remaining)
            if len(remaining) < max(min_path_length * 3, int(component_size * 0.25)):
                break
    return paths


def _skeleton_to_cycle_paths(skeleton: np.ndarray, min_path_length: int) -> list[list[tuple[int, int]]]:
    pixels = {tuple(point) for point in np.argwhere(skeleton)}
    paths: list[list[tuple[int, int]]] = []
    for component in _pixel_components(pixels):
        if len(component) < min_path_length:
            continue
        endpoints = [pixel for pixel in component if _degree(pixel, component) <= 1]
        if endpoints:
            path = _diameter_path(component)
        else:
            path = _trace_cycle(component)
        if len(path) >= min_path_length:
            paths.append(path)
    return paths


def _trace_cycle(component: set[tuple[int, int]]) -> list[tuple[int, int]]:
    start = min(component)
    neighbors = [neighbor for neighbor in _pixel_neighbors(start) if neighbor in component]
    if not neighbors:
        return [start]
    previous = start
    current = min(neighbors)
    path = [start]
    visited_edges = {_edge_key(start, current)}
    while True:
        path.append(current)
        candidates = [
            neighbor
            for neighbor in _pixel_neighbors(current)
            if neighbor in component and neighbor != previous and _edge_key(current, neighbor) not in visited_edges
        ]
        if not candidates:
            break
        next_pixel = _choose_cycle_next(previous, current, candidates)
        if next_pixel == start:
            path.append(start)
            break
        visited_edges.add(_edge_key(current, next_pixel))
        previous, current = current, next_pixel
    if path[-1] != path[0]:
        path.append(path[0])
    return path


def _choose_cycle_next(
    previous: tuple[int, int],
    current: tuple[int, int],
    candidates: list[tuple[int, int]],
) -> tuple[int, int]:
    in_vec = (current[0] - previous[0], current[1] - previous[1])
    return max(
        candidates,
        key=lambda item: (item[0] - current[0]) * in_vec[0] + (item[1] - current[1]) * in_vec[1],
    )


def _skeleton_to_branch_paths(skeleton: np.ndarray, min_path_length: int) -> list[list[tuple[int, int]]]:
    pixels = {tuple(point) for point in np.argwhere(skeleton)}
    if not pixels:
        return []

    node_pixels = {pixel for pixel in pixels if _degree(pixel, pixels) != 2}
    if not node_pixels:
        return _skeleton_to_cycle_paths(skeleton, min_path_length=min_path_length)

    node_clusters = _cluster_node_pixels(node_pixels)
    node_map = {pixel: idx for idx, cluster in enumerate(node_clusters) for pixel in cluster}
    edge_pixels = pixels - node_pixels
    paths: list[list[tuple[int, int]]] = []

    for edge_component in _pixel_components(edge_pixels):
        adjacent_nodes = _adjacent_node_ids(edge_component, node_map)
        if not adjacent_nodes:
            path = _diameter_path(edge_component)
        elif len(adjacent_nodes) == 1:
            path = _edge_component_to_terminal_path(edge_component, adjacent_nodes[0], node_clusters, node_map)
        else:
            start_id, end_id = _farthest_node_pair(adjacent_nodes, node_clusters)
            path = _edge_component_to_node_path(edge_component, start_id, end_id, node_clusters, node_map)
        if len(path) >= 2:
            paths.append(path)

    if not paths:
        return _skeleton_to_diameter_paths(skeleton, min_path_length=min_path_length)
    paths = _merge_continuation_paths(_dedupe_paths(paths))
    return [path for path in _dedupe_paths(paths) if len(path) >= min_path_length]


def _cluster_node_pixels(node_pixels: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
    return _pixel_components(node_pixels)


def _pixel_components(pixels: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
    components: list[set[tuple[int, int]]] = []
    pool = set(pixels)
    while pool:
        components.append(_take_pixel_component(pool))
    return components


def _adjacent_node_ids(edge_component: set[tuple[int, int]], node_map: dict[tuple[int, int], int]) -> list[int]:
    ids = {
        node_map[neighbor]
        for pixel in edge_component
        for neighbor in _pixel_neighbors(pixel)
        if neighbor in node_map
    }
    return sorted(ids)


def _edge_component_to_node_path(
    edge_component: set[tuple[int, int]],
    start_id: int,
    end_id: int,
    node_clusters: list[set[tuple[int, int]]],
    node_map: dict[tuple[int, int], int],
) -> list[tuple[int, int]]:
    start_pixel = _closest_edge_pixel_to_node(edge_component, start_id, node_map)
    end_pixel = _closest_edge_pixel_to_node(edge_component, end_id, node_map)
    inner = _shortest_path(start_pixel, end_pixel, edge_component)
    return [_node_center(node_clusters[start_id])] + inner + [_node_center(node_clusters[end_id])]


def _edge_component_to_terminal_path(
    edge_component: set[tuple[int, int]],
    node_id: int,
    node_clusters: list[set[tuple[int, int]]],
    node_map: dict[tuple[int, int], int],
) -> list[tuple[int, int]]:
    start_pixel = _closest_edge_pixel_to_node(edge_component, node_id, node_map)
    end_pixel, _ = _farthest_pixel(start_pixel, edge_component)
    inner = _shortest_path(start_pixel, end_pixel, edge_component)
    return [_node_center(node_clusters[node_id])] + inner


def _closest_edge_pixel_to_node(
    edge_component: set[tuple[int, int]],
    node_id: int,
    node_map: dict[tuple[int, int], int],
) -> tuple[int, int]:
    candidates = [
        pixel
        for pixel in edge_component
        if any(node_map.get(neighbor) == node_id for neighbor in _pixel_neighbors(pixel))
    ]
    return candidates[0] if candidates else next(iter(edge_component))


def _farthest_node_pair(node_ids: list[int], node_clusters: list[set[tuple[int, int]]]) -> tuple[int, int]:
    best = (node_ids[0], node_ids[-1])
    best_distance = -1
    centers = {node_id: _node_center(node_clusters[node_id]) for node_id in node_ids}
    for idx, first in enumerate(node_ids):
        for second in node_ids[idx + 1 :]:
            distance = (centers[first][0] - centers[second][0]) ** 2 + (centers[first][1] - centers[second][1]) ** 2
            if distance > best_distance:
                best = (first, second)
                best_distance = distance
    return best


def _direct_node_cluster_paths(
    node_clusters: list[set[tuple[int, int]]],
    node_map: dict[tuple[int, int], int],
    pixels: set[tuple[int, int]],
) -> list[list[tuple[int, int]]]:
    paths: list[list[tuple[int, int]]] = []
    seen: set[tuple[int, int]] = set()
    for pixel, first_id in node_map.items():
        for neighbor in _pixel_neighbors(pixel):
            second_id = node_map.get(neighbor)
            if second_id is None or second_id == first_id or neighbor not in pixels:
                continue
            key = (min(first_id, second_id), max(first_id, second_id))
            if key in seen:
                continue
            seen.add(key)
            paths.append([_node_center(node_clusters[first_id]), _node_center(node_clusters[second_id])])
    return paths


def _shortest_path(
    start: tuple[int, int],
    end: tuple[int, int],
    pixels: set[tuple[int, int]],
) -> list[tuple[int, int]]:
    if start == end:
        return [start]
    queue = deque([start])
    parents: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    while queue:
        current = queue.popleft()
        for neighbor in _pixel_neighbors(current):
            if neighbor not in pixels or neighbor in parents:
                continue
            parents[neighbor] = current
            if neighbor == end:
                return _reconstruct_path(start, end, parents)
            queue.append(neighbor)
    return _diameter_path(pixels)


def _node_center(cluster: set[tuple[int, int]]) -> tuple[int, int]:
    ys = [pixel[0] for pixel in cluster]
    xs = [pixel[1] for pixel in cluster]
    return (int(round(float(np.mean(ys)))), int(round(float(np.mean(xs)))))


def _dedupe_paths(paths: list[list[tuple[int, int]]]) -> list[list[tuple[int, int]]]:
    output: list[list[tuple[int, int]]] = []
    seen: set[tuple[tuple[int, int], tuple[int, int], int]] = set()
    for path in paths:
        if len(path) < 2:
            continue
        key = (path[0], path[-1], len(path))
        reverse_key = (path[-1], path[0], len(path))
        if key in seen or reverse_key in seen:
            continue
        seen.add(key)
        output.append(path)
    return output


def _merge_continuation_paths(paths: list[list[tuple[int, int]]]) -> list[list[tuple[int, int]]]:
    active = [list(path) for path in paths if len(path) >= 2]
    changed = True
    max_rounds = max(1, len(active))
    rounds = 0
    while changed and rounds < max_rounds:
        rounds += 1
        changed = False
        endpoint_map = _path_endpoint_map(active)
        used: set[int] = set()
        replacements: list[list[tuple[int, int]]] = []

        for point, refs in endpoint_map.items():
            refs = [ref for ref in refs if ref[0] not in used]
            if len(refs) < 2:
                continue
            pairs = _continuation_pairs(point, refs, active)
            for first, second in pairs:
                if first[0] in used or second[0] in used:
                    continue
                if _paths_share_interior(active[first[0]], active[second[0]]):
                    continue
                merged = _merge_path_pair(point, active[first[0]], first[1], active[second[0]], second[1])
                if len(merged) > max(len(active[first[0]]), len(active[second[0]])) and len(merged) <= len(active[first[0]]) + len(active[second[0]]):
                    used.add(first[0])
                    used.add(second[0])
                    replacements.append(merged)
                    changed = True

        if changed:
            active = [path for idx, path in enumerate(active) if idx not in used] + replacements
            active = _dedupe_paths(active)
    return active


def _paths_share_interior(first: list[tuple[int, int]], second: list[tuple[int, int]]) -> bool:
    first_interior = set(first[1:-1])
    second_interior = set(second[1:-1])
    return bool(first_interior & second_interior)


def _path_endpoint_map(paths: list[list[tuple[int, int]]]) -> dict[tuple[int, int], list[tuple[int, bool]]]:
    endpoint_map: dict[tuple[int, int], list[tuple[int, bool]]] = {}
    for idx, path in enumerate(paths):
        endpoint_map.setdefault(path[0], []).append((idx, True))
        endpoint_map.setdefault(path[-1], []).append((idx, False))
    return endpoint_map


def _continuation_pairs(
    point: tuple[int, int],
    refs: list[tuple[int, bool]],
    paths: list[list[tuple[int, int]]],
) -> list[tuple[tuple[int, bool], tuple[int, bool]]]:
    remaining = list(refs)
    pairs: list[tuple[tuple[int, bool], tuple[int, bool]]] = []
    while len(remaining) >= 2:
        best_pair: tuple[tuple[int, bool], tuple[int, bool]] | None = None
        best_score = 2.0
        for i, first in enumerate(remaining):
            for second in remaining[i + 1 :]:
                score = _endpoint_direction_dot(point, paths[first[0]], first[1], paths[second[0]], second[1])
                if score < best_score:
                    best_score = score
                    best_pair = (first, second)
        if best_pair is None:
            break
        if len(refs) == 2 or best_score <= -0.15:
            pairs.append(best_pair)
            remaining = [ref for ref in remaining if ref not in best_pair]
        else:
            break
    return pairs


def _endpoint_direction_dot(
    point: tuple[int, int],
    first_path: list[tuple[int, int]],
    first_at_start: bool,
    second_path: list[tuple[int, int]],
    second_at_start: bool,
) -> float:
    first_vec = _endpoint_outward_vector(point, first_path, first_at_start)
    second_vec = _endpoint_outward_vector(point, second_path, second_at_start)
    first_norm = float(np.hypot(first_vec[0], first_vec[1]))
    second_norm = float(np.hypot(second_vec[0], second_vec[1]))
    if first_norm == 0 or second_norm == 0:
        return 1.0
    return float((first_vec[0] * second_vec[0] + first_vec[1] * second_vec[1]) / (first_norm * second_norm))


def _endpoint_outward_vector(
    point: tuple[int, int],
    path: list[tuple[int, int]],
    at_start: bool,
) -> tuple[float, float]:
    sample_count = min(6, len(path) - 1)
    if sample_count <= 0:
        return (0.0, 0.0)
    other = path[sample_count] if at_start else path[-1 - sample_count]
    return (float(other[0] - point[0]), float(other[1] - point[1]))


def _merge_path_pair(
    point: tuple[int, int],
    first_path: list[tuple[int, int]],
    first_at_start: bool,
    second_path: list[tuple[int, int]],
    second_at_start: bool,
) -> list[tuple[int, int]]:
    del point
    first_to_shared = list(reversed(first_path)) if first_at_start else list(first_path)
    second_from_shared = list(second_path) if second_at_start else list(reversed(second_path))
    return first_to_shared + second_from_shared[1:]


def _take_pixel_component(pixels: set[tuple[int, int]]) -> set[tuple[int, int]]:
    start = next(iter(pixels))
    queue = deque([start])
    component = {start}
    pixels.remove(start)
    while queue:
        current = queue.popleft()
        for neighbor in _pixel_neighbors(current):
            if neighbor in pixels:
                pixels.remove(neighbor)
                component.add(neighbor)
                queue.append(neighbor)
    return component


def _largest_remaining_component(pixels: set[tuple[int, int]]) -> set[tuple[int, int]]:
    components: list[set[tuple[int, int]]] = []
    pool = set(pixels)
    while pool:
        components.append(_take_pixel_component(pool))
    return max(components, key=len) if components else set()


def _diameter_path(pixels: set[tuple[int, int]]) -> list[tuple[int, int]]:
    if not pixels:
        return []
    endpoints = [pixel for pixel in pixels if _degree(pixel, pixels) <= 1]
    start = endpoints[0] if endpoints else next(iter(pixels))
    far, _ = _farthest_pixel(start, pixels)
    farthest, parents = _farthest_pixel(far, pixels)
    return _reconstruct_path(far, farthest, parents)


def _farthest_pixel(
    start: tuple[int, int],
    pixels: set[tuple[int, int]],
) -> tuple[tuple[int, int], dict[tuple[int, int], tuple[int, int] | None]]:
    queue = deque([start])
    parents: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    farthest = start
    while queue:
        current = queue.popleft()
        farthest = current
        for neighbor in _pixel_neighbors(current):
            if neighbor in pixels and neighbor not in parents:
                parents[neighbor] = current
                queue.append(neighbor)
    return farthest, parents


def _reconstruct_path(
    start: tuple[int, int],
    end: tuple[int, int],
    parents: dict[tuple[int, int], tuple[int, int] | None],
) -> list[tuple[int, int]]:
    path = [end]
    current = end
    while current != start and parents.get(current) is not None:
        current = parents[current]  # type: ignore[assignment]
        path.append(current)
    path.reverse()
    return path


def _degree(pixel: tuple[int, int], pixels: set[tuple[int, int]]) -> int:
    return sum(1 for neighbor in _pixel_neighbors(pixel) if neighbor in pixels)


def _edge_key(
    a: tuple[int, int],
    b: tuple[int, int],
) -> tuple[tuple[int, int], tuple[int, int]]:
    return (a, b) if a <= b else (b, a)


def _pixel_neighbors(pixel: tuple[int, int]) -> list[tuple[int, int]]:
    y, x = pixel
    return [
        (y - 1, x - 1),
        (y - 1, x),
        (y - 1, x + 1),
        (y, x - 1),
        (y, x + 1),
        (y + 1, x - 1),
        (y + 1, x),
        (y + 1, x + 1),
    ]


def _ordered_neighbors(image: np.ndarray, y: int, x: int) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        int(image[y - 1, x]),
        int(image[y - 1, x + 1]),
        int(image[y, x + 1]),
        int(image[y + 1, x + 1]),
        int(image[y + 1, x]),
        int(image[y + 1, x - 1]),
        int(image[y, x - 1]),
        int(image[y - 1, x - 1]),
    )


def _zero_to_one_transitions(values: tuple[int, ...]) -> int:
    return sum(1 for idx, value in enumerate(values) if value == 0 and values[(idx + 1) % len(values)] == 1)


def _simplify_curve(points: Curve, epsilon: float) -> Curve:
    if len(points) <= 2 or epsilon <= 0:
        return points
    closed = _endpoint_distance(points) <= max(1.5, float(epsilon) * 2.0)
    contour = np.array(points, dtype=np.float32).reshape(-1, 1, 2)
    simplified = cv2.approxPolyDP(contour, float(epsilon), closed=closed)
    output = [(float(point[0][0]), float(point[0][1])) for point in simplified]
    if closed and output and output[0] != output[-1]:
        output.append(output[0])
    return output


def _curve_length(points: Curve) -> float:
    if len(points) < 2:
        return 0.0
    return float(
        sum(
            np.hypot(points[idx][0] - points[idx - 1][0], points[idx][1] - points[idx - 1][1])
            for idx in range(1, len(points))
        )
    )


def _postprocess_curve2d(
    curves: list[Curve2D],
    min_length_px: float,
    overlap_tolerance_px: float,
) -> list[Curve2D]:
    ordered = sorted(curves, key=lambda curve: _curve_length(_curve_points(curve)), reverse=True)
    accepted: list[Curve2D] = []
    for curve in ordered:
        points = _curve_points(curve)
        length = _curve_length(points)
        if length < min_length_px:
            continue
        if _is_redundant_curve(points, accepted, tolerance=overlap_tolerance_px):
            continue
        closed = curve.closed or _endpoint_distance(points) <= max(3.0, overlap_tolerance_px)
        accepted.append(Curve2D(points=curve.points, curve_id=len(accepted), closed=closed))
    accepted.sort(key=lambda curve: (curve.start()[1], curve.start()[0], curve.curve_id))
    for idx, curve in enumerate(accepted):
        curve.curve_id = idx
    return accepted


def _scale_curve2d(curve: Curve2D, scale: float) -> Curve2D:
    return Curve2D(
        points=[[float(point[0]) * scale, float(point[1]) * scale] for point in curve.points],
        curve_id=curve.curve_id,
        closed=curve.closed,
    )


def _curve_points(curve: Curve2D) -> Curve:
    return [(float(point[0]), float(point[1])) for point in curve.points]


def _endpoint_distance(points: Curve) -> float:
    if len(points) < 2:
        return float("inf")
    return float(np.hypot(points[0][0] - points[-1][0], points[0][1] - points[-1][1]))


def _is_redundant_curve(points: Curve, accepted: list[Curve2D], tolerance: float) -> bool:
    if len(points) < 2 or not accepted:
        return False
    samples = _sample_curve_points(points, max_samples=24)
    if len(samples) < 2:
        return False
    point_bbox = _points_bbox(points, padding=tolerance)
    for curve in accepted:
        accepted_points = _curve_points(curve)
        if not _bbox_intersects(point_bbox, _points_bbox(accepted_points, padding=tolerance)):
            continue
        near_count = sum(1 for sample in samples if _point_to_polyline_distance(sample, accepted_points) <= tolerance)
        if near_count / len(samples) >= 0.72:
            return True
    return False


def _sample_curve_points(points: Curve, max_samples: int) -> Curve:
    if len(points) <= max_samples:
        return points
    indices = np.linspace(0, len(points) - 1, max_samples).astype(int)
    return [points[int(index)] for index in indices]


def _point_to_polyline_distance(point: Point, polyline: Curve) -> float:
    if len(polyline) < 2:
        return float("inf")
    return min(_point_to_segment_distance(point, polyline[idx - 1], polyline[idx]) for idx in range(1, len(polyline)))


def _point_to_segment_distance(point: Point, start: Point, end: Point) -> float:
    px, py = point
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    denom = dx * dx + dy * dy
    if denom == 0:
        return float(np.hypot(px - sx, py - sy))
    t = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / denom))
    closest_x = sx + t * dx
    closest_y = sy + t * dy
    return float(np.hypot(px - closest_x, py - closest_y))


def _points_bbox(points: Curve, padding: float = 0.0) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs) - padding, min(ys) - padding, max(xs) + padding, max(ys) + padding)


def _bbox_intersects(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    return not (first[2] < second[0] or second[2] < first[0] or first[3] < second[1] or second[3] < first[1])


def _chaikin(points: Curve, iterations: int) -> Curve:
    output = list(points)
    for _ in range(max(0, int(iterations))):
        if len(output) < 3:
            break
        refined: Curve = [output[0]]
        for p0, p1 in zip(output[:-1], output[1:]):
            refined.append((0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1]))
            refined.append((0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1]))
        refined.append(output[-1])
        output = refined
    return output


def _public_analysis(analysis: dict) -> dict:
    components = []
    for item in analysis["components"]:
        components.append({key: value for key, value in item.items() if key != "mask"})
    return {**analysis, "components": components}


def _odd_at_least(value: int, minimum: int) -> int:
    output = max(minimum, int(value))
    return output if output % 2 == 1 else output + 1


def _report(callback: ProgressCallback | None, value: float, message: str) -> None:
    if callback is not None:
        callback(max(0.0, min(1.0, value)), message)
