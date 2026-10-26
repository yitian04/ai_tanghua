from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from src.pipeline.image_generation.providers import (
    ImageCallResult,
    ImageProviderError,
    ImageRequestOptions,
)


class PiGatewayError(ImageProviderError):
    """Raised when the local pi-ai model gateway cannot complete an operation."""


class PiModelGatewayClient:
    def __init__(
        self,
        root_dir: str | Path,
        *,
        base_url: str = "http://127.0.0.1:8766",
        timeout_s: int = 180,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.base_url = base_url.rstrip("/")
        self.timeout_s = int(timeout_s)
        self.data_dir = self.root_dir / "data" / "model_gateway"
        self.token_path = self.data_dir / "gateway_token.txt"
        self.server_path = self.root_dir / "services" / "pi_model_gateway" / "server.mjs"
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def ensure_running(self, *, wait_s: float = 10.0) -> dict[str, Any]:
        try:
            return self.health()
        except PiGatewayError as exc:
            if "连接" not in str(exc) and "refused" not in str(exc).lower():
                raise

        if not self.server_path.is_file():
            raise PiGatewayError(f"找不到 pi 模型网关：{self.server_path}")
        if not (self.root_dir / "node_modules" / "@earendil-works" / "pi-ai").is_dir():
            raise PiGatewayError("pi-ai 尚未安装，请先在项目目录运行 npm install。")

        token = self._token(create=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.data_dir / "gateway.log"
        environment = dict(os.environ)
        environment["TANGHUA_MODEL_GATEWAY_TOKEN"] = token
        creation_flags = 0
        if os.name == "nt":
            creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        with log_path.open("ab") as log_file:
            subprocess.Popen(
                ["node", str(self.server_path)],
                cwd=str(self.root_dir),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=creation_flags,
            )

        deadline = time.monotonic() + max(1.0, wait_s)
        last_error = ""
        while time.monotonic() < deadline:
            time.sleep(0.2)
            try:
                return self.health()
            except PiGatewayError as exc:
                last_error = str(exc)
        raise PiGatewayError(f"pi 模型网关启动失败：{last_error or '等待超时'}")

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def providers(self) -> list[dict[str, Any]]:
        return list(self._request("GET", "/providers").get("providers") or [])

    def image_models(self, provider_id: str = "") -> list[dict[str, Any]]:
        query = ""
        if provider_id:
            query = "?" + urllib.parse.urlencode({"provider": provider_id})
        return list(self._request("GET", f"/models{query}").get("models") or [])

    def save_api_key(self, provider_id: str, api_key: str) -> None:
        self._request(
            "POST",
            "/auth/api-key",
            {"providerId": provider_id, "apiKey": api_key},
        )

    def logout(self, provider_id: str) -> None:
        self._request("POST", "/auth/logout", {"providerId": provider_id})

    def start_oauth(self, provider_id: str) -> dict[str, Any]:
        return self._request("POST", "/auth/oauth/start", {"providerId": provider_id})

    def oauth_status(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/auth/oauth/{urllib.parse.quote(session_id)}")

    def oauth_respond(self, session_id: str, value: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/auth/oauth/{urllib.parse.quote(session_id)}",
            {"value": value},
        )

    def generate_image(
        self,
        *,
        provider_id: str,
        model_id: str,
        prompt: str,
        source_images: list[str | Path] | None = None,
    ) -> dict[str, Any]:
        images = []
        for source_value in source_images or []:
            source = Path(source_value)
            if not source.is_file():
                raise PiGatewayError(f"参考图不存在：{source}")
            mime_type = mimetypes.guess_type(source.name)[0] or "image/png"
            images.append(
                {
                    "mimeType": mime_type,
                    "data": base64.b64encode(source.read_bytes()).decode("ascii"),
                }
            )
        return self._request(
            "POST",
            "/images/generate",
            {
                "providerId": provider_id,
                "modelId": model_id,
                "prompt": prompt,
                "images": images,
            },
        )

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = None
        headers = {
            "Accept": "application/json",
            "X-Gateway-Token": self._token(create=False),
        }
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=payload,
            method=method,
            headers=headers,
        )
        try:
            with self._opener.open(request, timeout=self.timeout_s) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                detail = str(json.loads(raw).get("error") or raw)
            except Exception:
                detail = raw
            raise PiGatewayError(f"pi 模型网关请求失败（HTTP {exc.code}）：{detail}") from exc
        except urllib.error.URLError as exc:
            raise PiGatewayError(f"无法连接 pi 模型网关：{exc.reason}") from exc
        except TimeoutError as exc:
            raise PiGatewayError("pi 模型网关请求超时。") from exc
        except json.JSONDecodeError as exc:
            raise PiGatewayError("pi 模型网关返回了无效数据。") from exc
        if not isinstance(result, dict):
            raise PiGatewayError("pi 模型网关返回格式错误。")
        return result

    def _token(self, *, create: bool) -> str:
        try:
            token = self.token_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            if not create:
                return ""
            self.data_dir.mkdir(parents=True, exist_ok=True)
            token = secrets.token_hex(32)
            self.token_path.write_text(token + "\n", encoding="utf-8")
        if not token and create:
            token = secrets.token_hex(32)
            self.token_path.write_text(token + "\n", encoding="utf-8")
        return token


class PiGatewayImageProvider:
    provider_id: str
    negative_prompt_mode = "unsupported"

    def __init__(
        self,
        client: PiModelGatewayClient,
        *,
        provider_id: str,
        model_id: str,
    ) -> None:
        self.client = client
        self.provider_id = provider_id
        self.model_id = model_id

    def generate(
        self,
        prompt: str,
        output_path: str | Path,
        options: ImageRequestOptions,
    ) -> ImageCallResult:
        del options
        response = self.client.generate_image(
            provider_id=self.provider_id,
            model_id=self.model_id,
            prompt=prompt,
        )
        return self._save_response(response, output_path)

    def edit(
        self,
        prompt: str,
        source_image: str | Path,
        output_path: str | Path,
        options: ImageRequestOptions,
    ) -> ImageCallResult:
        del options
        response = self.client.generate_image(
            provider_id=self.provider_id,
            model_id=self.model_id,
            prompt=prompt,
            source_images=[source_image],
        )
        return self._save_response(response, output_path)

    def test_connection(self) -> tuple[bool, str]:
        try:
            health = self.client.ensure_running()
            return True, f"pi 模型网关已连接（pi-ai {health.get('piVersion', 'unknown')}）"
        except Exception as exc:
            return False, str(exc)

    def _save_response(
        self,
        response: dict[str, Any],
        output_path: str | Path,
    ) -> ImageCallResult:
        images = response.get("images") or []
        if not images or not isinstance(images[0], dict):
            raise PiGatewayError("pi 模型没有返回图像。")
        encoded = str(images[0].get("data") or "")
        mime_type = str(images[0].get("mimeType") or "image/png").lower()
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise PiGatewayError("pi 模型返回的图像编码无效。") from exc
        if mime_type == "image/svg+xml":
            raise PiGatewayError("所选模型返回 SVG；当前糖画线稿流程需要 PNG/JPEG/WebP 栅格图。")
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with Image.open(io.BytesIO(image_bytes)) as image:
                normalized = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                normalized.save(output, format="PNG")
        except (UnidentifiedImageError, OSError) as exc:
            raise PiGatewayError(f"pi 模型返回的 {mime_type} 图像无法读取。") from exc
        return ImageCallResult(
            output_path=output,
            provider_id=str(response.get("providerId") or self.provider_id),
            model_id=str(response.get("modelId") or self.model_id),
            request_id=str(response.get("responseId") or ""),
            usage=dict(response.get("usage") or {}),
            revised_prompt=str(response.get("text") or ""),
        )
