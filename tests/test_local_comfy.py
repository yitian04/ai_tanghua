import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from src.pipeline.image_generation.comfyui_client import ComfyUIError, ComfyUIImageRef
from src.pipeline.image_generation.local_comfy import LocalImageProvider, build_workflow
from src.pipeline.image_generation.providers import ImageRequestOptions, ImageProviderError
from src.pipeline.image_generation.sugar_painting import SugarPaintingService, SugarPaintingTask


class LocalComfyTests(unittest.TestCase):
    def test_edit_submits_padded_reference_and_downloads_result_node(self):
        with tempfile.TemporaryDirectory(dir=".") as folder:
            reference = Path(folder) / "input.png"
            Image.new("RGB", (80, 50), "black").save(reference)
            provider = LocalImageProvider()
            provider.client = Mock()
            provider.client.queue_prompt.return_value = {"prompt_id": "test"}
            result_image = ComfyUIImageRef("out.png", node_id="result")
            provider.client.list_output_images.return_value = [
                ComfyUIImageRef("ignore.png", node_id="preview"), result_image,
            ]
            output = Path(folder) / "out.png"
            provider.client.save_image.return_value = output

            def upload(path):
                with Image.open(path) as image:
                    self.assertEqual(image.size, (768, 432))
                    self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
                return "tanghua/input.png"

            with patch.object(provider, "_upload", side_effect=upload):
                result = provider.edit("centerline", reference, output, ImageRequestOptions(
                    size="1536x864", extra_body={"seed": 42, "negative_prompt": "shadow"},
                ))
            graph = provider.client.queue_prompt.call_args.args[0]
            self.assertEqual(graph["load"]["inputs"]["image"], "tanghua/input.png")
            self.assertIn("Avoid: shadow", graph["text"]["inputs"]["text"])
            self.assertEqual(result.usage["seed"], 42)
            provider.client.save_image.assert_called_once_with(result_image, output)

    def test_reference_upload_uses_multipart(self):
        with tempfile.TemporaryDirectory(dir=".") as folder:
            source = Path(folder) / "ref.png"
            source.write_bytes(b"png bytes")
            response = Mock()
            response.read.return_value = b'{"name":"ref.png","subfolder":"tanghua"}'
            with patch("urllib.request.urlopen") as open_url:
                open_url.return_value.__enter__.return_value = response
                self.assertEqual(LocalImageProvider()._upload(source), "tanghua/ref.png")
            req = open_url.call_args.args[0]
            self.assertTrue(req.full_url.endswith("/upload/image"))
            self.assertIn(b'name="image"; filename="ref.png"', req.data)
            self.assertIn(b"png bytes", req.data)

    def test_readiness_reports_missing_server_and_model(self):
        provider = LocalImageProvider()
        with patch.object(provider.client, "_request_json", side_effect=ComfyUIError("offline")):
            self.assertEqual(provider.test_connection(), (False, "offline"))
        schema = {"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [[]]}}}}
        with patch.object(provider.client, "_request_json", side_effect=[{}, schema]):
            ok, detail = provider.test_connection()
            self.assertFalse(ok)
            self.assertIn("sd_xl_base", detail)

    def test_generation_reports_timeout_failure_and_empty_output(self):
        provider = LocalImageProvider()
        provider.client = Mock()
        provider.client.queue_prompt.return_value = {"prompt_id": "test"}
        options = ImageRequestOptions()
        for failure in ("Timed out", "execution failed"):
            provider.client.wait_for_history.side_effect = ComfyUIError(failure)
            with self.assertRaisesRegex(ImageProviderError, failure):
                provider.generate("test", Path("unused.png"), options)
        provider.client.wait_for_history.side_effect = None
        provider.client.list_output_images.return_value = []
        with self.assertRaises(ImageProviderError):
            provider.generate("test", Path("unused.png"), options)

    def test_direct_task_has_no_confirmed_sample_and_legacy_default(self):
        with tempfile.TemporaryDirectory(dir=".") as folder:
            service = SugarPaintingService(folder)
            task = service.create_task("Coffee and croissant", mode="direct")
            provider = LocalImageProvider()

            def generate(prompt, output, options):
                from src.pipeline.image_generation.providers import ImageCallResult
                image = Image.new("RGB", (768, 432), "white")
                ImageDraw.Draw(image).ellipse((100, 100, 300, 300), outline="black", width=4)
                image.save(output)
                return ImageCallResult(output, "comfyui", "test-model")

            with patch.object(provider, "generate", side_effect=generate):
                result = service.generate_direct_line_art(task, provider, ImageRequestOptions())
            self.assertFalse(result.sample_confirmed)
            self.assertTrue(Path(result.line_art_image).is_file())
            self.assertEqual(service.load(task.task_id).mode, "direct")
            legacy = task.to_dict()
            del legacy["mode"]
            self.assertEqual(SugarPaintingTask.from_dict(legacy).mode, "two_stage")

    def test_sdxl_workflow_keeps_negative_prompt_and_exact_wide_aspect(self):
        options = ImageRequestOptions(size="1536x864", extra_body={"negative_prompt": "shadow"})
        graph = build_workflow("coffee", options, 13)
        latent = graph["latent"]["inputs"]
        self.assertEqual(latent["width"] * 9, latent["height"] * 16)
        self.assertEqual(graph["negative"]["inputs"]["text"], "shadow")

    def test_klein_uses_four_step_scheduler_and_reference_latent(self):
        graph = build_workflow("line art", ImageRequestOptions(), 91, "ref.png", profile="klein")
        self.assertEqual(graph["schedule"]["inputs"]["steps"], 4)
        self.assertEqual(graph["noise"]["inputs"]["noise_seed"], 91)
        self.assertEqual(graph["guider"]["inputs"]["positive"], ["reference", 0])

    def test_page_restores_local_model_and_can_retry_after_failure(self):
        from streamlit.testing.v1 import AppTest
        from src.pipeline.shop_creation import shared_image_provider

        with tempfile.TemporaryDirectory(dir=".") as folder:
            root = Path(folder).resolve()
            script = f"""
from apps.gui import workspace
from apps.gui.parameter_ui import parameter_scope
from apps.gui.views.direct_curve_page import render
import streamlit as st
root = {str(root)!r}
page = workspace.enter(root, {{"AI糖画线稿": render}})
with workspace.workspace_context(root, page), parameter_scope(root, "ai"):
    try:
        render({{}}, root)
    finally:
        rerun = workspace.after_render()
    if rerun:
        st.rerun()
"""
            app = AppTest.from_string(script).run()
            app.selectbox(key="model_source_stage_1").select("本地 ComfyUI").run()
            app.button(key="save_project_model_default_stage_1").click().run()
            self.assertEqual(shared_image_provider(root)[0].provider_id, "comfyui")
            restarted = AppTest.from_string(script).run()
            self.assertEqual(restarted.selectbox(key="model_source_stage_1").value, "本地 ComfyUI")
            app.radio(key="ai_sugar_mode").set_value("直接线稿").run()
            next(field for field in app.text_input if field.label == "主体名称").set_value("Coffee and croissant")
            next(button for button in app.button if button.label == "新建任务").click().run()
            with patch.object(LocalImageProvider, "generate", side_effect=ImageProviderError("本地服务不可达")):
                for _ in range(2):
                    next(button for button in app.button if button.label == "生成黑白线稿").click().run()
                    self.assertEqual(app.session_state["wf_notice"], "本地服务不可达")
                    self.assertFalse(app.session_state["wf_running"])
            app.radio(key="ai_sugar_mode").set_value("两阶段").run()
            app.selectbox(key="model_source_stage_1").select("硅基流动（中国大陆 API）").run()
            self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()

