from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src.pipeline.image_generation.banana_pro import BananaProImagesProvider
from src.pipeline.image_generation.providers import (
    ImageRequestOptions,
    ProviderConfig,
    create_image_provider,
)


class _FakeResponse:
    def __init__(self, payload: bytes, headers: dict[str, str] | None = None) -> None:
        self.payload = payload
        self.headers = headers or {}

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def _json_response(payload: dict) -> _FakeResponse:
    return _FakeResponse(json.dumps(payload).encode("utf-8"))


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (24, 24), "white").save(buffer, format="PNG")
    return buffer.getvalue()


class BananaProProviderTests(unittest.TestCase):
    def _provider(self) -> BananaProImagesProvider:
        provider = create_image_provider(
            ProviderConfig(
                provider_id="bananapro",
                model="nano-banana-pro",
                edit_model="seedream-5-pro",
                api_key="sk-test",
                base_url="https://www.bananapro.site",
                timeout_s=30,
            )
        )
        self.assertIsInstance(provider, BananaProImagesProvider)
        provider.poll_interval_s = 0
        return provider

    def test_generate_submits_polls_and_saves_png(self) -> None:
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request)
            url = request if isinstance(request, str) else request.full_url
            if url.endswith("/api/v1/images/generate"):
                return _json_response(
                    {
                        "success": True,
                        "data": {"task_id": "task-1", "credits_used": 8},
                    }
                )
            if url.endswith("/api/v1/images/task-1"):
                return _json_response(
                    {
                        "success": True,
                        "request_id": "req-1",
                        "data": {
                            "status": "completed",
                            "image_url": "https://cdn.example/result.webp",
                            "credits_used": 8,
                        },
                    }
                )
            return _FakeResponse(_png_bytes())

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            output = Path(temporary) / "sample.png"
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                result = self._provider().generate(
                    "传统糖画马",
                    output,
                    ImageRequestOptions(
                        extra_body={
                            "resolution": "2K",
                            "aspect_ratio": "1:1",
                            "negative_prompt": "阴影，色块",
                        }
                    ),
                )

            body = json.loads(calls[0].data.decode("utf-8"))
            self.assertEqual(body["model"], "nano-banana-pro")
            self.assertEqual(body["type"], "text-to-image")
            self.assertEqual(body["resolution"], "2K")
            self.assertIn("阴影，色块", body["prompt"])
            self.assertTrue(calls[0].get_header("Idempotency-key").startswith("tanghua-"))
            self.assertEqual(result.request_id, "req-1")
            self.assertEqual(result.usage["credits_used"], 8)
            with Image.open(output) as saved:
                self.assertEqual(saved.format, "PNG")

    def test_edit_uses_seedream_and_centerline_reference(self) -> None:
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request)
            url = request if isinstance(request, str) else request.full_url
            if url.endswith("/api/v1/images/generate"):
                return _json_response({"success": True, "data": {"task_id": "task-edit"}})
            if url.endswith("/api/v1/images/task-edit"):
                return _json_response(
                    {
                        "success": True,
                        "data": {
                            "status": "completed",
                            "output": {"images": [{"url": "https://cdn.example/line.png"}]},
                        },
                    }
                )
            return _FakeResponse(_png_bytes())

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            source = Path(temporary) / "sample.png"
            output = Path(temporary) / "line.png"
            Image.new("RGB", (24, 24), "white").save(source)
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                result = self._provider().edit(
                    "提取单中心线",
                    source,
                    output,
                    ImageRequestOptions(
                        extra_body={
                            "resolution": "4K",
                            "aspect_ratio": "4:3",
                            "generation_mode": "standard",
                            "reference_image_url": "https://cdn.example/source.png",
                        }
                    ),
                )

            body = json.loads(calls[0].data.decode("utf-8"))
            self.assertEqual(body["model"], "seedream-5-pro")
            self.assertEqual(body["type"], "image-to-image")
            self.assertEqual(body["resolution"], "2K")
            self.assertEqual(body["generation_mode"], "standard")
            self.assertEqual(body["image_urls"], ["https://cdn.example/source.png"])
            self.assertEqual(result.model_id, "seedream-5-pro")
            self.assertTrue(output.is_file())

    def test_connection_reads_balance_and_dynamic_image_models(self) -> None:
        def fake_urlopen(request, timeout):
            if request.full_url.endswith("/api/v1/balance"):
                return _json_response(
                    {"success": True, "data": {"credits": 50, "api_credits": 25}}
                )
            return _json_response(
                {
                    "success": True,
                    "data": {
                        "models": [
                            {"id": "nano-banana-pro", "type": "image", "types": ["text-to-image"]},
                            {"id": "seedream-5-pro", "type": "image", "types": ["image-to-image"]},
                            {"id": "video-model", "type": "video", "types": ["text-to-video"]},
                        ]
                    },
                }
            )

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            ok, message = self._provider().test_connection()
        self.assertTrue(ok)
        self.assertIn("2 个图像模型", message)
        self.assertIn("25 credits", message)

    def test_recent_tasks_and_completed_result_can_be_recovered(self) -> None:
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request)
            if request.full_url.endswith("/api/v1/tasks?limit=20"):
                return _json_response(
                    {
                        "success": True,
                        "data": {
                            "tasks": [
                                {
                                    "task_id": "lost-task",
                                    "type": "image",
                                    "status": "completed",
                                    "model": "seedream-5-pro",
                                },
                                {"task_id": "video-task", "type": "video"},
                            ]
                        },
                    }
                )
            if request.full_url.endswith("/api/v1/images/lost-task"):
                return _json_response(
                    {
                        "success": True,
                        "data": {
                            "status": "completed",
                            "model": "seedream-5-pro",
                            "image_url": "https://cdn.example/lost.webp",
                            "credits_used": 14,
                        },
                    }
                )
            return _FakeResponse(_png_bytes())

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            output = Path(temporary) / "recovered.png"
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                provider = self._provider()
                tasks = provider.list_recent_image_tasks()
                result = provider.recover_completed_task("lost-task", output)

            self.assertEqual([task["task_id"] for task in tasks], ["lost-task"])
            self.assertTrue(output.is_file())
            self.assertTrue(result.usage["recovered"])
            self.assertEqual(result.usage["credits_used"], 14)
            download_request = calls[-1]
            self.assertIn("Mozilla/5.0", download_request.get_header("User-agent"))
            self.assertEqual(download_request.get_header("Referer"), "https://www.bananapro.site/")


if __name__ == "__main__":
    unittest.main()
