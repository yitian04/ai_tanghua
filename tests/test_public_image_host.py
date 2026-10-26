from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src.pipeline.image_generation.public_image_host import ImgBBImageHost


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload).encode("utf-8")
        self.headers = {}

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


class PublicImageHostTests(unittest.TestCase):
    def test_imgbb_upload_returns_direct_public_url(self) -> None:
        captured = []

        def fake_urlopen(request, timeout):
            captured.append(request)
            return _FakeResponse(
                {
                    "success": True,
                    "data": {"url": "https://i.ibb.co/example/sample.png"},
                }
            )

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            source = Path(temporary) / "sample.png"
            Image.new("RGB", (16, 16), "white").save(source)
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                url = ImgBBImageHost("imgbb-test-key", expiration_s=3600).upload(source)

        self.assertEqual(url, "https://i.ibb.co/example/sample.png")
        self.assertIn("expiration=3600", captured[0].full_url)
        self.assertIn(b"image=", captured[0].data)
        self.assertNotIn(b"imgbb-test-key", captured[0].data)


if __name__ == "__main__":
    unittest.main()
