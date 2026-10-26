from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.pipeline.image_generation.project_defaults import ProjectDefaultsStore
from src.pipeline.image_generation.sugar_painting import SugarPaintingService


class ProjectDefaultsTests(unittest.TestCase):
    def test_models_and_prompts_persist_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            store = ProjectDefaultsStore(temporary)
            store.save_stage(
                "sample",
                source="bananapro",
                provider_id="bananapro",
                model_id="nano-banana-2",
            )
            store.save_prompt(
                "sample",
                "zh",
                positive="使用简洁、连续的糖线。",
                negative="",
            )

            restored = ProjectDefaultsStore(temporary)
            self.assertEqual(restored.stage("sample")["model_id"], "nano-banana-2")
            self.assertEqual(
                restored.prompt(
                    "sample",
                    "zh",
                    fallback_positive="fallback",
                    fallback_negative="fallback",
                ),
                ("使用简洁、连续的糖线。", ""),
            )
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            serialized = json.dumps(payload).lower()
            self.assertNotIn("api_key", serialized)
            self.assertNotIn("token", serialized)

    def test_new_tasks_use_saved_prompt_defaults(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            store = ProjectDefaultsStore(temporary)
            store.save_prompt(
                "line_art",
                "zh",
                positive="只提取糖线中心线。",
                negative="双线，色块",
            )

            task = SugarPaintingService(temporary).create_task("马")
            self.assertEqual(task.line_art_prompt, "只提取糖线中心线。")
            self.assertEqual(task.line_art_negative_prompt, "双线，色块")

    def test_default_prompt_rejects_subject_placeholder(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            with self.assertRaisesRegex(ValueError, "OBJECT"):
                ProjectDefaultsStore(temporary).save_prompt(
                    "sample",
                    "zh",
                    positive="生成 {{OBJECT}} 的糖画",
                    negative="",
                )


if __name__ == "__main__":
    unittest.main()
