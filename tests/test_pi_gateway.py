from __future__ import annotations

import base64
import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.pipeline.image_generation.pi_gateway import PiGatewayImageProvider


class PiGatewayImageProviderTests(unittest.TestCase):
    def test_non_png_response_is_normalized_to_png(self) -> None:
        source = io.BytesIO()
        Image.new("RGB", (8, 6), "white").save(source, format="WEBP")
        response = {
            "images": [
                {
                    "data": base64.b64encode(source.getvalue()).decode("ascii"),
                    "mimeType": "image/webp",
                }
            ],
            "providerId": "openrouter",
            "modelId": "test/image-model",
        }
        provider = PiGatewayImageProvider(
            client=None,  # type: ignore[arg-type]
            provider_id="openrouter",
            model_id="test/image-model",
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "sample.png"
            provider._save_response(response, output)
            with Image.open(output) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (8, 6))


if __name__ == "__main__":
    unittest.main()
