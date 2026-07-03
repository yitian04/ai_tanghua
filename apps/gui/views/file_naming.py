from __future__ import annotations

import re
import time
from pathlib import Path


def sanitize_filename(value: str, fallback: str = "job") -> str:
    text = (value or "").strip()
    if not text:
        text = fallback
    text = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", text, flags=re.UNICODE)
    text = text.strip("._")
    return text[:80] or fallback


def build_output_path(root_dir: str, folder: str, prefix: str, suffix: str, extension: str) -> Path:
    output_dir = Path(root_dir) / "data" / folder
    output_dir.mkdir(parents=True, exist_ok=True)
    clean_prefix = sanitize_filename(prefix)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return output_dir / f"{clean_prefix}_{stamp}_{suffix}.{extension.lstrip('.')}"


def infer_prefix_from_path(path: str, fallback: str = "job") -> str:
    if not path:
        return fallback
    stem = Path(path).stem
    for marker in ("_input", "_curves", "_trajectory"):
        if marker in stem:
            stem = stem.split(marker, 1)[0]
    return sanitize_filename(stem, fallback=fallback)
