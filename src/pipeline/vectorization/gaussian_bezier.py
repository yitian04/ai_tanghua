"""Solid-stroke Bézier centerlines fitted by 2D Gaussian splatting.

This is the geometry stage of Chen et al., SIGGRAPH 2026,
"2D Gaussian Splatting for Bézier Spline Line Art Vectorization"
(DOI 10.1145/3799902.3811211), adapted to constant-width sugar strokes
that a robot traces as polylines.

Adopted from the paper
----------------------
* Zhang-Suen skeleton graph, then one cubic Bézier chain per stroke
  (Section 3.1, without the pretrained affinity partition).
* Constant width ``m = 0`` taken from the stroke distance transform,
  the solid-line setting in Section 5.1.
* Centerline samples are isotropic 2D Gaussians. Scale follows Eq. (7);
  a solid stroke uses the paper's 1×1 texture, so samples sit on the
  centerline (normal offset ``s = 0``) and the curvature factor is 1.
* Control points move to reduce the mean squared error between the
  splatted stroke and the ink (Section 3.3, Stage 1, reconstruction
  only). Shared junctions stay fixed so strokes still meet.

Dropped
-------
* Depth and DINOv2 edge affinities. Sugar strands are physical strokes;
  splitting them with a pretrained segmentation model is not justified
  in this local app, and the existing collinear join already keeps
  straight-through continuations at a junction.
* Brush texture, LPIPS, and the Stage-2 appearance fit. The robot
  follows the centerline; strand width is a process setting.
* The geometric penalties used for textured strokes (self-intersection
  and curvature caps). A light G1 property is enforced by construction
  on smooth chains because the output is a robot path. Sharp corners
  stay broken, matching the previous regularizer.
* Stroke densification. Inventing strokes from leftover ink can bridge
  gaps the user did not ask to close.
* Video tracking and keyframes.

Pixel-space note: the paper fixes the density ``ρ`` at ``2e-3`` in its
normalized splat coordinates. Here coordinates are image pixels, and
``ρ = 1.25`` makes a centerline Gaussian about ``0.8`` of the half-width,
which is enough for one row of Gaussians to cover a solid stroke.
"""

from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np

from src.pipeline.vectorization.centerline import regularize


LINE_FIT_ID = "2d_gaussian_bezier_stage1"
PAPER_DOI = "10.1145/3799902.3811211"
# Pixel-space density in Eq. (7). See the module docstring.
RHO = 1.25
_SHARP_COSINE = 0.5


def gaussian_sigma(width: float, normal_offset: float, curvature: float, rho: float = RHO) -> float:
    """Isotropic Gaussian scale, Eq. (7), in pixels.

    ``normal_offset`` is the paper's ``s ∈ [-1, 1]``. Positive curvature
    with a positive offset enlarges the Gaussian (outer side when the
    normal points away from the center of curvature). The factor is
    floored so a tight bend cannot flip the scale.
    """
    factor = 1.0 + float(normal_offset) * float(width) * float(curvature)
    return max(0.35, float(width) / float(rho) * max(0.25, factor))


