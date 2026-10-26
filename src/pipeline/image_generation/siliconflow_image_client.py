from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class SiliconFlowImageError(RuntimeError):
    """Raised when image generation fails."""


@dataclass
class SiliconFlowImageRequest:
    prompt: str
    model: str = "Qwen/Qwen-Image"
    size: str = "1328x1328"
    negative_prompt: str = "color, grayscale, shadow, texture, background, filled black areas, tiny fragments, complex details"
    steps: int = 20
    seed: int | None = None
    extra_body: dict[str, Any] = field(default_factory=dict)


class SiliconFlowImageClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.siliconflow.cn/v1",
        timeout_s: int = 120,
    ) -> None:
        self.api_key = api_key or os.getenv("AI_IMAGE_API_KEY", "") or os.getenv("SILICONFLOW_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def generate_and_save(self, request: SiliconFlowImageRequest, output_path: str | Path) -> Path:
        if not self.api_key:
            raise SiliconFlowImageError("API Key is not set. Input an API Key or set AI_IMAGE_API_KEY.")

        body: dict[str, Any] = {
            "model": request.model,
            "prompt": request.prompt,
            "image_size": request.size,
            "num_inference_steps": int(request.steps),
        }
        if request.negative_prompt:
            body["negative_prompt"] = request.negative_prompt
        if request.seed is not None:
            body["seed"] = int(request.seed)
        body.update(request.extra_body)

        response = self._post_json("/images/generations", body)
        image_bytes = self._extract_image_bytes(response)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(image_bytes)
        return output

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Enable-Watermark": "0",
            },
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SiliconFlowImageError(f"Image API request failed: HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise SiliconFlowImageError(f"Image API request failed: {exc}") from exc

    def _extract_image_bytes(self, response: dict[str, Any]) -> bytes:
        item = None
        data = response.get("data")
        if isinstance(data, list) and data:
            item = data[0]
        elif isinstance(response.get("images"), list) and response["images"]:
            item = response["images"][0]
        if not isinstance(item, dict):
            raise SiliconFlowImageError(f"Unexpected image API response: {response}")

        b64_json = item.get("b64_json") or item.get("base64")
        if b64_json:
            return base64.b64decode(str(b64_json))

        url = item.get("url")
        if not url:
            raise SiliconFlowImageError(f"No image URL or base64 payload in response: {response}")
        return self._download_url(str(url))

    def _download_url(self, url: str) -> bytes:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise SiliconFlowImageError(f"Unsupported image URL: {url}")
        try:
            with urllib.request.urlopen(url, timeout=self.timeout_s) as response:
                return response.read()
        except Exception as exc:
            raise SiliconFlowImageError(f"Failed to download generated image: {exc}") from exc
