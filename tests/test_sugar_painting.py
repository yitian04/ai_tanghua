from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from src.pipeline.image_generation.providers import ImageCallResult, ImageRequestOptions
from src.pipeline.image_generation.quality import evaluate_traceable_line_image
from src.pipeline.image_generation.sugar_painting import (
    SugarPaintingService,
    compose_stage_prompt,
    negative_prompt_for,
    subject_instruction_for,
)


class FakeImageProvider:
    provider_id = "fake"

    def generate(self, prompt: str, output_path: str | Path, options: ImageRequestOptions) -> ImageCallResult:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (256, 256), "white")
        draw = ImageDraw.Draw(image)
        draw.line([(35, 180), (80, 70), (145, 45), (210, 150), (160, 205), (35, 180)], fill="#bd741c", width=8)
        image.save(output)
        return ImageCallResult(output, self.provider_id, "fake-image")

    def edit(
        self,
        prompt: str,
        source_image: str | Path,
        output_path: str | Path,
        options: ImageRequestOptions,
    ) -> ImageCallResult:
        if not Path(source_image).is_file():
            raise AssertionError("edit must receive the confirmed sample image")
        output = Path(output_path)
        image = Image.new("RGB", (256, 256), "white")
        draw = ImageDraw.Draw(image)
        draw.line([(35, 180), (80, 70), (145, 45), (210, 150), (160, 205), (35, 180)], fill="black", width=4)
        draw.line([(80, 70), (155, 155), (210, 150)], fill="black", width=4)
        image.save(output)
        return ImageCallResult(output, self.provider_id, "fake-image")

    def test_connection(self) -> tuple[bool, str]:
        return True, "ok"


class CapturingSiliconFlowProvider(FakeImageProvider):
    provider_id = "siliconflow"

    def __init__(self) -> None:
        self.generated_options: ImageRequestOptions | None = None
        self.edited_options: ImageRequestOptions | None = None

    def generate(self, prompt: str, output_path: str | Path, options: ImageRequestOptions) -> ImageCallResult:
        self.generated_options = options
        return super().generate(prompt, output_path, options)

    def edit(
        self,
        prompt: str,
        source_image: str | Path,
        output_path: str | Path,
        options: ImageRequestOptions,
    ) -> ImageCallResult:
        self.edited_options = options
        return super().edit(prompt, source_image, output_path, options)