def fit_solid_stroke(
    points: Sequence[Sequence[float]],
    mask: np.ndarray,
    offset: tuple[float, float] = (0.0, 0.0),
    epsilon: float = 1.2,
    smooth: int = 0,
    *,
    fix_start: bool = False,
    fix_end: bool = False,
) -> list[list[float]]:
    """Fit one skeleton path and return a dense polyline in image pixels.

    Endpoints that are shared junctions (``fix_start`` / ``fix_end``) are
    returned unchanged. A failed or out-of-stroke fit falls back to the
    previous heuristic regularizer so topology is never worse than before.
    """
    original = np.asarray([[float(p[0]), float(p[1])] for p in points], dtype=float)
    if len(original) < 2:
        return original.tolist()
    ink = np.asarray(mask)
    if ink.ndim == 3:
        ink = ink[..., 0]
    local = original.copy()
    local[:, 0] -= float(offset[0])
    local[:, 1] -= float(offset[1])
    closed = len(local) >= 3 and float(np.linalg.norm(local[0] - local[-1])) <= 1e-5
    if closed:
        local = local[:-1]
    if len(local) < 2 or ink.size == 0 or int(np.count_nonzero(ink)) == 0:
        return _as_lists(regularize(original.tolist(), epsilon, smooth))

    width = _stroke_half_width(ink)
    tolerance = min(1.0, max(0.0, float(epsilon)))
    try:
        if not closed and _max_chord_distance(local) <= tolerance:
            fitted = _recenter_straight(local, ink, width, fix_start, fix_end)
            if _on_ink_fraction(ink, fitted) < 0.9:
                fitted = np.vstack([local[0], local[-1]])
        else:
            fitted = _fit_curved(local, ink, width, tolerance, int(smooth), closed, fix_start, fix_end)
            # The traced skeleton is the topology the robot must cover. A fit
            # that shortcuts toward a neighboring stroke is discarded.
            if fitted is None or not _inside_tube(local, fitted, closed, tolerance=1.55):
                fitted = None
    except (cv2.error, ValueError, FloatingPointError):
        fitted = None
    if fitted is None:
        fitted_global = regularize(original.tolist(), epsilon, smooth)
        return _as_lists(fitted_global)

    fitted = fitted.copy()
    fitted[:, 0] += float(offset[0])
    fitted[:, 1] += float(offset[1])
    if closed:
        if len(fitted) == 0:
            return _as_lists(regularize(original.tolist(), epsilon, smooth))
        fitted = np.vstack([fitted, fitted[0]])
    else:
        if fix_start:
            fitted[0] = original[0]
        if fix_end:
            fitted[-1] = original[-1]
    return _as_lists(fitted)


def _fit_curved(
    local: np.ndarray,
    ink: np.ndarray,
    width: float,
    tolerance: float,
    smooth: int,
    closed: bool,
    fix_start: bool,
    fix_end: bool,
) -> np.ndarray | None:
    chains = _chains(local, tolerance, width, closed, fix_start, fix_end)
    if not chains:
        return None
    rendered: list[np.ndarray] = []
    for chain in chains:
        knots = chain["knots"]
        if chain["straight"] or not np.any(chain["free"]):
            rendered.append(knots)
            continue
        # A narrow band ignores parallel strokes that share this component.
        target, valid, origin = _target_band(ink, chain["source"], width, reach=float(width) + 1.25)
        optimized = _optimize_offsets(
            knots,
            chain["free"],
            chain["closed"],
            width,
            target,
            valid,
            origin,
            steps=min(24, 10 + 3 * max(0, smooth)),
        )
        rendered.append(_sample_curve(optimized, chain["closed"], spacing=1.0))
    return _stitch(rendered, closed)


def _recenter_straight(
    local: np.ndarray,
    ink: np.ndarray,
    width: float,
    fix_start: bool,
    fix_end: bool,
) -> np.ndarray:
    """Slide a straight strand along its normal onto the medial axis.

    One shared offset keeps the stroke straight. Junction ends stay put,
    so a bar between two joints cannot leave those joints.
    """
    start = local[0].copy()
    end = local[-1].copy()
    if fix_start and fix_end:
        return np.vstack([start, end])
    direction = end - start
    length = float(np.linalg.norm(direction))
    if length < 1e-6:
        return np.vstack([start, end])
    tangent = direction / length
    normal = np.array([-tangent[1], tangent[0]], dtype=float)
    trust = float(np.clip(width, 1.35, 10.0))
    sigma = gaussian_sigma(width, 0.0, 0.0)
    target, valid, origin = _target_band(ink, local, width)

    def loss_at(offset: float) -> float:
        moved_start = start if fix_start else start + normal * offset
        moved_end = end if fix_end else end + normal * offset
        loss, _ = _loss_and_knot_grad(
            np.vstack([moved_start, moved_end]),
            False,
            sigma,
            target,
            valid,
            origin,
        )
        return loss

    base = loss_at(0.0)
    candidates = np.linspace(-trust, trust, 11)
    best = 0.0
    best_loss = base
    for offset in candidates:
        loss = loss_at(float(offset))
        if loss < best_loss:
            best = float(offset)
            best_loss = loss
    for offset in np.linspace(best - trust / 8.0, best + trust / 8.0, 5):
        offset = float(np.clip(offset, -trust, trust))
        loss = loss_at(offset)
        if loss < best_loss:
            best = offset
            best_loss = loss
    # Ignore sub-pixel numerical ties so a centered skeleton stays put.
    if best_loss > base * 0.995:
        best = 0.0
    moved_start = start if fix_start else start + normal * best
    moved_end = end if fix_end else end + normal * best
    return np.vstack([moved_start, moved_end])


