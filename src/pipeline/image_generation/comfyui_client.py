from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib import error, parse, request


class ComfyUIError(RuntimeError):
    """Raised when the local ComfyUI server rejects or fails a workflow."""


@dataclass(frozen=True)
class ComfyUIImageRef:
    filename: str
    subfolder: str = ""
    folder_type: str = "output"
    node_id: str = ""

    @classmethod
    def from_history_image(cls, node_id: str, data: Mapping[str, Any]) -> "ComfyUIImageRef":
        return cls(
            filename=str(data.get("filename", "")),
            subfolder=str(data.get("subfolder", "")),
            folder_type=str(data.get("type", "output")),
            node_id=str(node_id),
        )


ProgressCallback = Callable[[str, dict[str, Any]], None]


def load_workflow_json(path: str | Path) -> dict[str, Any]:
    """Load a ComfyUI workflow exported with File -> Export Workflow (API)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


class ComfyUIClient:
    """Small HTTP client for ComfyUI Server API.

    The client expects a workflow in ComfyUI API format. It submits the workflow to
    POST /prompt, waits for GET /history/{prompt_id}, and downloads images through
    GET /view. This avoids a websocket dependency and is enough for the first
    design-input integration step.
    """

    def __init__(self, server_url: str = "http://127.0.0.1:8188", timeout_s: float = 30.0):
        self.server_url = server_url.rstrip("/")
        self.timeout_s = float(timeout_s)

    def queue_prompt(
        self,
        workflow: Mapping[str, Any],
        client_id: str | None = None,
        prompt_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "prompt": dict(workflow),
            "client_id": client_id or str(uuid.uuid4()),
        }
        if prompt_id:
            payload["prompt_id"] = prompt_id

        response = self._request_json("POST", "/prompt", payload)
        if "error" in response:
            raise ComfyUIError(_format_comfy_error(response))
        if "prompt_id" not in response:
            raise ComfyUIError(f"ComfyUI /prompt did not return prompt_id: {response}")
        return response

    def get_history(self, prompt_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/history/{parse.quote(prompt_id)}")

    def wait_for_history(
        self,
        prompt_id: str,
        timeout_s: float = 300.0,
        poll_interval_s: float = 1.0,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + float(timeout_s)
        while time.monotonic() < deadline:
            history = self.get_history(prompt_id)
            if prompt_id in history:
                item = history[prompt_id]
                self._raise_if_failed(item)
                return item
            if progress_callback:
                progress_callback("waiting", {"prompt_id": prompt_id})
            time.sleep(max(0.1, float(poll_interval_s)))
        raise ComfyUIError(f"Timed out waiting for ComfyUI prompt {prompt_id}")

    def list_output_images(self, history_item: Mapping[str, Any]) -> list[ComfyUIImageRef]:
        images: list[ComfyUIImageRef] = []
        outputs = history_item.get("outputs", {})
        if not isinstance(outputs, Mapping):
            return images
        for node_id, node_output in outputs.items():
            if not isinstance(node_output, Mapping):
                continue
            for image in node_output.get("images", []) or []:
                if isinstance(image, Mapping) and image.get("filename"):
                    images.append(ComfyUIImageRef.from_history_image(str(node_id), image))
        return images

    def download_image(self, image_ref: ComfyUIImageRef) -> bytes:
        if not image_ref.filename:
            raise ComfyUIError("Cannot download ComfyUI image: filename is empty")
        query = parse.urlencode(
            {
                "filename": image_ref.filename,
                "subfolder": image_ref.subfolder,
                "type": image_ref.folder_type,
            }
        )
        return self._request_bytes("GET", f"/view?{query}")

    def save_image(self, image_ref: ComfyUIImageRef, output_path: str | Path) -> Path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(self.download_image(image_ref))
        return output

    def queue_and_download_first_image(
        self,
        workflow: Mapping[str, Any],
        output_path: str | Path,
        timeout_s: float = 300.0,
        poll_interval_s: float = 1.0,
        client_id: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> Path:
        queued = self.queue_prompt(workflow, client_id=client_id)
        prompt_id = str(queued["prompt_id"])
        if progress_callback:
            progress_callback("queued", queued)
        history_item = self.wait_for_history(
            prompt_id,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            progress_callback=progress_callback,
        )
        images = self.list_output_images(history_item)
        if not images:
            raise ComfyUIError(f"ComfyUI prompt {prompt_id} completed but produced no images")
        return self.save_image(images[0], output_path)

    def _request_json(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(self._url(path), data=data, headers=headers, method=method.upper())
        try:
            with request.urlopen(req, timeout=self.timeout_s) as resp:
                body = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ComfyUIError(f"ComfyUI HTTP {exc.code} for {path}: {detail}") from exc
        except error.URLError as exc:
            raise ComfyUIError(f"Cannot connect to ComfyUI at {self.server_url}: {exc.reason}") from exc
        try:
            decoded = json.loads(body or "{}")
        except json.JSONDecodeError as exc:
            raise ComfyUIError(f"ComfyUI returned non-JSON response for {path}: {body[:200]}") from exc
        if not isinstance(decoded, dict):
            raise ComfyUIError(f"ComfyUI returned unexpected JSON for {path}: {decoded!r}")
        return decoded

    def _request_bytes(self, method: str, path: str) -> bytes:
        req = request.Request(self._url(path), method=method.upper())
        try:
            with request.urlopen(req, timeout=self.timeout_s) as resp:
                return resp.read()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ComfyUIError(f"ComfyUI HTTP {exc.code} for {path}: {detail}") from exc
        except error.URLError as exc:
            raise ComfyUIError(f"Cannot connect to ComfyUI at {self.server_url}: {exc.reason}") from exc

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.server_url}{path if path.startswith('/') else '/' + path}"

    @staticmethod
    def _raise_if_failed(history_item: Mapping[str, Any]) -> None:
        status = history_item.get("status")
        if not isinstance(status, Mapping):
            return
        status_str = str(status.get("status_str", "")).lower()
        completed = bool(status.get("completed", False))
        if status_str in {"error", "failed"} or (status_str and not completed and "error" in status_str):
            messages = status.get("messages", [])
            raise ComfyUIError(f"ComfyUI prompt failed: {messages or status}")


def _format_comfy_error(response: Mapping[str, Any]) -> str:
    parts = [f"ComfyUI rejected workflow: {response.get('error')}"]
    node_errors = response.get("node_errors")
    if node_errors:
        parts.append(f"node_errors={node_errors}")
    return "; ".join(parts)
