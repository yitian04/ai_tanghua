from __future__ import annotations

import json
import math
import os
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.core.models import Curve2D, CurveList
from src.pipeline.vectorization import parse_svg_to_curve_list


class DirectCurveGenerationError(RuntimeError):
    """Raised when direct CurveList generation fails."""


@dataclass
class DirectCurveRequest:
    prompt: str
    style: str = "traditional_sugar_painting"
    canvas_size: int = 1000
    max_curves: int = 10
    max_points_per_curve: int = 48
    complexity: str = "medium"
    model: str = "Qwen/Qwen3.6-27B"
    fallback_model: str = "moonshotai/Kimi-K2.7-Code"
    api_base_url: str = "https://api.siliconflow.cn/v1"
    timeout_s: int = 180
    max_attempts: int = 3
    sample_tolerance_px: float = 2.0


class DirectCurveGenerator:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("SILICONFLOW_API_KEY", "")

    def generate(self, request: DirectCurveRequest, *, use_demo: bool = False) -> CurveList:
        if use_demo:
            return self.generate_demo(request)
        if not self.api_key:
            raise DirectCurveGenerationError("SILICONFLOW_API_KEY is not set. Use demo mode or input a SiliconFlow API key.")
        return self._generate_svg_curves(request)

    def _generate_svg_curves(self, request: DirectCurveRequest) -> CurveList:
        feedback = ""
        last_error = ""
        attempts = max(1, min(4, int(request.max_attempts)))
        for attempt in range(1, attempts + 1):
            model = request.fallback_model if attempt == attempts and attempt > 1 else request.model
            try:
                payload = self._call_svg_generation(request, model=model, feedback=feedback)
                svg = _clean_svg(str(payload.get("svg", "")), request)
                curves = _parse_svg_text(svg, request)
                deterministic = _deterministic_review(curves, request)
                if deterministic["accepted"]:
                    curves.metadata.update(
                        {
                            "source": "siliconflow_text_to_svg",
                            "prompt": request.prompt,
                            "style": request.style,
                            "canvas_size": request.canvas_size,
                            "model": model,
                            "attempt": attempt,
                            "description": payload.get("description", ""),
                            "validation": deterministic,
                            "generated_svg": svg,
                        }
                    )
                    return curves
                feedback = _review_feedback(deterministic)
                last_error = feedback
            except (DirectCurveGenerationError, ET.ParseError, ValueError) as exc:
                last_error = str(exc)
                feedback = f"The previous SVG was invalid: {last_error}. Regenerate it from scratch."
        raise DirectCurveGenerationError(
            f"No acceptable sugar-painting SVG after {attempts} attempts: {last_error}"
        )

    def _call_svg_generation(
        self, request: DirectCurveRequest, *, model: str, feedback: str
    ) -> dict[str, Any]:
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": _svg_system_prompt(request)},
                {"role": "user", "content": _svg_user_prompt(request, feedback)},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 6000,
            "temperature": 0.1 if feedback else 0.35,
            "top_p": 0.85,
        }
        response_data = self._post_chat_completion(request, body)
        content = _extract_message_content(response_data)
        try:
            payload = _loads_model_json(content)
        except json.JSONDecodeError as exc:
            raise DirectCurveGenerationError(
                f"Model returned invalid JSON: {content[:500]}"
            ) from exc
        if not isinstance(payload.get("svg"), str):
            raise DirectCurveGenerationError("Model JSON did not contain an SVG string.")
        return payload

    def generate_demo(self, request: DirectCurveRequest) -> CurveList:
        prompt = request.prompt.lower()
        if any(word in prompt for word in ("鱼", "fish")):
            curves = _fish_curves()
            title = "fish"
        elif any(word in prompt for word in ("兔", "rabbit", "bunny")):
            curves = _rabbit_curves()
            title = "rabbit"
        elif any(word in prompt for word in ("云", "cloud", "祥云")):
            curves = _cloud_curves()
            title = "cloud"
        else:
            curves = _flower_curves()
            title = "flower"
        return _build_curve_list(curves, request, source="local_demo_template", extra_metadata={"demo_template": title})

    def _call_siliconflow(self, request: DirectCurveRequest) -> dict[str, Any]:
        body = {
            "model": request.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You generate robot-drawable 2D curve data for Chinese sugar painting. "
                        "Return one valid JSON object only. Never use markdown. Never use placeholders. "
                        "All point coordinates must be real numbers."
                    ),
                },
                {"role": "user", "content": _build_user_prompt(request)},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 3072,
            "temperature": 0.1,
        }
        response_data = self._post_chat_completion(request, body)
        content = _extract_message_content(response_data)
        try:
            return _loads_model_json(content)
        except json.JSONDecodeError:
            repaired = self._repair_json(request, content)
            try:
                return _loads_model_json(repaired)
            except json.JSONDecodeError as exc:
                raise DirectCurveGenerationError(f"Model returned invalid JSON after repair: {content[:500]}") from exc

    def _repair_json(self, request: DirectCurveRequest, broken_content: str) -> str:
        body = {
            "model": request.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Repair the user's broken JSON into exactly one valid JSON object. "
                        "Do not explain. Do not use markdown. Remove invalid placeholders. "
                        "Required shape: {\"description\": string, \"prompt_refinement\": string, "
                        "\"curves\": [{\"name\": string, \"closed\": boolean, \"points\": [[x,y], ...]}]}. "
                        "All x and y values must be numbers in 0..1000."
                    ),
                },
                {"role": "user", "content": broken_content[:6000]},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 3072,
            "temperature": 0.0,
        }
        response_data = self._post_chat_completion(request, body)
        return _extract_message_content(response_data)

    def _post_chat_completion(self, request: DirectCurveRequest, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        http_request = urllib.request.Request(
            f"{request.api_base_url.rstrip('/')}/chat/completions",
            data=data,
            method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(http_request, timeout=request.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise DirectCurveGenerationError(f"SiliconFlow request failed: HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise DirectCurveGenerationError(f"SiliconFlow request failed: {exc}") from exc

    def _curve_list_from_payload(self, payload: dict[str, Any], request: DirectCurveRequest, *, source: str) -> CurveList:
        raw_items = payload.get("curves") or payload.get("curve_list") or []
        curves: list[list[list[float]]] = []
        if not isinstance(raw_items, list):
            raise DirectCurveGenerationError("Model JSON has no valid curves array.")
        for item in raw_items[: request.max_curves]:
            if not isinstance(item, dict):
                continue
            points = []
            raw_points = item.get("points") or []
            if not isinstance(raw_points, list):
                continue
            for point in raw_points[: request.max_points_per_curve]:
                parsed = _parse_point(point)
                if parsed is not None:
                    points.append(parsed)
            curves.append(points)
        return _build_curve_list(
            curves,
            request,
            source=source,
            extra_metadata={
                "description": payload.get("description", ""),
                "prompt_refinement": payload.get("prompt_refinement", ""),
            },
        )


def curve_list_to_svg(curves: CurveList, *, width: int = 1000, height: int = 1000, stroke_width: float = 12.0, padding: float | None = None) -> str:
    pad = float(stroke_width * 2 if padding is None else padding)
    view_x = -pad
    view_y = -pad
    view_w = float(width) + 2 * pad
    view_h = float(height) + 2 * pad
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="{view_x:.2f} {view_y:.2f} {view_w:.2f} {view_h:.2f}" preserveAspectRatio="xMidYMid meet" style="display:block;max-width:100%;max-height:100%;">',
        f'<rect x="{view_x:.2f}" y="{view_y:.2f}" width="{view_w:.2f}" height="{view_h:.2f}" fill="white"/>',
        '<g fill="none" stroke="black" stroke-linecap="round" stroke-linejoin="round">',
    ]
    for curve in curves.curves:
        if len(curve.points) < 2:
            continue
        d = _points_to_path(curve.points, closed=curve.closed)
        parts.append(f'<path d="{d}" stroke-width="{stroke_width:.2f}"/>')
    parts.extend(["</g>", "</svg>"])
    return "\n".join(parts)


def save_curve_list_svg(curves: CurveList, path: str | Path, *, stroke_width: float = 12.0) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    size = int(curves.metadata.get("canvas_size", 1000))
    output.write_text(curve_list_to_svg(curves, width=size, height=size, stroke_width=stroke_width), encoding="utf-8")
    return output


def _svg_system_prompt(request: DirectCurveRequest) -> str:
    return (
        "You design simple 2D robot-drawable Chinese sugar-painting line art. "
        "Return exactly one JSON object with keys description and svg. "
        "The svg value must be a complete SVG string. Use viewBox 0 0 "
        f"{request.canvas_size} {request.canvas_size}. "
        "Use path elements only, fill='none', black strokes, round caps and joins. "
        f"Use no more than {request.max_curves} paths. "
        "Prefer cubic Bezier commands. Do not use text, images, CSS, scripts, "
        "filters, gradients, masks, patterns, clipping, or external references. "
        "Make one centered recognizable subject with few long smooth strokes. "
        "Important parts should touch. Avoid tiny details, hatching, double outlines, "
        "filled regions, self-intersection, and decorative clutter."
    )


def _svg_user_prompt(request: DirectCurveRequest, feedback: str) -> str:
    prompt = (
        f"Create sugar-painting curve art for: {request.prompt}. "
        f"Complexity: {request.complexity}. "
        "The drawing will be sampled into robot trajectories, so visual recognition "
        "must come from sparse smooth centerlines."
    )
    if feedback:
        prompt += " Revision feedback: " + feedback
    return prompt


def _extract_svg_text(value: str) -> str:
    text = (value or "").strip()
    start = text.find("<svg")
    end = text.rfind("</svg>")
    if start < 0 or end < start:
        raise DirectCurveGenerationError("Model output did not contain a complete SVG.")
    svg = text[start : end + 6]
    if len(svg) > 120000:
        raise DirectCurveGenerationError("Generated SVG is too large.")
    return svg


def _clean_svg(value: str, request: DirectCurveRequest) -> str:
    root = ET.fromstring(_extract_svg_text(value))
    if root.tag.rsplit("}", 1)[-1].lower() != "svg":
        raise DirectCurveGenerationError("Generated XML root is not svg.")
    allowed = {"svg", "g", "path"}
    path_count = 0
    for parent in list(root.iter()):
        for child in list(parent):
            tag = child.tag.rsplit("}", 1)[-1].lower()
            if tag not in allowed:
                parent.remove(child)
                continue
            if tag == "path":
                path_count += 1
                if path_count > request.max_curves or not child.attrib.get("d"):
                    parent.remove(child)
                    continue
                child.attrib["fill"] = "none"
                child.attrib["stroke"] = "black"
                child.attrib["stroke-linecap"] = "round"
                child.attrib["stroke-linejoin"] = "round"
                for key in list(child.attrib):
                    if key.lower().startswith("on") or key in {"style", "filter", "mask", "clip-path"}:
                        child.attrib.pop(key, None)
    root.attrib.clear()
    root.attrib.update(
        {
            "xmlns": "http://www.w3.org/2000/svg",
            "viewBox": f"0 0 {request.canvas_size} {request.canvas_size}",
            "width": str(request.canvas_size),
            "height": str(request.canvas_size),
        }
    )
    output = ET.tostring(root, encoding="unicode")
    if "<path" not in output and ":path" not in output:
        raise DirectCurveGenerationError("Generated SVG has no valid path elements.")
    return output


def _parse_svg_text(svg: str, request: DirectCurveRequest) -> CurveList:
    with tempfile.TemporaryDirectory(prefix="tanghua_svg_") as directory:
        path = Path(directory) / "generated.svg"
        path.write_text(svg, encoding="utf-8")
        curves = parse_svg_to_curve_list(
            path,
            sample_tolerance_px=request.sample_tolerance_px,
            min_curve_length_px=request.canvas_size * 0.015,
            metadata={"source": "siliconflow_text_to_svg"},
        )
    if not curves.curves:
        raise DirectCurveGenerationError("SVG parser found no drawable curves.")
    return curves


def _deterministic_review(curves: CurveList, request: DirectCurveRequest) -> dict[str, Any]:
    lengths = [_polyline_length(curve.points) for curve in curves.curves]
    problems: list[str] = []
    if len(curves.curves) > request.max_curves:
        problems.append(f"Too many paths: {len(curves.curves)}")
    if any(length < request.canvas_size * 0.02 for length in lengths):
        problems.append("One or more paths are too short.")
    total = sum(lengths)
    if total < request.canvas_size * 0.5:
        problems.append("The drawing is too sparse to be recognizable.")
    if total > request.canvas_size * request.max_curves * 4:
        problems.append("The drawing is too dense for sugar painting.")
    return {
        "accepted": not problems,
        "problems": problems,
        "curve_count": len(curves.curves),
        "total_curve_length_px": round(total, 2),
    }


def _review_feedback(deterministic: dict[str, Any]) -> str:
    problems = list(deterministic.get("problems", []))
    return (
        "Redraw the same subject as simpler robot-drawable centerlines. "
        + " ".join(str(item) for item in problems)
    ).strip()


def _extract_message_content(response_data: dict[str, Any]) -> str:
    try:
        return str(response_data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise DirectCurveGenerationError(f"Unexpected SiliconFlow response: {response_data}") from exc


def _loads_model_json(content: str) -> dict[str, Any]:
    return json.loads(_extract_json_object(content))


def _extract_json_object(content: str) -> str:
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _parse_point(point: Any) -> list[float] | None:
    try:
        if isinstance(point, dict):
            x = point.get("x")
            y = point.get("y")
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            x, y = point[0], point[1]
        else:
            return None
        if isinstance(x, str) or isinstance(y, str):
            return None
        return [float(x), float(y)]
    except (TypeError, ValueError):
        return None


def _build_user_prompt(request: DirectCurveRequest) -> str:
    return (
        f"User request: {request.prompt}\n"
        f"Canvas: {request.canvas_size}x{request.canvas_size}. Origin is top-left.\n"
        f"Return at most {request.max_curves} curves. Return 6 to 24 points per curve, at most {request.max_points_per_curve}.\n"
        "Required JSON shape exactly:\n"
        "{\"description\":\"...\",\"prompt_refinement\":\"...\",\"curves\":[{\"name\":\"body\",\"closed\":false,\"points\":[[120,500],[180,440],[260,420]]}]}\n"
        "Rules: points are numeric [x,y] arrays only; no strings inside points; no empty arrays; no placeholder values. "
        "Use simple continuous sugar-painting strokes, centered composition, white background implied, no filled areas."
    )


def _build_curve_list(
    raw_curves: list[list[list[float]]],
    request: DirectCurveRequest,
    *,
    source: str,
    extra_metadata: dict[str, Any] | None = None,
) -> CurveList:
    canvas_size = float(request.canvas_size)
    curves: list[Curve2D] = []
    for raw_points in raw_curves[: request.max_curves]:
        points = _clean_points(raw_points, canvas_size=canvas_size)
        if len(points) < 2 or _polyline_length(points) < canvas_size * 0.015:
            continue
        curves.append(Curve2D(points=points[: request.max_points_per_curve], curve_id=len(curves), closed=_is_closed(points)))
    if not curves:
        raise DirectCurveGenerationError("No valid drawable curves were generated. Try Qwen/Qwen3-8B or deepseek-ai/DeepSeek-V3, and use a simpler prompt.")
    return CurveList(
        curves=curves,
        coordinate_frame="image_px",
        metadata={
            "source": source,
            "prompt": request.prompt,
            "style": request.style,
            "canvas_size": int(request.canvas_size),
            "complexity": request.complexity,
            "max_curves": request.max_curves,
            "max_points_per_curve": request.max_points_per_curve,
            **(extra_metadata or {}),
        },
    )


def _clean_points(raw_points: list[list[float]], *, canvas_size: float) -> list[list[float]]:
    points: list[list[float]] = []
    for item in raw_points:
        if len(item) < 2:
            continue
        x = min(canvas_size, max(0.0, float(item[0])))
        y = min(canvas_size, max(0.0, float(item[1])))
        if not math.isfinite(x) or not math.isfinite(y):
            continue
        if not points or math.hypot(points[-1][0] - x, points[-1][1] - y) >= 2.0:
            points.append([round(x, 2), round(y, 2)])
    return points


def _polyline_length(points: list[list[float]]) -> float:
    return sum(math.hypot(points[idx][0] - points[idx - 1][0], points[idx][1] - points[idx - 1][1]) for idx in range(1, len(points)))


def _is_closed(points: list[list[float]]) -> bool:
    return len(points) > 2 and math.hypot(points[0][0] - points[-1][0], points[0][1] - points[-1][1]) <= 4.0


def _points_to_path(points: list[list[float]], *, closed: bool) -> str:
    if not points:
        return ""
    commands = [f"M {points[0][0]:.2f} {points[0][1]:.2f}"]
    commands.extend(f"L {point[0]:.2f} {point[1]:.2f}" for point in points[1:])
    if closed:
        commands.append("Z")
    return " ".join(commands)


def _cubic(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float], n: int = 48) -> list[list[float]]:
    return [
        [
            round((1 - t) ** 3 * a[0] + 3 * (1 - t) ** 2 * t * b[0] + 3 * (1 - t) * t * t * c[0] + t**3 * d[0], 2),
            round((1 - t) ** 3 * a[1] + 3 * (1 - t) ** 2 * t * b[1] + 3 * (1 - t) * t * t * c[1] + t**3 * d[1], 2),
        ]
        for t in (idx / n for idx in range(n + 1))
    ]


def _quad(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], n: int = 36) -> list[list[float]]:
    return [
        [
            round((1 - t) ** 2 * a[0] + 2 * (1 - t) * t * b[0] + t * t * c[0], 2),
            round((1 - t) ** 2 * a[1] + 2 * (1 - t) * t * b[1] + t * t * c[1], 2),
        ]
        for t in (idx / n for idx in range(n + 1))
    ]


def _ellipse(cx: float, cy: float, rx: float, ry: float, n: int = 96) -> list[list[float]]:
    return [[round(cx + rx * math.cos(2 * math.pi * idx / n), 2), round(cy + ry * math.sin(2 * math.pi * idx / n), 2)] for idx in range(n + 1)]


def _fish_curves() -> list[list[list[float]]]:
    return [
        _ellipse(500, 500, 260, 145, 96),
        [[745, 500], [900, 370], [875, 500], [900, 630], [745, 500]],
        _cubic((350, 500), (420, 395), (585, 390), (690, 475), 42),
        _cubic((350, 500), (420, 605), (585, 610), (690, 525), 42),
        _ellipse(305, 455, 22, 22, 32),
        _cubic((465, 360), (535, 260), (610, 350), (555, 425), 32),
        _cubic((470, 640), (540, 740), (615, 650), (560, 575), 32),
    ]


def _rabbit_curves() -> list[list[list[float]]]:
    return [
        _ellipse(500, 565, 180, 150, 96),
        _cubic((420, 430), (300, 170), (385, 110), (495, 395), 52),
        _cubic((540, 405), (610, 115), (730, 170), (605, 450), 52),
        _ellipse(440, 540, 18, 18, 32),
        _ellipse(565, 540, 18, 18, 32),
        _quad((500, 565), (485, 595), (500, 620), 24) + _quad((500, 620), (515, 595), (500, 565), 24)[1:],
        _cubic((375, 625), (285, 610), (250, 575), (180, 585), 32),
        _cubic((385, 675), (290, 705), (240, 750), (170, 755), 32),
        _cubic((620, 625), (715, 610), (760, 575), (830, 585), 32),
        _cubic((610, 675), (710, 705), (765, 750), (835, 755), 32),
        _cubic((390, 730), (455, 815), (555, 815), (615, 730), 42),
    ]


def _cloud_curves() -> list[list[list[float]]]:
    return [
        _cubic((160, 520), (260, 360), (430, 360), (515, 505), 52) + _cubic((515, 505), (610, 665), (390, 710), (320, 575), 52)[1:],
        _cubic((500, 500), (610, 355), (825, 395), (830, 535), 52) + _cubic((830, 535), (835, 680), (655, 710), (590, 575), 52)[1:],
        _cubic((210, 650), (365, 720), (535, 720), (705, 650), 42),
        _cubic((250, 430), (360, 300), (570, 285), (700, 395), 42),
        _cubic((615, 455), (715, 410), (795, 450), (785, 535), 32),
    ]


def _flower_curves() -> list[list[list[float]]]:
    curves = []
    center = (500.0, 500.0)
    for idx in range(6):
        angle = 2 * math.pi * idx / 6
        cx = center[0] + 130 * math.cos(angle)
        cy = center[1] + 130 * math.sin(angle)
        curves.append(_ellipse(cx, cy, 95, 45, 48))
    curves.append(_ellipse(500, 500, 55, 55, 48))
    curves.append(_cubic((500, 560), (490, 680), (430, 760), (330, 830), 42))
    curves.append(_cubic((470, 700), (390, 650), (340, 640), (280, 670), 32))
    curves.append(_cubic((520, 690), (600, 650), (675, 640), (740, 680), 32))
    return curves