def _optimize_offsets(
    knots: np.ndarray,
    free: np.ndarray,
    closed: bool,
    width: float,
    target: np.ndarray,
    valid: np.ndarray,
    origin: tuple[int, int],
    steps: int,
) -> np.ndarray:
    """Move free knots along their normals to cut reconstruction error."""
    initial = np.asarray(knots, dtype=float).copy()
    normals = _vertex_normals(initial, closed)
    trust = float(np.clip(0.45 * width, 0.75, 1.15))
    sigma = gaussian_sigma(width, 0.0, 0.0)
    offset = np.zeros(len(initial), dtype=float)
    positions = initial
    loss, grad_pos = _loss_and_knot_grad(positions, closed, sigma, target, valid, origin)
    # Take a normalized step along the normal, and keep it only when the
    # splatted reconstruction actually improves. Adam's RMS scaling would
    # turn a tiny residual into a multi-pixel jump and walk off the medial axis.
    step_size = 0.35
    for _ in range(max(1, steps)):
        grad = np.sum(grad_pos * normals, axis=1)
        grad = np.where(free, grad, 0.0)
        magnitude = float(np.max(np.abs(grad))) if grad.size else 0.0
        if magnitude < 1e-8:
            break
        candidate = np.clip(offset - grad / magnitude * step_size, -trust, trust)
        candidate = np.where(free, candidate, 0.0)
        if np.max(np.abs(candidate - offset)) < 1e-4:
            break
        trial = initial + candidate[:, None] * normals
        new_loss, new_grad = _loss_and_knot_grad(trial, closed, sigma, target, valid, origin)
        if new_loss < loss - 1e-8:
            offset = candidate
            loss = new_loss
            grad_pos = new_grad
            step_size = min(0.55, step_size * 1.15)
        else:
            step_size *= 0.5
            if step_size < 0.04:
                break
    return initial + offset[:, None] * normals


