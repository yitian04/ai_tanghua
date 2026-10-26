from __future__ import annotations

import base64
import json
import mimetypes
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

from PIL import Image


class ImageProviderError(RuntimeError):
    """Raised when an image provider cannot complete a request."""


class UnsupportedImageCapability(ImageProviderError):
    """Raised when the selected provider does not support the requested operation."""


@dataclass(frozen=True)
class ProviderSpec:
    provider_id: str
    label: str
    default_base_url: str
    default_model: str
    supports_generation: bool
    supports_edit: bool
    default_edit_model: str = ""
    notes: str = ""


@dataclass
class ProviderConfig:
    provider_id: str
    model: str
    api_key: str = ""
    base_url: str = ""
    edit_model: str = ""
    timeout_s: int = 180


@dataclass
class ImageRequestOptions:
    size: str = "1024x1024"
    quality: str = "medium"
    output_format: str = "png"
    extra_body: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ImageCallResult:
    output_path: Path
    provider_id: str
    model_id: str
    request_id: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    revised_prompt: str = ""


PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(
        provider_id="openai",
        label="OpenAI Images API",
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-image-2.5-sunburst",
        supports_generation=True,
        supports_edit=True,
        notes="自动生成与基于原图编辑；API 用量与 ChatGPT 订阅分开计费。",
    ),
    "siliconflow": ProviderSpec(
        provider_id="siliconflow",
        label="硅基流动 SiliconFlow",
        default_base_url="https://api.siliconflow.cn/v1",
        default_model="Qwen/Qwen-Image",
        supports_generation=True,
        supports_edit=True,
        default_edit_model="Qwen/Qwen-Image-Edit-2509",
        notes="文生图和参考图编辑均调用 /images/generations，但使用不同模型。",
    ),
    "bananapro": ProviderSpec(
        provider_id="bananapro",
        label="BananaPro 多模型 API",
        default_base_url="https://www.bananapro.site",
        default_model="nano-banana-pro",
        supports_generation=True,
        supports_edit=True,
        default_edit_model="seedream-5-pro",
        notes="第一阶段默认 Nano Banana Pro，第二阶段默认 Seedream 5 Pro。",
    ),
    "custom_openai": ProviderSpec(
        provider_id="custom_openai",
        label="自定义 OpenAI Images 兼容接口",
        default_base_url="",
        default_model="gpt-image-2.5-sunburst",
        supports_generation=True,
        supports_edit=True,
        notes="服务端必须兼容 /images/generations 与 /images/edits。",
    ),
}


class ImageProvider(Protocol):
    provider_id: str

    def generate(
        self,
        prompt: str,
        output_path: str | Path,
        options: ImageRequestOptions,
    ) -> ImageCallResult: ...

    def edit(
        self,
        prompt: str,
        source_image: str | Path,
        output_path: str | Path,
        options: ImageRequestOptions,
    ) -> ImageCallResult: ...

    def test_connection(self) -> tuple[bool, str]: ...


def create_image_provider(config: ProviderConfig) -> ImageProvider:
    if config.provider_id not in PROVIDER_SPECS:
        raise ImageProviderError(f"未知模型服务商：{config.provider_id}")
    spec = PROVIDER_SPECS[config.provider_id]
    base_url = (config.base_url or spec.default_base_url).rstrip("/")
    api_key = config.api_key.strip() or _provider_api_key(config.provider_id)
    if config.provider_id == "siliconflow":
        return SiliconFlowImagesProvider(
            api_key=api_key,
            base_url=base_url,
            generation_model=config.model.strip() or spec.default_model,
            edit_model=config.edit_model.strip() or spec.default_edit_model,
            timeout_s=config.timeout_s,
        )
    if config.provider_id == "bananapro":
        from src.pipeline.image_generation.banana_pro import BananaProImagesProvider

        return BananaProImagesProvider(
            api_key=api_key,
            base_url=base_url,
            generation_model=config.model.strip() or spec.default_model,
            edit_model=config.edit_model.strip() or spec.default_edit_model,
            timeout_s=config.timeout_s,
        )
    return OpenAIImagesProvider(
        provider_id=config.provider_id,
        api_key=api_key,
        base_url=base_url,
        model=config.model.strip() or spec.default_model,
        timeout_s=config.timeout_s,
        supports_edit=spec.supports_edit,
    )


