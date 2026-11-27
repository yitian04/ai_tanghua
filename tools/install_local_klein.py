"""Download missing Klein 4B files from the ModelScope mirrors in resumable ranges."""
import argparse
import concurrent.futures
import os
import re
import shutil
from pathlib import Path
from urllib.request import Request, urlopen

MIRROR = "https://modelscope.cn/models"
FILES = {
    "diffusion_models/flux-2-klein-4b-fp8.safetensors":
        "black-forest-labs/FLUX.2-klein-4b-fp8/resolve/master/flux-2-klein-4b-fp8.safetensors",
    "text_encoders/qwen_3_4b.safetensors":
        "Comfy-Org/z_image_turbo/resolve/master/split_files/text_encoders/qwen_3_4b.safetensors",
    "vae/flux2-vae.safetensors":
        "Comfy-Org/flux2-dev/resolve/master/split_files/vae/flux2-vae.safetensors",
}
PART_SIZE = 32 * 1024 * 1024


def fetch_range(url, start, end, destination):
    for attempt in range(3):
        try:
            req = Request(url, headers={"Range": f"bytes={start}-{end}"})
            with urlopen(req, timeout=45) as response:
                header = response.headers.get("Content-Range", "")
                if not header.startswith(f"bytes {start}-{end}/"):
                    raise OSError(f"Unexpected range: {header!r}")
                with destination.open("wb") as handle:
                    shutil.copyfileobj(response, handle, 1024 * 1024)
            if destination.stat().st_size != end - start + 1:
                raise OSError("Incomplete range")
            return
        except OSError:
            if attempt == 2:
                raise


def download(url, path, workers):
    if path.is_file():
        return
    with urlopen(Request(url, headers={"Range": "bytes=0-0"}), timeout=30) as response:
        match = re.fullmatch(r"bytes 0-0/(\d+)", response.headers.get("Content-Range", ""))
        if not match:
            raise OSError("The mirror did not declare a ranged model file.")
        total = int(match[1])
    parts_dir = path.with_name(path.name + ".parts")
    parts_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        pending = []
        for start in range(0, total, PART_SIZE):
            end = min(start + PART_SIZE, total) - 1
            part = parts_dir / f"{start:012d}.part"
            parts.append(part)
            if part.is_file() and part.stat().st_size == end - start + 1:
                continue
            pending.append(executor.submit(fetch_range, url, start, end, part))
        for index, future in enumerate(concurrent.futures.as_completed(pending), 1):
            future.result()
            if index % 10 == 0:
                print(f"{path.name}: {index}/{len(pending)} new parts", flush=True)
    staging = path.with_suffix(".assembling")
    with staging.open("wb") as handle:
        for part in parts:
            with part.open("rb") as source:
                shutil.copyfileobj(source, handle, 1024 * 1024)
    if staging.stat().st_size != total:
        raise OSError(f"Incomplete model: {path.name}")
    os.replace(staging, path)
    for part in parts:
        part.unlink()
    parts_dir.rmdir()
    print(f"Ready: {path}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, choices=range(1, 33), metavar="1-32", default=12)
    args = parser.parse_args()
    models = Path("data/ai_generation/comfyui/models")
    for name, url in FILES.items():
        download(f"{MIRROR}/{url}?download=true", models / name, args.workers)