def _loss_and_knot_grad(
    knots: np.ndarray,
    closed: bool,
    sigma: float,
    target: np.ndarray,
    valid: np.ndarray,
    origin: tuple[int, int],
) -> tuple[float, np.ndarray]:
    """MSE between α-composited centerline Gaussians and the ink band.

    Knot gradients treat Bézier handles as constant for this step. The
    handle directions are rebuilt from the knots on the next evaluation,
    which is the same stop-gradient used so a smooth chain stays G1.
    """
    knots = np.asarray(knots, dtype=float)
    grad = np.zeros_like(knots)
    count = int(np.count_nonzero(valid))
    if count == 0 or len(knots) < 2:
        return 0.0, grad
    segments = _bezier_segments(knots, closed)
    sigma2 = max(float(sigma) * float(sigma), 1e-4)
    radius = max(2, int(np.ceil(3.0 * sigma)))
    height, width = target.shape
    x0, y0 = origin
    accumulation = np.zeros((height, width), dtype=np.float64)
    stamps: list[tuple | None] = []
    for index, segment in enumerate(segments):
        polygon = float(np.linalg.norm(np.diff(segment, axis=0), axis=1).sum())
        samples = int(np.clip(np.ceil(polygon / max(1.0, 0.8 * sigma)), 2, 36))
        # The knot at t=1 belongs to the next segment, except when closing an open chain.
        parameters = np.linspace(0.0, 1.0, samples, endpoint=index == len(segments) - 1 and not closed)
        for parameter in parameters:
            basis = _bernstein(float(parameter))
            mu = basis @ segment
            local_x = float(mu[0] - x0)
            local_y = float(mu[1] - y0)
            xa = max(0, int(np.floor(local_x - radius)))
            xb = min(width, int(np.ceil(local_x + radius)) + 1)
            ya = max(0, int(np.floor(local_y - radius)))
            yb = min(height, int(np.ceil(local_y + radius)) + 1)
            if xa >= xb or ya >= yb:
                stamps.append(None)
                continue
            xs = np.arange(xa, xb, dtype=np.float64)
            ys = np.arange(ya, yb, dtype=np.float64)
            dx = xs[None, :] - local_x
            dy = ys[:, None] - local_y
            kernel = np.exp(-0.5 * (dx * dx + dy * dy) / sigma2)
            accumulation[ya:yb, xa:xb] += kernel
            stamps.append((ya, yb, xa, xb, kernel, local_x, local_y, basis, index))

    # Order-independent stand-in for α-blending of equal-depth splats:
    # I = 1 - exp(-Σ G). The paper composites with standard α-blending;
    # for a single black stroke the two agree up to a monotone map, and
    # this form has a simple derivative.
    rendered = 1.0 - np.exp(-accumulation)
    residual = (rendered - target) * valid
    loss = float(np.sum(residual * residual) / count)
    coeff = (2.0 / count) * residual * np.exp(-accumulation)
    knot_count = len(knots)
    for stamp in stamps:
        if stamp is None:
            continue
        ya, yb, xa, xb, kernel, local_x, local_y, basis, index = stamp
        weight = coeff[ya:yb, xa:xb] * kernel
        xs = np.arange(xa, xb, dtype=np.float64)
        ys = np.arange(ya, yb, dtype=np.float64)
        dx = xs[None, :] - local_x
        dy = ys[:, None] - local_y
        grad_mu = np.array(
            [np.sum(weight * dx) / sigma2, np.sum(weight * dy) / sigma2],
            dtype=float,
        )
        b0, b1, b2, b3 = basis
        start = index
        finish = (index + 1) % knot_count if closed else index + 1
        grad[start] += grad_mu * (b0 + b1)
        grad[finish] += grad_mu * (b2 + b3)
    return loss, grad


def _target_band(
    ink: np.ndarray,
    polyline: np.ndarray,
    width: float,
    reach: float | None = None,
) -> tuple[np.ndarray, np.ndarray, tuple[int, int]]:
    """Ink near this stroke is the target; nearby paper is a spill penalty.

    Pixels farther away are ignored so a neighboring branch in the same
    connected component does not attract this centerline. The default
    reach is wide enough for an isolated straight strand to see both
    edges; curved strokes pass a narrower one.
    """
    if reach is None:
        reach = float(width) * 2.0 + 2.5
    height, width_px = ink.shape[:2]
    xs = polyline[:, 0]
    ys = polyline[:, 1]
    margin = int(np.ceil(reach + 4.0))
    x0 = max(0, int(np.floor(np.min(xs))) - margin)
    y0 = max(0, int(np.floor(np.min(ys))) - margin)
    x1 = min(width_px, int(np.ceil(np.max(xs))) + margin + 1)
    y1 = min(height, int(np.ceil(np.max(ys))) + margin + 1)
    if x1 <= x0 or y1 <= y0:
        empty = np.zeros((1, 1), dtype=np.float64)
        return empty, np.zeros((1, 1), dtype=bool), (0, 0)
    sub_ink = ink[y0:y1, x0:x1] > 0
    skeleton = np.zeros(sub_ink.shape, dtype=np.uint8)
    poly = np.rint(polyline - np.array([x0, y0])).astype(np.int32)
    poly[:, 0] = np.clip(poly[:, 0], 0, sub_ink.shape[1] - 1)
    poly[:, 1] = np.clip(poly[:, 1], 0, sub_ink.shape[0] - 1)
    if len(np.unique(poly, axis=0)) >= 2:
        cv2.polylines(skeleton, [poly.reshape(-1, 1, 2)], False, 255, 1)
    distance = cv2.distanceTransform(255 - skeleton, cv2.DIST_L2, 3)
    near = distance <= reach
    target = (sub_ink & near).astype(np.float64)
    valid = near
    return target, valid, (x0, y0)