class SiliconFlowImagesProvider:
    """Native client for SiliconFlow text-to-image and image editing."""

    provider_id = "siliconflow"
    negative_prompt_mode = "native"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        generation_model: str,
        edit_model: str,
        timeout_s: int = 180,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.generation_model = generation_model
        self.edit_model = edit_model
        self.timeout_s = int(timeout_s)

    def generate(
        self,
        prompt: str,
        output_path: str | Path,
        options: ImageRequestOptions,
    ) -> ImageCallResult:
        self._require_config(self.generation_model, "样图生成模型")
        body: dict[str, Any] = {
            "model": self.generation_model,
            "prompt": prompt,
            "image_size": options.size,
            "num_inference_steps": int(options.extra_body.get("num_inference_steps", 30)),
        }
        if self.generation_model == "Qwen/Qwen-Image":
            body["cfg"] = float(options.extra_body.get("cfg", 4.0))
        elif self.generation_model == "Kwai-Kolors/Kolors":
            body["guidance_scale"] = float(options.extra_body.get("guidance_scale", 7.5))
        self._add_optional_fields(body, options)
        response, headers = self._request_json("POST", "/images/generations", body)
        return self._save_response(response, headers, output_path, self.generation_model)

    def edit(
        self,
        prompt: str,
        source_image: str | Path,
        output_path: str | Path,
        options: ImageRequestOptions,
    ) -> ImageCallResult:
        self._require_config(self.edit_model, "线稿编辑模型")
        source = Path(source_image)
        if not source.is_file():
            raise ImageProviderError(f"待编辑样图不存在：{source}")
        body: dict[str, Any] = {
            "model": self.edit_model,
            "prompt": prompt,
            "image": _image_data_url(source),
            "num_inference_steps": int(options.extra_body.get("num_inference_steps", 30)),
        }
        self._add_optional_fields(body, options)
        # Qwen Image Edit does not accept image_size.
        response, headers = self._request_json("POST", "/images/generations", body)
        return self._save_response(response, headers, output_path, self.edit_model)

    def test_connection(self) -> tuple[bool, str]:
        try:
            self._require_config(self.generation_model, "样图生成模型")
            raw, headers = self._request("GET", "/models", None, {})
            payload = json.loads(raw.decode("utf-8"))
            available = {
                str(item.get("id"))
                for item in payload.get("data", [])
                if isinstance(item, dict) and item.get("id")
            }
            missing = [
                model
                for model in (self.generation_model, self.edit_model)
                if available and model not in available
            ]
            if missing:
                return False, f"连接成功，但模型列表中未找到：{', '.join(missing)}"
            trace_id = _header_value(headers, "x-siliconcloud-trace-id")
            suffix = f"，追踪编号 {trace_id}" if trace_id else ""
            return True, f"连接成功，样图与线稿模型配置有效{suffix}"
        except Exception as exc:
            return False, str(exc)

    def _require_config(self, model: str, model_label: str) -> None:
        if not self.base_url:
            raise ImageProviderError("请填写硅基流动 API 地址。")
        if not self.api_key:
            raise ImageProviderError("请填写硅基流动 API Key，或设置 SILICONFLOW_API_KEY。")
        if not model:
            raise ImageProviderError(f"请填写{model_label}。")

    @staticmethod
    def _add_optional_fields(body: dict[str, Any], options: ImageRequestOptions) -> None:
        for key in ("negative_prompt", "seed"):
            value = options.extra_body.get(key)
            if value not in (None, ""):
                body[key] = value

    def _request_json(
        self,
        method: str,
        path: str,
        body: dict[str, Any],
    ) -> tuple[dict[str, Any], Any]:
        raw, headers = self._request(
            method,
            path,
            json.dumps(body, ensure_ascii=False).encode("utf-8"),
            {"Content-Type": "application/json"},
        )
        try:
            return json.loads(raw.decode("utf-8")), headers
        except Exception as exc:
            raise ImageProviderError("硅基流动返回了无法解析的数据。") from exc

    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None,
        headers: dict[str, str],
    ) -> tuple[bytes, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "X-Enable-Watermark": "0",
                **headers,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return response.read(), response.headers
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ImageProviderError(
                f"硅基流动请求失败（HTTP {exc.code}）：{_safe_error_detail(detail)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ImageProviderError(f"无法连接硅基流动：{exc.reason}") from exc
        except TimeoutError as exc:
            raise ImageProviderError("硅基流动请求超时，请稍后重试。") from exc

    def _save_response(
        self,
        response: dict[str, Any],
        headers: Any,
        output_path: str | Path,
        model: str,
    ) -> ImageCallResult:
        images = response.get("images")
        if not isinstance(images, list) or not images or not isinstance(images[0], dict):
            raise ImageProviderError("硅基流动没有返回图像数据。")
        image_bytes = _image_bytes(images[0], timeout_s=self.timeout_s)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with Image.open(BytesIO(image_bytes)) as image:
                image.convert("RGB").save(output, format="PNG")
        except Exception as exc:
            raise ImageProviderError("硅基流动返回的图像文件无效。") from exc
        return ImageCallResult(
            output_path=output,
            provider_id=self.provider_id,
            model_id=model,
            request_id=_header_value(headers, "x-siliconcloud-trace-id"),
            usage={"timings": response.get("timings") or {}, "seed": response.get("seed")},
        )


class OpenAIImagesProvider:
    """Small dependency-free client for OpenAI-compatible Images endpoints."""

    negative_prompt_mode = "unsupported"

    def __init__(
        self,
        *,
        provider_id: str,
        api_key: str,
        base_url: str,
        model: str,
        timeout_s: int = 180,
        supports_edit: bool = True,
    ) -> None:
        self.provider_id = provider_id
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = int(timeout_s)
        self.supports_edit = supports_edit

    def generate(
        self,
        prompt: str,
        output_path: str | Path,
        options: ImageRequestOptions,
    ) -> ImageCallResult:
        self._require_config()
        body: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "n": 1,
            "size": options.size,
        }
        if self.provider_id != "siliconflow":
            body.update(
                {
                    "quality": options.quality,
                    "output_format": options.output_format,
                    "background": "opaque",
                }
            )
        elif options.extra_body:
            body["extra_body"] = dict(options.extra_body)
        body.update({key: value for key, value in options.extra_body.items() if key not in body})
        response, headers = self._request_json("POST", "/images/generations", body)
        return self._save_response(response, headers, output_path)

    def edit(
        self,
        prompt: str,
        source_image: str | Path,
        output_path: str | Path,
        options: ImageRequestOptions,
    ) -> ImageCallResult:
        if not self.supports_edit:
            raise UnsupportedImageCapability("当前服务商没有配置图像编辑接口，无法保证第二阶段沿用同一张样图。")
        self._require_config()
        source = Path(source_image)
        if not source.is_file():
            raise ImageProviderError(f"待编辑样图不存在：{source}")
        fields = {
            "model": self.model,
            "prompt": prompt,
            "n": "1",
            "size": options.size,
            "quality": options.quality,
            "output_format": options.output_format,
            "background": "opaque",
        }
        body, content_type = _encode_multipart(fields, "image", source)
        response, headers = self._request(
            "POST",
            "/images/edits",
            body,
            {"Content-Type": content_type},
        )
        try:
            payload = json.loads(response.decode("utf-8"))
        except Exception as exc:
            raise ImageProviderError("图像编辑接口返回了无法解析的数据。") from exc
        return self._save_response(payload, headers, output_path)

    def test_connection(self) -> tuple[bool, str]:
        try:
            self._require_config()
            _, headers = self._request("GET", "/models", None, {})
            request_id = _header_value(headers, "x-request-id")
            suffix = f"，请求编号 {request_id}" if request_id else ""
            return True, f"连接成功{suffix}"
        except Exception as exc:
            return False, str(exc)

    def _require_config(self) -> None:
        if not self.base_url:
            raise ImageProviderError("请填写模型服务地址。")
        if not self.api_key:
            raise ImageProviderError("请填写 API Key，或设置对应的环境变量。")

    def _request_json(
        self,
        method: str,
        path: str,
        body: dict[str, Any],
    ) -> tuple[dict[str, Any], Any]:
        raw, headers = self._request(
            method,
            path,
            json.dumps(body, ensure_ascii=False).encode("utf-8"),
            {"Content-Type": "application/json"},
        )
        try:
            return json.loads(raw.decode("utf-8")), headers
        except Exception as exc:
            raise ImageProviderError("模型接口返回了无法解析的数据。") from exc

    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None,
        headers: dict[str, str],
    ) -> tuple[bytes, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={"Authorization": f"Bearer {self.api_key}", **headers},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return response.read(), response.headers
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ImageProviderError(f"模型接口请求失败（HTTP {exc.code}）：{_safe_error_detail(detail)}") from exc
        except urllib.error.URLError as exc:
            raise ImageProviderError(f"无法连接模型服务：{exc.reason}") from exc
        except TimeoutError as exc:
            raise ImageProviderError("模型接口请求超时，请稍后重试。") from exc

    def _save_response(
        self,
        response: dict[str, Any],
        headers: Any,
        output_path: str | Path,
    ) -> ImageCallResult:
        data = response.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise ImageProviderError("模型接口没有返回图像数据。")
        item = data[0]
        image_bytes = _image_bytes(item, timeout_s=self.timeout_s)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(image_bytes)
        return ImageCallResult(
            output_path=output,
            provider_id=self.provider_id,
            model_id=self.model,
            request_id=_header_value(headers, "x-request-id"),
            usage=dict(response.get("usage") or {}),
            revised_prompt=str(item.get("revised_prompt") or ""),
        )


def _provider_api_key(provider_id: str) -> str:
    names = {
        "openai": ("OPENAI_API_KEY", "AI_IMAGE_API_KEY"),
        "siliconflow": ("SILICONFLOW_API_KEY", "AI_IMAGE_API_KEY"),
        "bananapro": ("BANANAPRO_API_KEY", "NANOBANANA_API_KEY", "AI_IMAGE_API_KEY"),
        "custom_openai": ("AI_IMAGE_API_KEY",),
    }
    for name in names.get(provider_id, ("AI_IMAGE_API_KEY",)):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _encode_multipart(fields: dict[str, str], file_field: str, source: Path) -> tuple[bytes, str]:
    boundary = "----Tanghua" + secrets.token_hex(12)
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{file_field}"; filename="{source.name}"\r\n'.encode("utf-8"),
            f"Content-Type: {mime}\r\n\r\n".encode(),
            source.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _image_bytes(item: dict[str, Any], *, timeout_s: int) -> bytes:
    encoded = item.get("b64_json") or item.get("base64")
    if encoded:
        try:
            return base64.b64decode(str(encoded), validate=True)
        except Exception as exc:
            raise ImageProviderError("模型返回的图像编码无效。") from exc
    url = str(item.get("url") or "")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ImageProviderError("模型接口没有返回可用的图像。")
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response:
            return response.read()
    except Exception as exc:
        raise ImageProviderError("下载模型生成的图像失败。") from exc


def _image_data_url(source: Path) -> str:
    mime = mimetypes.guess_type(source.name)[0] or "image/png"
    encoded = base64.b64encode(source.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _header_value(headers: Any, name: str) -> str:
    if headers is None:
        return ""
    try:
        return str(headers.get(name, "") or "")
    except Exception:
        return ""


def _safe_error_detail(detail: str, limit: int = 500) -> str:
    compact = " ".join((detail or "").split())
    return compact[:limit] or "服务端未提供错误详情"