class SugarPaintingServiceTests(unittest.TestCase):
    def test_empty_negative_prompt_is_preserved_and_not_sent(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            service = SugarPaintingService(temporary)
            provider = CapturingSiliconFlowProvider()
            task = service.create_task("马")
            task = service.set_stage_prompts(
                task,
                "sample",
                positive=task.sample_prompt,
                negative="",
            )

            task = service.generate_sample(task, provider, ImageRequestOptions())
            self.assertEqual(task.sample_negative_prompt, "")
            self.assertNotIn("negative_prompt", provider.generated_options.extra_body)
            self.assertEqual(service.load(task.task_id).sample_negative_prompt, "")

    def test_active_task_survives_a_new_service_instance(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            service = SugarPaintingService(temporary)
            created = service.create_task("龙")

            restored = SugarPaintingService(temporary).load_active_task()
            self.assertIsNotNone(restored)
            self.assertEqual(restored.task_id, created.task_id)

            service.clear_active_task()
            self.assertIsNone(SugarPaintingService(temporary).load_active_task())

    def test_completed_remote_line_art_can_be_restored_without_generation(self) -> None:
        class RecoveryProvider:
            provider_id = "bananapro"

            def recover_completed_task(self, task_id, output_path):
                self.task_id = task_id
                output = Path(output_path)
                image = Image.new("RGB", (256, 256), "white")
                draw = ImageDraw.Draw(image)
                draw.line([(30, 200), (80, 60), (190, 80), (220, 200)], fill="black", width=4)
                image.save(output)
                return ImageCallResult(
                    output,
                    self.provider_id,
                    "seedream-5-pro",
                    usage={"task_id": task_id, "recovered": True},
                )

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            service = SugarPaintingService(temporary)
            task = service.create_task("龙")
            sample = Path(temporary) / "sample.png"
            Image.new("RGB", (256, 256), "white").save(sample)
            task = service.import_sample(task, sample.read_bytes(), sample.name)
            task = service.confirm_sample(task)
            provider = RecoveryProvider()

            task = service.recover_line_art(
                task,
                provider,
                "lost-task",
                ImageRequestOptions(),
            )

            self.assertEqual(provider.task_id, "lost-task")
            self.assertTrue(Path(task.line_art_image).is_file())
            self.assertEqual(task.line_art_attempts[-1]["recoveredRemoteTaskId"], "lost-task")
            self.assertEqual(len(service.load(task.task_id).line_art_attempts), 1)

    def test_uploaded_sample_can_be_published_and_reused_by_stage_two(self) -> None:
        class FakeHost:
            expiration_s = 3600

            def upload(self, image_path: str | Path) -> str:
                self.path = Path(image_path)
                return "https://images.example/uploaded-sample.png"

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            service = SugarPaintingService(temporary)
            task = service.create_task("马")
            source = Path(temporary) / "source.png"
            Image.new("RGB", (32, 32), "white").save(source)
            task = service.import_sample(task, source.read_bytes(), source.name)
            task = service.publish_sample(task, FakeHost())

            self.assertEqual(
                task.sample_public_url,
                "https://images.example/uploaded-sample.png",
            )
            self.assertEqual(
                task.sample_attempts[-1]["usage"]["result_url"],
                task.sample_public_url,
            )
            self.assertGreater(task.sample_public_url_expires_at, 0)

    def test_dense_parallel_contour_echo_fails_density_check(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            path = Path(temporary) / "parallel_echo.png"
            image = Image.new("RGB", (256, 256), "white")
            draw = ImageDraw.Draw(image)
            draw.line([(20, 20), (20, 235)], fill="black", width=2)
            for y in range(24, 232, 7):
                draw.line([(20, y), (235, y)], fill="black", width=2)
            image.save(path)

            report = evaluate_traceable_line_image(path)
            self.assertFalse(report.accepted)
            self.assertTrue(any("重复偏移轮廓" in reason for reason in report.reasons))

    def test_many_isolated_lines_fail_continuity_check(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            path = Path(temporary) / "fragments.png"
            image = Image.new("RGB", (256, 256), "white")
            draw = ImageDraw.Draw(image)
            for index in range(24):
                x = 12 + (index % 6) * 40
                y = 15 + (index // 6) * 55
                draw.line([(x, y), (x + 22, y + 12)], fill="black", width=3)
            image.save(path)

            report = evaluate_traceable_line_image(path)
            self.assertFalse(report.accepted)
            self.assertTrue(any("孤立糖线" in reason for reason in report.reasons))

    def test_siliconflow_receives_different_negative_prompts_for_each_stage(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            service = SugarPaintingService(temporary)
            provider = CapturingSiliconFlowProvider()
            options = ImageRequestOptions(extra_body={"cfg": 4.0})
            task = service.create_task("马", prompt_language="zh")

            task = service.generate_sample(task, provider, options)
            self.assertIsNotNone(provider.generated_options)
            self.assertIn("大面积填充", provider.generated_options.extra_body["negative_prompt"])
            self.assertNotIn("negative_prompt", options.extra_body)

            task = service.confirm_sample(task)
            service.extract_line_art(task, provider, options, auto_retry_once=False)
            self.assertIsNotNone(provider.edited_options)
            self.assertIn("合并排线", provider.edited_options.extra_body["negative_prompt"])

    def test_prompts_can_switch_between_chinese_and_english(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            service = SugarPaintingService(temporary)
            task = service.create_task("马", prompt_language="zh")

            self.assertEqual(task.prompt_language, "zh")
            self.assertNotIn("机械臂", task.sample_prompt)
            self.assertNotIn("不得", task.sample_prompt)
            self.assertIn("所有糖线相互关联", task.sample_prompt)
            self.assertIn("严格一对一转换", task.line_art_prompt)
            self.assertIn("中轴线（medial axis）/骨架线提取", task.line_art_prompt)
            self.assertIn("大面积填充", negative_prompt_for("sample", "zh"))
            self.assertIn("孤立线", negative_prompt_for("line_art", "zh"))

            task = service.set_prompt_language(task, "en")
            self.assertEqual(task.prompt_language, "en")
            self.assertNotIn("robot", task.sample_prompt.lower())
            self.assertNotIn("No ", task.sample_prompt)
            self.assertIn("one coherent line network", task.sample_prompt)
            self.assertIn("exactly one input sugar strand", task.line_art_prompt)
            self.assertIn("medial-axis/skeleton extraction", task.line_art_prompt)
            self.assertIn("solid black block", negative_prompt_for("line_art", "en"))

            legacy = task.to_dict()
            legacy.pop("prompt_language")
            restored = type(task).from_dict(legacy)
            self.assertEqual(restored.prompt_language, "en")

    def test_two_stage_task_keeps_sample_lineage_and_confirms_line_art(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            service = SugarPaintingService(temporary)
            provider = FakeImageProvider()
            options = ImageRequestOptions(size="256x256", quality="low")

            task = service.create_task("马")
            self.assertNotIn("马", task.sample_prompt)
            self.assertIn("马", subject_instruction_for("sample", "马", "zh"))
            self.assertTrue(compose_stage_prompt(task, "sample").startswith("生成一幅以“马”为主体"))
            task = service.generate_sample(task, provider, options)
            sample_path = task.sample_image
            task = service.confirm_sample(task)
            task = service.extract_line_art(task, provider, options, auto_retry_once=False)

            self.assertEqual(task.line_art_attempts[-1]["sourceImage"], sample_path)
            self.assertTrue(task.line_art_quality["accepted"])
            task = service.confirm_line_art(task)
            self.assertTrue(task.line_art_confirmed)
            self.assertFalse(task.approved_for_sample_library)

            restored = service.load(task.task_id)
            self.assertEqual(restored.sample_image, sample_path)
            self.assertTrue(restored.line_art_confirmed)

            referenced = service.create_task("龙")
            referenced = service.generate_sample(
                referenced,
                provider,
                options,
                reference_image=sample_path,
            )
            self.assertEqual(referenced.sample_attempts[-1]["referenceImage"], sample_path)

    def test_unapproved_line_art_cannot_enter_curve_pipeline(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            service = SugarPaintingService(temporary)
            task = service.create_task("兔子")
            blank = Image.new("RGB", (256, 256), "white")
            sample = Path(temporary) / "sample.png"
            blank.save(sample)
            task = service.import_sample(task, sample.read_bytes(), sample.name)
            task = service.confirm_sample(task)
            line = Path(temporary) / "line.png"
            blank.save(line)
            task = service.import_line_art(task, line.read_bytes(), line.name)

            self.assertFalse(task.line_art_quality["accepted"])
            with self.assertRaisesRegex(ValueError, "未通过"):
                service.confirm_line_art(task)

            with self.assertRaisesRegex(ValueError, "不能加入"):
                service.confirm_line_art(
                    task,
                    add_to_sample_library=True,
                    allow_quality_override=True,
                )

            task = service.confirm_line_art(task, allow_quality_override=True)
            self.assertTrue(task.line_art_confirmed)
            self.assertTrue(task.line_art_quality_overridden)
            self.assertFalse(task.approved_for_sample_library)
            self.assertTrue(task.line_art_attempts[-1]["manualQualityOverride"])


if __name__ == "__main__":
    unittest.main()