def _chains(
    local: np.ndarray,
    tolerance: float,
    width: float,
    closed: bool,
    fix_start: bool,
    fix_end: bool,
) -> list[dict]:
    simplified = cv2.approxPolyDP(local.astype(np.float32).reshape(-1, 1, 2), tolerance, closed)
    simplified = simplified.reshape(-1, 2).astype(float)
    indices = _match_indices(local, simplified)
    sharp = {
        indices[k]
        for k in range(len(indices))
        if _is_sharp(simplified, k, closed)
    }
    count = len(local)
    if not closed:
        anchors = [0]
        anchors.extend(sorted(index for index in sharp if 0 < index < count - 1))
        anchors.append(count - 1)
        ranges = [(anchors[i], anchors[i + 1]) for i in range(len(anchors) - 1) if anchors[i + 1] > anchors[i]]
        chains = []
        for start, finish in ranges:
            fix = (
                start in sharp or (start == 0 and fix_start),
                finish in sharp or (finish == count - 1 and fix_end),
            )
            chains.append(_make_chain(local[start : finish + 1], width, tolerance, fix, False))
        return chains

    ordered = sorted(sharp)
    if not ordered:
        return [_make_chain(local, width, tolerance, (False, False), True)]
    chains = []
    for index, start in enumerate(ordered):
        finish = ordered[(index + 1) % len(ordered)]
        if finish > start:
            sub = local[start : finish + 1]
        else:
            sub = np.vstack([local[start:], local[: finish + 1]])
        chains.append(_make_chain(sub, width, tolerance, (True, True), False))
    return chains


def _make_chain(
    sub: np.ndarray,
    width: float,
    tolerance: float,
    fix_ends: tuple[bool, bool],
    closed: bool,
) -> dict:
    sub = np.asarray(sub, dtype=float).copy()
    if not closed and _max_chord_distance(sub) <= tolerance:
        return {
            "knots": np.vstack([sub[0], sub[-1]]),
            "free": np.array([False, False]),
            "closed": False,
            "straight": True,
            "source": sub,
        }
    spacing = float(np.clip(1.25 * width, 4.0, 9.0))
    knots = _resample(sub, spacing, closed)
    if not closed:
        knots[0] = sub[0]
        knots[-1] = sub[-1]
    free = np.ones(len(knots), dtype=bool)
    if not closed:
        free[0] = not fix_ends[0]
        free[-1] = not fix_ends[1]
    return {"knots": knots, "free": free, "closed": closed, "straight": False, "source": sub}


def _inside_tube(source: np.ndarray, fitted: np.ndarray, closed: bool, tolerance: float) -> bool:
    """Both polylines have to stay in a thin tube around each other."""
    if fitted is None or len(fitted) < 2 or len(source) < 2:
        return False
    source_line = _closed_line(source, closed)
    fitted_line = _closed_line(fitted, closed)
    return (
        float(np.max(_distance_to_polyline(source_line, fitted_line))) <= tolerance
        and float(np.max(_distance_to_polyline(fitted_line, source_line))) <= tolerance
    )


def _closed_line(points: np.ndarray, closed: bool) -> np.ndarray:
    if closed and len(points) >= 2 and float(np.linalg.norm(points[0] - points[-1])) > 1e-6:
        return np.vstack([points, points[0]])
    return points


