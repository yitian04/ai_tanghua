from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.pipeline.image_generation.local_credentials import (
    BananaProCredentialStore,
    BananaProSavedConfig,
    PublicImageHostCredentialStore,
    PublicImageHostSavedConfig,
    SiliconFlowCredentialStore,
    SiliconFlowSavedConfig,
)


class LocalCredentialStoreTests(unittest.TestCase):
    def test_public_image_host_config_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            first = PublicImageHostCredentialStore(temporary)
            first.save(
                PublicImageHostSavedConfig(
                    imgbb_api_key="imgbb-local-test",
                    expiration_s=3600,
                )
            )
            restored = PublicImageHostCredentialStore(temporary).load()
            self.assertEqual(restored.imgbb_api_key, "imgbb-local-test")
            self.assertEqual(restored.expiration_s, 3600)
            first.clear()
            self.assertEqual(
                PublicImageHostCredentialStore(temporary).load().imgbb_api_key,
                "",
            )

    def test_bananapro_config_survives_new_store_instance(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            first = BananaProCredentialStore(temporary)
            first.save(
                BananaProSavedConfig(
                    api_key="sk-banana-test",
                    generation_model="nano-banana-pro",
                    edit_model="seedream-5-pro",
                    resolution="2K",
                )
            )

            restored = BananaProCredentialStore(temporary).load()
            self.assertEqual(restored.api_key, "sk-banana-test")
            self.assertEqual(restored.edit_model, "seedream-5-pro")
            self.assertEqual(restored.resolution, "2K")

            first.clear()
            self.assertEqual(BananaProCredentialStore(temporary).load().api_key, "")

    def test_siliconflow_config_survives_new_store_instance(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            first = SiliconFlowCredentialStore(temporary)
            first.save(
                SiliconFlowSavedConfig(
                    api_key="sk-local-test",
                    base_url="https://api.siliconflow.cn/v1",
                    generation_model="Qwen/Qwen-Image",
                    edit_model="Qwen/Qwen-Image-Edit-2509",
                )
            )

            restored = SiliconFlowCredentialStore(temporary).load()
            self.assertEqual(restored.api_key, "sk-local-test")
            self.assertEqual(restored.edit_model, "Qwen/Qwen-Image-Edit-2509")

            first.clear()
            self.assertEqual(SiliconFlowCredentialStore(temporary).load().api_key, "")


if __name__ == "__main__":
    unittest.main()
