from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src.pipeline.image_generation.providers import (
    ImageRequestOptions,
    ProviderConfig,
    SiliconFlowImagesProvider,
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


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, format="PNG")
    return buffer.getvalue()


class SiliconFlowProviderTests(unittest.TestCase):
    def _provider(self) -> SiliconFlowImagesProvider:
        provider = create_image_provider(
            ProviderConfig(
                provider_id="siliconflow",
                model="Qwen/Qwen-Image",
                edit_model="Qwen/Qwen-Image-Edit-2509",
                api_key="test-key",
                base_url="https://api.siliconflow.cn/v1",
            )
        )
        self.assertIsInstance(provider, SiliconFlowImagesProvider)
        return provider

    def test_generation_uses_siliconflow_schema_and_saves_png(self) -> None:
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request)
            url = request if isinstance(request, str) else request.full_url
            if url.endswith("/images/generations"):
                payload = {"images": [{"url": "https://images.example/result.webp"}], "seed": 42}
                return _FakeResponse(
                    json.dumps(payload).encode("utf-8"),
                    {"x-siliconcloud-trace-id": "trace-generation"},
                )
            return _FakeResponse(_png_bytes())

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            output = Path(temporary) / "sample.png"
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                result = self._provider().generate(
                    "一匹马",
                    output,
                    ImageRequestOptions(
                        size="1328x1328",
                        extra_body={"negative_prompt": "阴影", "num_inference_steps": 25},
                    ),
                )

            request_body = json.loads(calls[0].data.decode("utf-8"))
            self.assertEqual(request_body["model"], "Qwen/Qwen-Image")
            self.assertEqual(request_body["image_size"], "1328x1328")
            self.assertNotIn("size", request_body)
            self.assertEqual(request_body["negative_prompt"], "阴影")
            self.assertEqual(calls[0].get_header("X-enable-watermark"), "0")
            self.assertEqual(result.model_id, "Qwen/Qwen-Image")
            self.assertEqual(result.request_id, "trace-generation")
            with Image.open(output) as saved:
                self.assertEqual(saved.format, "PNG")

    def test_generation_parameters_follow_selected_model(self) -> None:
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request)
            url = request if isinstance(request, str) else request.full_url
            if url.endswith("/images/generations"):
                payload = {"images": [{"url": "https://images.example/result.png"}]}
                return _FakeResponse(json.dumps(payload).encode("utf-8"))
            return _FakeResponse(_png_bytes())

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            for model in ("Tongyi-MAI/Z-Image", "Kwai-Kolors/Kolors"):
                provider = create_image_provider(
                    ProviderConfig(
                        provider_id="siliconflow",
                        model=model,
                        edit_model="Qwen/Qwen-Image-Edit-2509",
                        api_key="test-key",
                        base_url="https://api.siliconflow.cn/v1",
                    )
                )
                with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                    provider.generate(
                        "一匹马",
                        Path(temporary) / f"{model.rsplit('/', 1)[-1]}.png",
                        ImageRequestOptions(size="1024x1024", extra_body={"cfg": 4.0}),
                    )

        z_image_body = json.loads(calls[0].data.decode("utf-8"))
        kolors_body = json.loads(calls[2].data.decode("utf-8"))
        self.assertNotIn("cfg", z_image_body)
        self.assertNotIn("guidance_scale", z_image_body)
        self.assertNotIn("cfg", kolors_body)
        self.assertEqual(kolors_body["guidance_scale"], 7.5)

    def test_edit_uses_same_endpoint_with_data_url_and_no_size(self) -> None:
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request)
            url = request if isinstance(request, str) else request.full_url
            if url.endswith("/images/generations"):
                return _FakeResponse(
                    json.dumps({"images": [{"url": "https://images.example/line.png"}]}).encode("utf-8")
                )
            return _FakeResponse(_png_bytes())

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            source = Path(temporary) / "source.png"
            output = Path(temporary) / "line.png"
            Image.new("RGB", (32, 32), "white").save(source)
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                result = self._provider().edit(
                    "转换为黑白线稿",
                    source,
                    output,
                    ImageRequestOptions(size="1328x1328"),
                )

            request_body = json.loads(calls[0].data.decode("utf-8"))
            self.assertEqual(request_body["model"], "Qwen/Qwen-Image-Edit-2509")
            self.assertTrue(request_body["image"].startswith("data:image/png;base64,"))
            self.assertNotIn("image_size", request_body)
            self.assertEqual(calls[0].full_url, "https://api.siliconflow.cn/v1/images/generations")
            self.assertEqual(result.model_id, "Qwen/Qwen-Image-Edit-2509")
            self.assertTrue(output.is_file())

    def test_connection_checks_both_configured_models_without_generating(self) -> None:
        models = {
            "data": [
                {"id": "Qwen/Qwen-Image"},
                {"id": "Qwen/Qwen-Image-Edit-2509"},
            ]
        }
        response = _FakeResponse(
            json.dumps(models).encode("utf-8"),
            {"x-siliconcloud-trace-id": "trace-models"},
        )
        with patch("urllib.request.urlopen", return_value=response):
            ok, message = self._provider().test_connection()
        self.assertTrue(ok)
        self.assertIn("连接成功", message)
        self.assertIn("trace-models", message)


if __name__ == "__main__":
    unittest.main()