def _on_ink_fraction(ink: np.ndarray, points: np.ndarray, limit: float | None = None) -> float:
    if limit is None:
        limit = 1.35
    inverse = np.where(ink > 0, 0, 255).astype(np.uint8)
    distance = cv2.distanceTransform(inverse, cv2.DIST_L2, 3)
    height, width = distance.shape
    inside = 0
    for x, y in points:
        xi = int(round(float(x)))
        yi = int(round(float(y)))
        if 0 <= xi < width and 0 <= yi < height and distance[yi, xi] <= limit:
            inside += 1
    return inside / max(1, len(points))


def _stroke_half_width(ink: np.ndarray) -> float:
    """Medial half-width from the distance transform.

    A high percentile over the whole stroke is the radius at the medial
    axis. Sampling only an off-center skeleton would underestimate it.
    """
    binary = (ink > 0).astype(np.uint8) * 255
    if cv2.countNonZero(binary) == 0:
        return 1.5
    distance = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
    values = distance[ink > 0]
    if values.size == 0:
        return 1.5
    return float(np.clip(np.percentile(values, 90), 0.8, 36.0))


def _bezier_segments(knots: np.ndarray, closed: bool) -> list[np.ndarray]:
    count = len(knots)
    segment_count = count if closed else count - 1
    segments: list[np.ndarray] = []
    for index in range(segment_count):
        start = knots[index]
        finish = knots[(index + 1) % count]
        chord = finish - start
        length = float(np.linalg.norm(chord))
        if length < 1e-6:
            continue
        handle = length / 3.0
        tangent_start = _tangent(knots, index, closed)
        tangent_finish = _tangent(knots, (index + 1) % count, closed)
        if float(np.dot(tangent_start, chord)) < 0.0:
            tangent_start = chord / length
        if float(np.dot(tangent_finish, chord)) < 0.0:
            tangent_finish = chord / length
        control1 = start + tangent_start * handle
        control2 = finish - tangent_finish * handle
        segments.append(np.vstack([start, control1, control2, finish]))
    return segments


def _sample_curve(knots: np.ndarray, closed: bool, spacing: float) -> np.ndarray:
    segments = _bezier_segments(knots, closed)
    if not segments:
        return np.asarray(knots, dtype=float)
    points = [segments[0][0]]
    for segment in segments:
        chord = float(np.linalg.norm(segment[-1] - segment[0]))
        count = max(2, int(np.ceil(max(chord, 1.0) / spacing)) + 1)
        for parameter in np.linspace(0.0, 1.0, count)[1:]:
            points.append(_bernstein(float(parameter)) @ segment)
    return np.asarray(points, dtype=float)


def _stitch(parts: list[np.ndarray], closed: bool) -> np.ndarray:
    rows: list[np.ndarray] = []
    for part in parts:
        if len(part) == 0:
            continue
        if rows and np.linalg.norm(rows[-1][-1] - part[0]) <= 1e-6:
            part = part[1:]
        if len(part):
            rows.append(part)
    if not rows:
        return np.zeros((0, 2), dtype=float)
    fitted = np.vstack(rows)
    if closed and len(fitted):
        fitted = fitted[:-1] if np.linalg.norm(fitted[0] - fitted[-1]) <= 1e-6 else fitted
    return fitted


def _vertex_normals(knots: np.ndarray, closed: bool) -> np.ndarray:
    normals = np.zeros_like(knots)
    for index in range(len(knots)):
        tangent = _tangent(knots, index, closed)
        normals[index] = (-tangent[1], tangent[0])
    return normals


def _tangent(knots: np.ndarray, index: int, closed: bool) -> np.ndarray:
    count = len(knots)
    if count < 2:
        return np.array([1.0, 0.0])
    if closed:
        vector = knots[(index + 1) % count] - knots[(index - 1) % count]
    elif index <= 0:
        vector = knots[1] - knots[0]
    elif index >= count - 1:
        vector = knots[-1] - knots[-2]
    else:
        vector = knots[index + 1] - knots[index - 1]
    length = float(np.linalg.norm(vector))
    if length < 1e-8:
        return np.array([1.0, 0.0])
    return vector / length


