from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from src.modules.image_process_module import analyze_binary_content, bridge_small_gaps, threshold_image


@dataclass(frozen=True)
class ImageQualityReport:
    accepted: bool
    score: int
    reasons: list[str]
    metrics: dict[str, Any]


def evaluate_traceable_line_image(image_path: str | Path, *, max_dim: int = 768) -> ImageQualityReport:
    image = np.array(Image.open(image_path).convert("RGB"))
    image = _resize_rgb(image, max_dim=max_dim)
    binary = threshold_image(image, method="otsu", blur_size=3)
    binary = bridge_small_gaps(binary, bridge_gap_px=1)
    binary_mask = binary > 0
    total_px = max(1, int(binary_mask.size))
    black_ratio = float(np.count_nonzero(binary_mask) / total_px)

    analysis = analyze_binary_content(binary, min_component_area=max(12, int(total_px * 0.000015)))
    raw_component_count, small_component_count = _component_counts(binary, min_area=max(12, int(total_px * 0.000015)))
    detail_density = _edge_density(image)
    large_filled_count = _large_filled_component_count(analysis.get("components", []), total_px)
    p90_stroke = float(analysis.get("p90_stroke_width_px", 0.0))

    metrics = {
        "score": 100,
        "black_ratio": round(black_ratio, 4),
        "component_count": int(analysis.get("component_count", 0)),
        "raw_component_count": int(raw_component_count),
        "small_component_count": int(small_component_count),
        "line_component_count": int(analysis.get("line_component_count", 0)),
        "area_component_count": int(analysis.get("area_component_count", 0)),
        "large_filled_component_count": int(large_filled_count),
        "p90_stroke_width_px": round(p90_stroke, 2),
        "detail_density": round(detail_density, 4),
        "processing_size": [int(image.shape[1]), int(image.shape[0])],
    }

    penalties: list[tuple[int, str]] = []
    if black_ratio < 0.004:
        penalties.append((35, "线条太少，可能无法识别主体"))
    if black_ratio > 0.16:
        penalties.append((35, "黑色区域过多，图像更像填充图而不是线稿"))
    if int(analysis.get("component_count", 0)) > 45:
        penalties.append((25, "连通区域过多，转曲线后容易产生大量碎线"))
    if small_component_count > 50:
        penalties.append((25, "短小噪声过多，后续轨迹会变碎"))
    if large_filled_count > 0:
        penalties.append((30, "存在较大的填充块，不适合中心线提取"))
    if detail_density > 0.085:
        penalties.append((20, "边缘密度过高，细节过多"))
    if p90_stroke > 42:
        penalties.append((15, "笔画过粗，可能被识别为面图"))

    score = max(0, 100 - sum(value for value, _ in penalties))
    metrics["score"] = int(score)
    blocking = [reason for value, reason in penalties if value >= 25]
    accepted = score >= 70 and not blocking
    if accepted:
        reasons = ["通过：图像足够简洁，适合进入图像转曲线模块"]
    else:
        reasons = blocking or [reason for _, reason in penalties] or ["未通过：图像质量评分不足"]
    return ImageQualityReport(accepted=accepted, score=int(score), reasons=reasons, metrics=metrics)


def build_retry_prompt(base_prompt: str, attempt_index: int) -> str:
    if attempt_index <= 1:
        return base_prompt
    retry_constraints = [
        "Make it much simpler than the previous attempt.",
        "Use at most 6 long continuous strokes.",
        "Remove all internal texture and decorative detail.",
        "Use one clean outline, no repeated lines, no small fragments.",
    ]
    if attempt_index >= 3:
        retry_constraints.extend(
            [
                "Ultra minimal icon.",
                "A child should be able to draw it in one continuous motion.",
            ]
        )
    return base_prompt + " " + " ".join(retry_constraints)


def _resize_rgb(image: np.ndarray, *, max_dim: int) -> np.ndarray:
    if image.size == 0:
        return image
    max_side = max(image.shape[:2])
    limit = max(128, int(max_dim))
    if max_side <= limit:
        return image
    scale = limit / float(max_side)
    width = max(1, int(round(image.shape[1] * scale)))
    height = max(1, int(round(image.shape[0] * scale)))
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)


def _component_counts(binary: np.ndarray, *, min_area: int) -> tuple[int, int]:
    if binary.size == 0:
        return 0, 0
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats((binary > 0).astype(np.uint8), connectivity=8)
    raw_count = max(0, int(num_labels) - 1)
    small_count = 0
    for label_id in range(1, num_labels):
        area = int(stats[label_id, cv2.CC_STAT_AREA])
        if 0 < area < min_area:
            small_count += 1
    return raw_count, small_count


def _large_filled_component_count(components: list[dict[str, Any]], total_px: int) -> int:
    count = 0
    for component in components:
        area = int(component.get("area", 0))
        fill_ratio = float(component.get("fill_ratio", 0.0))
        content_type = str(component.get("content_type", ""))
        if content_type == "area" and area / max(1, total_px) >= 0.015 and fill_ratio >= 0.42:
            count += 1
    return count


def _edge_density(image: np.ndarray) -> float:
    if image.size == 0:
        return 0.0
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 80, 180)
    return float(np.count_nonzero(edges) / max(1, edges.size))
