from __future__ import annotations

import base64
import json
import mimetypes
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from src.pipeline.image_generation.providers import (
    ImageCallResult,
    ImageProviderError,
    ImageRequestOptions,
)


class BananaProImagesProvider:
    """Native adapter for BananaPro's asynchronous multi-model image API."""

    provider_id = "bananapro"
    negative_prompt_mode = "prompt_suffix"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        generation_model: str,
        edit_model: str,
        timeout_s: int = 300,
        poll_interval_s: float = 5.0,
    ) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.generation_model = generation_model.strip()
        self.edit_model = edit_model.strip()
        self.timeout_s = int(timeout_s)
        self.poll_interval_s = float(poll_interval_s)

    @property
    def requires_public_reference_image(self) -> bool:
        return self.edit_model not in {
            "nano-banana-pro",
            "nano-banana-2",
            "nano-banana",
        }

    def generate(
        self,
        prompt: str,
        output_path: str | Path,
        options: ImageRequestOptions,
    ) -> ImageCallResult:
        return self._submit_and_wait(
            model=self.generation_model,
            request_type="text-to-image",
            prompt=prompt,
            output_path=output_path,
            options=options,
        )

    def edit(
        self,
        prompt: str,
        source_image: str | Path,
        output_path: str | Path,
        options: ImageRequestOptions,
    ) -> ImageCallResult:
        source = Path(source_image)
        if not source.is_file():
            raise ImageProviderError(f"待编辑样图不存在：{source}")
        reference_url = str(options.extra_body.get("reference_image_url") or "").strip()
        if self.requires_public_reference_image and not reference_url:
            raise ImageProviderError(
                "当前 BananaPro 编辑模型需要可访问的参考图 URL。请先配置图片托管，"
                "或将第二阶段切换为支持 base64 参考图的模型。"
            )
        return self._submit_and_wait(
            model=self.edit_model,
            request_type="image-to-image",
            prompt=prompt,
            output_path=output_path,
            options=options,
            image_urls=[reference_url or _image_data_url(source)],
        )

    def list_models(self) -> list[dict[str, Any]]:
        self._require_config(self.generation_model, "第一阶段模型")
        payload, _ = self._request_json("GET", "/api/v1/models")
        data = payload.get("data") or {}
        models = data.get("models") if isinstance(data, dict) else []
        if not isinstance(models, list):
            return []
        return [
            item
            for item in models
            if isinstance(item, dict) and item.get("id") and item.get("type") == "image"
        ]

    def list_recent_image_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        self._require_config(self.edit_model, "图像模型")
        safe_limit = max(1, min(int(limit), 50))
        payload, _ = self._request_json("GET", f"/api/v1/tasks?limit={safe_limit}")
        data = payload.get("data") or {}
        tasks = data.get("tasks") if isinstance(data, dict) else []
        if not isinstance(tasks, list):
            return []
        return [
            item
            for item in tasks
            if isinstance(item, dict) and item.get("type") == "image"
        ]

    def recover_completed_task(
        self,
        task_id: str,
        output_path: str | Path,
    ) -> ImageCallResult:
        remote_task_id = task_id.strip()
        if not remote_task_id:
            raise ImageProviderError("远程任务编号不能为空。")
        payload, _ = self._request_json(
            "GET", f"/api/v1/images/{urllib.parse.quote(remote_task_id, safe='')}"
        )
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise ImageProviderError("BananaPro 返回了无效的任务记录。")
        status = str(data.get("status") or "").lower()
        if status != "completed":
            raise ImageProviderError(f"远程任务尚未完成，当前状态：{status or 'unknown'}")
        image_url = _result_image_url(data)
        if not image_url:
            raise ImageProviderError("远程任务没有可恢复的图片地址。")
        output = Path(output_path)
        self._save_image(self._download_image(image_url), output)
        return ImageCallResult(
            output_path=output,
            provider_id=self.provider_id,
            model_id=str(data.get("model") or self.edit_model),
            request_id=str(payload.get("request_id") or remote_task_id),
            usage={
                "task_id": remote_task_id,
                "result_url": image_url,
                "credits_used": data.get("credits_used"),
                "recovered": True,
            },
        )

    def test_connection(self) -> tuple[bool, str]:
        try:
            self._require_config(self.generation_model, "第一阶段模型")
            balance, _ = self._request_json("GET", "/api/v1/balance")
            models = self.list_models()
            available = {str(item.get("id")) for item in models}
            missing = [
                model
                for model in (self.generation_model, self.edit_model)
                if available and model not in available
            ]
            if missing:
                return False, f"连接成功，但模型列表中未找到：{', '.join(missing)}"
            data = balance.get("data") or {}
            credits = data.get("api_credits", data.get("credits")) if isinstance(data, dict) else None
            suffix = f"，API 余额 {credits} credits" if credits is not None else ""
            return True, f"连接成功，已读取 {len(models)} 个图像模型{suffix}"
        except Exception as exc:
            return False, str(exc)

    def _submit_and_wait(
        self,
        *,
        model: str,
        request_type: str,
        prompt: str,
        output_path: str | Path,
        options: ImageRequestOptions,
        image_urls: list[str] | None = None,
    ) -> ImageCallResult:
        self._require_config(model, "图像模型")
        negative_prompt = str(options.extra_body.get("negative_prompt") or "").strip()
        effective_prompt = prompt
        if negative_prompt:
            effective_prompt = f"{prompt}\n\n必须避免以下内容：{negative_prompt}"
        body: dict[str, Any] = {
            "model": model,
            "type": request_type,
            "prompt": effective_prompt,
            "num_images": 1,
        }
        if image_urls:
            body["image_urls"] = image_urls
        self._add_model_options(body, model, options)
        submitted, _ = self._request_json(
            "POST",
            "/api/v1/images/generate",
            body,
            extra_headers={"Idempotency-Key": f"tanghua-{secrets.token_hex(12)}"},
        )
        submit_data = submitted.get("data") or {}
        task_id = str(submit_data.get("task_id") or "") if isinstance(submit_data, dict) else ""
        if not task_id:
            raise ImageProviderError("BananaPro 未返回任务编号。")
        recovery_path = Path(output_path).with_suffix(".remote.json")
        _write_recovery_record(
            recovery_path,
            {
                "task_id": task_id,
                "model": model,
                "status": "submitted",
                "request_type": request_type,
            },
        )

        deadline = time.monotonic() + self.timeout_s
        completed: dict[str, Any] | None = None
        request_id = str(submitted.get("request_id") or "")
        while time.monotonic() < deadline:
            polled, _ = self._request_json(
                "GET", f"/api/v1/images/{urllib.parse.quote(task_id, safe='')}"
            )
            request_id = str(polled.get("request_id") or request_id)
            data = polled.get("data") or {}
            if not isinstance(data, dict):
                raise ImageProviderError("BananaPro 返回了无效的任务状态。")
            status = str(data.get("status") or "").lower()
            if status == "completed":
                completed = data
                break
            if status == "failed":
                message = str(data.get("error_message") or "生成任务失败")
                refunded = data.get("credits_refunded")
                suffix = f"（已退回 {refunded} credits）" if refunded else ""
                raise ImageProviderError(f"BananaPro 生成失败：{message}{suffix}")
            time.sleep(self.poll_interval_s)
        if completed is None:
            raise ImageProviderError("BananaPro 生成超时；任务仍可能在平台后台继续执行。")

        image_url = _result_image_url(completed)
        if not image_url:
            raise ImageProviderError("BananaPro 任务已完成，但没有返回图像地址。")
        image_bytes = self._download_image(image_url)
        output = Path(output_path)
        self._save_image(image_bytes, output)
        _write_recovery_record(
            recovery_path,
            {
                "task_id": task_id,
                "model": model,
                "status": "completed",
                "result_url": image_url,
            },
        )
        return ImageCallResult(
            output_path=output,
            provider_id=self.provider_id,
            model_id=model,
            request_id=request_id or task_id,
            usage={
                "task_id": task_id,
                "result_url": image_url,
                "credits_used": completed.get("credits_used", submit_data.get("credits_used")),
                "remaining_credits": submit_data.get("remaining_credits"),
            },
        )

    @staticmethod
    def _add_model_options(
        body: dict[str, Any], model: str, options: ImageRequestOptions
    ) -> None:
        resolution = str(options.extra_body.get("resolution") or "1K")
        aspect_ratio = str(options.extra_body.get("aspect_ratio") or "1:1")
        if model in {"nano-banana-pro", "nano-banana-2", "seedream-5-pro"}:
            body["resolution"] = "2K" if model == "seedream-5-pro" and resolution == "4K" else resolution
        if model.startswith("nano-banana") or model == "seedream-5-pro":
            body["aspect_ratio"] = aspect_ratio
        if model == "seedream-5-pro":
            body["generation_mode"] = str(
                options.extra_body.get("generation_mode") or "standard"
            )
        if model == "nano-banana-2":
            body["output_format"] = options.output_format

    def _require_config(self, model: str, model_label: str) -> None:
        if not self.base_url:
            raise ImageProviderError("请填写 BananaPro API 地址。")
        if not self.api_key:
            raise ImageProviderError(
                "请填写 BananaPro API Key，或设置 BANANAPRO_API_KEY。"
            )
        if not model:
            raise ImageProviderError(f"请选择{model_label}。")

    def _request_json(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], Any]:
        encoded = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=encoded,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                **(extra_headers or {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                raw, headers = response.read(), response.headers
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ImageProviderError(
                f"BananaPro 请求失败（HTTP {exc.code}）：{_safe_detail(detail)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ImageProviderError(f"无法连接 BananaPro：{exc.reason}") from exc
        except TimeoutError as exc:
            raise ImageProviderError("BananaPro 请求超时，请稍后重试。") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ImageProviderError("BananaPro 返回了无法解析的数据。") from exc
        if not isinstance(payload, dict):
            raise ImageProviderError("BananaPro 返回的数据格式无效。")
        if payload.get("success") is False:
            raise ImageProviderError(
                f"BananaPro 请求失败：{payload.get('message') or payload.get('error') or '未知错误'}"
            )
        return payload, headers

    def _download_image(self, url: str) -> bytes:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ImageProviderError("BananaPro 返回了不安全的图像地址。")
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": f"{self.base_url}/",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return response.read()
        except Exception as exc:
            raise ImageProviderError("下载 BananaPro 生成图像失败。") from exc

    @staticmethod
    def _save_image(image_bytes: bytes, output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with Image.open(BytesIO(image_bytes)) as image:
                image.convert("RGB").save(output, format="PNG")
        except Exception as exc:
            raise ImageProviderError("BananaPro 返回的图像文件无效。") from exc


def _image_data_url(source: Path) -> str:
    mime = mimetypes.guess_type(source.name)[0] or "image/png"
    encoded = base64.b64encode(source.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _result_image_url(data: dict[str, Any]) -> str:
    for key in ("image_url", "primary_url"):
        value = str(data.get(key) or "")
        if value:
            return value
    output = data.get("output") or {}
    images = output.get("images") if isinstance(output, dict) else []
    if isinstance(images, list) and images:
        item = images[0]
        if isinstance(item, dict):
            return str(item.get("url") or "")
        return str(item or "")
    result_urls = data.get("result_urls") or []
    return str(result_urls[0]) if isinstance(result_urls, list) and result_urls else ""


def _safe_detail(detail: str, limit: int = 800) -> str:
    compact = " ".join(detail.split())
    return compact[:limit] + ("…" if len(compact) > limit else "")


def _write_recovery_record(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