def _bernstein(parameter: float) -> np.ndarray:
    inverse = 1.0 - parameter
    return np.array(
        [
            inverse**3,
            3.0 * inverse**2 * parameter,
            3.0 * inverse * parameter**2,
            parameter**3,
        ],
        dtype=float,
    )


def _resample(points: np.ndarray, spacing: float, closed: bool) -> np.ndarray:
    sequence = np.vstack([points, points[:1]]) if closed else np.asarray(points, dtype=float)
    lengths = np.linalg.norm(np.diff(sequence, axis=0), axis=1)
    total = float(lengths.sum())
    if total < 1e-6:
        return np.asarray(points[:1], dtype=float)
    if closed:
        count = int(np.clip(round(total / spacing), 4, 48))
        targets = np.arange(count, dtype=float) / count * total
    else:
        count = int(np.clip(round(total / spacing) + 1, 2, 48))
        targets = np.linspace(0.0, total, count)
    cumulative = np.concatenate([[0.0], np.cumsum(lengths)])
    sampled = []
    for target in targets:
        index = int(np.searchsorted(cumulative, target, side="right") - 1)
        index = min(max(index, 0), len(lengths) - 1)
        span = float(lengths[index])
        alpha = 0.0 if span < 1e-8 else (float(target) - float(cumulative[index])) / span
        alpha = min(1.0, max(0.0, alpha))
        sampled.append(sequence[index] * (1.0 - alpha) + sequence[index + 1] * alpha)
    return np.asarray(sampled, dtype=float)


def _match_indices(points: np.ndarray, simplified: np.ndarray) -> list[int]:
    indices: list[int] = []
    cursor = 0
    last = len(points) - 1
    for vertex in simplified:
        window = points[cursor:]
        if len(window) == 0:
            indices.append(last)
            continue
        cursor += int(np.argmin(np.linalg.norm(window - vertex, axis=1)))
        indices.append(cursor)
        if cursor < last:
            cursor += 1
    return indices


def _is_sharp(simplified: np.ndarray, index: int, closed: bool) -> bool:
    count = len(simplified)
    if count < 3 or (not closed and (index == 0 or index == count - 1)):
        return False
    previous = simplified[(index - 1) % count]
    nxt = simplified[(index + 1) % count]
    incoming = simplified[index] - previous
    outgoing = nxt - simplified[index]
    incoming_norm = float(np.linalg.norm(incoming))
    outgoing_norm = float(np.linalg.norm(outgoing))
    if incoming_norm < 1e-6 or outgoing_norm < 1e-6:
        return False
    return float(np.dot(incoming, outgoing)) < _SHARP_COSINE * incoming_norm * outgoing_norm


def _max_chord_distance(points: np.ndarray) -> float:
    if len(points) < 3:
        return 0.0
    delta = points[-1] - points[0]
    length = float(np.linalg.norm(delta))
    if length <= 1e-8:
        return float(np.max(np.linalg.norm(points - points[0], axis=1)))
    distances = np.abs((points[:, 0] - points[0, 0]) * delta[1] - (points[:, 1] - points[0, 1]) * delta[0]) / length
    return float(np.max(distances))


def _distance_to_polyline(points: np.ndarray, polyline: np.ndarray) -> np.ndarray:
    if len(polyline) == 1:
        return np.linalg.norm(points - polyline[0], axis=1)
    best = np.full(len(points), np.inf)
    for start, finish in zip(polyline[:-1], polyline[1:]):
        edge = finish - start
        length2 = float(np.dot(edge, edge))
        if length2 < 1e-12:
            distance = np.linalg.norm(points - start, axis=1)
        else:
            alpha = np.clip(((points - start) @ edge) / length2, 0.0, 1.0)
            distance = np.linalg.norm(points - (start + alpha[:, None] * edge), axis=1)
        best = np.minimum(best, distance)
    if len(polyline) >= 3 and np.linalg.norm(polyline[0] - polyline[-1]) <= 1e-6:
        return best
    return best


def _as_lists(points) -> list[list[float]]:
    return [[float(x), float(y)] for x, y in np.asarray(points, dtype=float).reshape(-1, 2)]
