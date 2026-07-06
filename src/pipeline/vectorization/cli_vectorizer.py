from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Literal

import cv2
import numpy as np


SvgVectorizer = Literal["outline_svg"]
OutlineEngine = Literal["auto", "vtracer", "potrace"]


class VectorizationToolError(RuntimeError):
    pass


def available_vectorization_tools() -> dict[str, str | None]:
    return {
        "potrace": _find_tool("potrace", ["potrace.exe", "potrace"]),
        "vtracer": _find_tool("vtracer", ["vtracer.exe", "vtracer"]),
    }


def vectorize_binary_with_cli(
    binary: np.ndarray,
    *,
    vectorizer: SvgVectorizer,
    outline_engine: OutlineEngine = "auto",
    work_dir: str | Path | None = None,
    svg_output_path: str | Path | None = None,
    timeout_s: int = 45,
    speckle_size: int = 8,
) -> Path:
    if binary is None or binary.size == 0:
        raise VectorizationToolError("Binary image is empty; cannot run SVG vectorizer.")
    if vectorizer != "outline_svg":
        raise VectorizationToolError("Centerline AutoTrace backend has been removed. Use outline_svg or OpenCV fallback.")

    tools = available_vectorization_tools()
    base_dir = Path(work_dir) if work_dir else Path(tempfile.gettempdir()) / "ai_tanghua_vectorization"
    base_dir.mkdir(parents=True, exist_ok=True)
    run_dir = base_dir / uuid.uuid4().hex[:12]
    run_dir.mkdir(parents=True, exist_ok=True)
    output_svg = Path(svg_output_path) if svg_output_path else run_dir / "vectorized.svg"
    output_svg.parent.mkdir(parents=True, exist_ok=True)

    binary_mask = (binary > 0).astype(np.uint8)
    png_path = run_dir / "input_binary.png"
    pbm_path = run_dir / "input_binary.pbm"
    _write_binary_png(binary_mask, png_path)
    _write_ascii_pbm(binary_mask, pbm_path)

    engine = _select_outline_engine(outline_engine, tools)
    if engine == "vtracer":
        commands = [
            [
                tools["vtracer"] or "vtracer",
                "--input",
                str(png_path),
                "--output",
                str(output_svg),
                "--colormode",
                "bw",
                "--mode",
                "spline",
                "--filter_speckle",
                str(max(0, int(speckle_size))),
            ],
            [
                tools["vtracer"] or "vtracer",
                "--input",
                str(png_path),
                "--output",
                str(output_svg),
                "--colormode",
                "binary",
                "--mode",
                "spline",
            ],
        ]
        _run_first_success(commands, timeout_s=timeout_s)
    else:
        command = [
            tools["potrace"] or "potrace",
            str(pbm_path),
            "-s",
            "-o",
            str(output_svg),
            "-t",
            str(max(0, int(speckle_size))),
        ]
        _run_command(command, timeout_s=timeout_s)

    if not output_svg.exists() or output_svg.stat().st_size == 0:
        raise VectorizationToolError(f"SVG backend did not produce a valid file: {output_svg}")
    return output_svg


def _find_tool(tool_name: str, executable_names: list[str]) -> str | None:
    root = _project_root()
    search_dirs = [
        root / "tools" / tool_name,
        root / "tools" / tool_name.capitalize(),
        root / "tools" / tool_name.upper(),
        root / "tools" / _tool_display_dir(tool_name),
        root / "tools",
    ]
    for directory in search_dirs:
        for executable in executable_names:
            candidate = directory / executable
            if candidate.is_file():
                return str(candidate)

    found = shutil.which(tool_name)
    if found:
        return found

    for candidate in _known_windows_locations(tool_name):
        if candidate.is_file():
            return str(candidate)
    return None


def _project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "src").is_dir() and (parent / "apps").is_dir():
            return parent
    return current.parents[3]


def _tool_display_dir(tool_name: str) -> str:
    names = {
        "potrace": "Potrace",
        "vtracer": "VTracer",
    }
    return names.get(tool_name, tool_name)


def _known_windows_locations(tool_name: str) -> list[Path]:
    if os.name != "nt":
        return []
    names = {
        "potrace": ["Potrace/potrace.exe"],
        "vtracer": ["VTracer/vtracer.exe"],
    }.get(tool_name, [])
    bases = [Path("C:/Program Files"), Path("C:/Program Files (x86)"), Path("D:/Program Files")]
    return [base / name for base in bases for name in names]


def _select_outline_engine(outline_engine: OutlineEngine, tools: dict[str, str | None]) -> Literal["vtracer", "potrace"]:
    if outline_engine == "vtracer":
        if not tools["vtracer"]:
            raise VectorizationToolError("vtracer was not found. Put vtracer.exe under tools/VTracer/ or choose auto/potrace.")
        return "vtracer"
    if outline_engine == "potrace":
        if not tools["potrace"]:
            raise VectorizationToolError("potrace was not found. Put potrace.exe under tools/Potrace/ or choose auto/vtracer.")
        return "potrace"
    if tools["vtracer"]:
        return "vtracer"
    if tools["potrace"]:
        return "potrace"
    raise VectorizationToolError("vtracer or potrace was not found. Put an executable under tools/VTracer/ or tools/Potrace/.")


def _run_command(command: list[str], *, timeout_s: int) -> None:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout_s)),
        )
    except subprocess.TimeoutExpired as exc:
        raise VectorizationToolError(f"SVG backend timed out: {' '.join(command[:2])}") from exc
    except OSError as exc:
        raise VectorizationToolError(f"Cannot start SVG backend: {exc}") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        message = f"SVG backend failed with exit code {result.returncode}: {command[0]}"
        if detail:
            message += f"; output: {detail[:800]}"
        raise VectorizationToolError(message)


def _run_first_success(commands: list[list[str]], *, timeout_s: int) -> None:
    errors: list[str] = []
    for command in commands:
        try:
            _run_command(command, timeout_s=timeout_s)
            return
        except VectorizationToolError as exc:
            errors.append(str(exc))
    raise VectorizationToolError("SVG backend failed: " + " | ".join(errors)[-1200:])


def _write_binary_png(binary_mask: np.ndarray, path: Path) -> None:
    image = np.where(binary_mask > 0, 0, 255).astype(np.uint8)
    ok = cv2.imwrite(str(path), image)
    if not ok:
        raise VectorizationToolError(f"Failed to write temporary PNG: {path}")


def _write_ascii_pbm(binary_mask: np.ndarray, path: Path) -> None:
    height, width = binary_mask.shape[:2]
    rows = [" ".join("1" if value else "0" for value in row) for row in binary_mask]
    path.write_text(f"P1\n{width} {height}\n" + "\n".join(rows) + "\n", encoding="ascii")