from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class PublicImageHostError(RuntimeError):
    """Raised when a local image cannot be published as an accessible URL."""


class ImgBBImageHost:
    """Upload local images to ImgBB and return the direct public image URL."""

    provider_id = "imgbb"

    def __init__(self, api_key: str, *, expiration_s: int = 86400, timeout_s: int = 60) -> None:
        self.api_key = api_key.strip()
        self.expiration_s = max(60, min(int(expiration_s), 15_552_000))
        self.timeout_s = int(timeout_s)

    def upload(self, image_path: str | Path) -> str:
        path = Path(image_path)
        if not path.is_file():
            raise PublicImageHostError(f"待发布图片不存在：{path}")
        if not self.api_key:
            raise PublicImageHostError("请先配置 ImgBB API Key。")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        query = urllib.parse.urlencode(
            {"key": self.api_key, "expiration": str(self.expiration_s)}
        )
        body = urllib.parse.urlencode({"image": encoded, "name": path.stem}).encode("utf-8")
        request = urllib.request.Request(
            f"https://api.imgbb.com/1/upload?{query}",
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise PublicImageHostError(
                f"ImgBB 上传失败（HTTP {exc.code}）：{_safe_detail(detail)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise PublicImageHostError(f"无法连接 ImgBB：{exc.reason}") from exc
        except Exception as exc:
            raise PublicImageHostError("ImgBB 返回了无法解析的数据。") from exc
        data: Any = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise PublicImageHostError("ImgBB 没有返回图片地址。")
        url = str(data.get("url") or data.get("display_url") or "").strip()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise PublicImageHostError("ImgBB 返回了无效的图片地址。")
        return url


def _safe_detail(detail: str, limit: int = 500) -> str:
    compact = " ".join(detail.split())
    return compact[:limit] + ("…" if len(compact) > limit else "")
