"""Local ComfyUI workflows for the installed SDXL and Flux Kontext models."""
from __future__ import annotations

import json
import re
import secrets
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib import request

from PIL import Image, ImageOps

from .comfyui_client import ComfyUIClient, ComfyUIError
from .providers import ImageCallResult, ImageProviderError, ImageRequestOptions, _encode_multipart

URL = "http://127.0.0.1:8188"
LABEL = "本地 ComfyUI"
SDXL = "sd_xl_base_1.0.safetensors"
KONTEXT = "flux1-dev-kontext_fp8_scaled.safetensors"
KLEIN = "flux-2-klein-4b-fp8.safetensors"


@dataclass
class LocalSettings:
    installation: str = r"D:\ai\ComfyUI-aki-v1.5"
    timeout_s: int = 600
    profile: str = "installed"

    @classmethod
    def load(cls, root):
        path = cls.path(root)
        return cls(**json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else cls()

    @staticmethod
    def path(root):
        return Path(root) / "data" / "ai_generation" / "comfyui.local.json"

    def save(self, root):
        path = self.path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(vars(self), ensure_ascii=False, indent=2), encoding="utf-8")

    def start(self, root):
        home = Path(self.installation).resolve()
        runtime = Path(root).resolve() / "data" / "ai_generation" / "comfyui"
        runtime.mkdir(parents=True, exist_ok=True)
        model_paths = runtime / "extra-model-paths.yaml"
        model_paths.write_text(
            "tanghua:\n  base_path: " + json.dumps((runtime / "models").as_posix()) +
            "\n  diffusion_models: diffusion_models\n  text_encoders: text_encoders\n  vae: vae\n",
            encoding="utf-8",
        )
        args = [
            str(home / "python" / "python.exe"), str(home / "main.py"),
            "--listen", "127.0.0.1", "--lowvram", "--disable-api-nodes",
            "--disable-all-custom-nodes", "--base-directory", str(home),
            "--extra-model-paths-config", str(model_paths),
            "--database-url", f"sqlite:///{(runtime / 'comfyui.db').as_posix()}",
        ]
        for name in ("input", "output", "temp", "user"):
            (runtime / name).mkdir(exist_ok=True)
            args.extend((f"--{name}-directory", str(runtime / name)))
        with (runtime / "server.log").open("ab") as log:
            subprocess.Popen(args, cwd=home, stdout=log, stderr=subprocess.STDOUT,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def build_workflow(prompt, options, seed, reference="", *, profile="installed"):
    match = re.fullmatch(r"(\d+)x(\d+)", options.size or "")
    width, height = map(int, match.groups()) if match else (768, 768)
    scale = min(1, 768 / max(width, height))
    width, height = (max(64, round(value * scale / 8) * 8) for value in (width, height))
    graph = {}

    def node(key, class_type, **inputs):
        graph[key] = {"class_type": class_type, "inputs": inputs}

    if profile == "klein":
        node("model", "UNETLoader", unet_name=KLEIN, weight_dtype="default")
        node("clip", "CLIPLoader", clip_name="qwen_3_4b.safetensors", type="flux2", device="default")
        node("vae", "VAELoader", vae_name="flux2-vae.safetensors")
        node("text", "CLIPTextEncode", text=prompt, clip=["clip", 0])
        positive = ["text", 0]
        if reference:
            node("load", "LoadImage", image=reference)
            node("encode", "VAEEncode", pixels=["load", 0], vae=["vae", 0])
            node("reference", "ReferenceLatent", conditioning=positive, latent=["encode", 0])
            positive = ["reference", 0]
        node("negative", "ConditioningZeroOut", conditioning=["text", 0])
        node("latent", "EmptyFlux2LatentImage", width=width, height=height, batch_size=1)
        node("guider", "CFGGuider", model=["model", 0], positive=positive, negative=["negative", 0], cfg=1.0)
        node("noise", "RandomNoise", noise_seed=seed)
        node("schedule", "Flux2Scheduler", steps=4, width=width, height=height)
        node("sampler", "KSamplerSelect", sampler_name="euler")
        node("sample", "SamplerCustomAdvanced", noise=["noise", 0], guider=["guider", 0],
             sampler=["sampler", 0], sigmas=["schedule", 0], latent_image=["latent", 0])
        vae = ["vae", 0]
    elif reference:
        node("model", "UNETLoader", unet_name=KONTEXT, weight_dtype="default")
        node("clip", "DualCLIPLoader", clip_name1="t5xxl_fp8_e4m3fn_scaled.safetensors",
             clip_name2="clip_l.safetensors", type="flux", device="default")
        node("vae", "VAELoader", vae_name="ae.safetensors")
        node("load", "LoadImage", image=reference)
        node("resize", "ImageScale", image=["load", 0], upscale_method="area",
             width=width, height=height, crop="disabled")
        node("encode", "VAEEncode", pixels=["resize", 0], vae=["vae", 0])
        node("text", "CLIPTextEncode", text=prompt, clip=["clip", 0])
        node("reference", "ReferenceLatent", conditioning=["text", 0], latent=["encode", 0])
        node("guidance", "FluxGuidance", conditioning=["reference", 0], guidance=2.5)
        node("negative", "ConditioningZeroOut", conditioning=["text", 0])
        node("latent", "EmptySD3LatentImage", width=width, height=height, batch_size=1)
        positive, vae, steps, cfg, sampler, scheduler = ["guidance", 0], ["vae", 0], 20, 1, "euler", "simple"
    else:
        node("model", "CheckpointLoaderSimple", ckpt_name=SDXL)
        node("text", "CLIPTextEncode", text=prompt, clip=["model", 1])
        node("negative", "CLIPTextEncode", text=options.extra_body.get("negative_prompt", ""), clip=["model", 1])
        node("latent", "EmptyLatentImage", width=width, height=height, batch_size=1)
        positive, vae, steps, cfg, sampler, scheduler = ["text", 0], ["model", 2], 24, 6, "euler", "normal"
    if profile != "klein":
        node("sample", "KSampler", model=["model", 0], seed=seed, steps=steps, cfg=cfg,
             sampler_name=sampler, scheduler=scheduler, positive=positive, negative=["negative", 0],
             latent_image=["latent", 0], denoise=1)
    node("decode", "VAEDecode", samples=["sample", 0], vae=vae)
    node("result", "SaveImage", images=["decode", 0], filename_prefix="tanghua")
    return graph


class LocalImageProvider:
    provider_id = "comfyui"
    negative_prompt_mode = "prompt_suffix"

    def __init__(self, settings=None, *, progress_callback=None):
        self.settings = settings or LocalSettings()
        self.generation_model = KLEIN if self.settings.profile == "klein" else SDXL
        self.edit_model = KLEIN if self.settings.profile == "klein" else KONTEXT
        self.client = ComfyUIClient(URL, timeout_s=5)
        self.progress_callback = progress_callback

    def test_connection(self, *, edit=False):
        try:
            self.client._request_json("GET", "/system_stats")
            graph = build_workflow("", ImageRequestOptions(), 0, "input.png" if edit else "",
                                   profile=self.settings.profile)
            for node in graph.values():
                name = node["class_type"]
                schema = self.client._request_json("GET", f"/object_info/{name}").get(name)
                if not schema:
                    return False, f"缺少 ComfyUI 节点：{name}"
                required = schema["input"].get("required", {})
                for key, value in node["inputs"].items():
                    if isinstance(value, str) and value.endswith(".safetensors"):
                        spec = required.get(key, [])
                        # Recent ComfyUI exposes choices as COMBO metadata.
                        choices = spec[0] if spec and isinstance(spec[0], list) else (
                            spec[1].get("options", []) if len(spec) > 1 else []
                        )
                        if value not in choices:
                            return False, f"缺少模型文件：{value}"
        except (ComfyUIError, TimeoutError) as exc:
            return False, str(exc)
        return True, "本地模型已就绪"

    def is_running(self):
        try:
            self.client._request_json("GET", "/system_stats")
        except (ComfyUIError, TimeoutError):
            return False
        return True

    def generate(self, prompt, output_path, options):
        return self._run(prompt, output_path, options)

    def edit(self, prompt, image_path, output_path, options):
        return self._run(prompt, output_path, options, Path(image_path))

    def _run(self, prompt, output_path, options, image_path=None):
        started = time.monotonic()
        seed = int(options.extra_body.get("seed", secrets.randbits(53)))
        try:
            if image_path or self.settings.profile == "klein":
                avoid = str(options.extra_body.get("negative_prompt", "")).strip()
                if avoid:
                    prompt += "\nAvoid: " + avoid
            graph = build_workflow(prompt, options, seed, "reference.png" if image_path else "",
                                   profile=self.settings.profile)
            if image_path:
                latent = graph["latent"]["inputs"]
                with tempfile.TemporaryDirectory() as directory:
                    prepared = Path(directory) / "reference.png"
                    with Image.open(image_path) as source:
                        source = ImageOps.exif_transpose(source).convert("RGBA")
                        white = Image.new("RGBA", source.size, "white")
                        white.alpha_composite(source)
                        ImageOps.pad(white.convert("RGB"), (latent["width"], latent["height"]),
                                     color="white").save(prepared)
                    graph["load"]["inputs"]["image"] = self._upload(prepared)
            queued = self.client.queue_prompt(graph)
            prompt_id = queued["prompt_id"]
            if self.progress_callback:
                self.progress_callback("queued", queued)
            history = self.client.wait_for_history(
                prompt_id, timeout_s=self.settings.timeout_s, progress_callback=self.progress_callback,
            )
            image = next((image for image in self.client.list_output_images(history)
                          if image.node_id == "result"), None)
            if image is None:
                raise ComfyUIError("工作流没有返回预期的线稿或样图。")
            output = self.client.save_image(image, output_path)
        except (ComfyUIError, OSError, ValueError) as exc:
            raise ImageProviderError(f"本地生成失败：{exc}") from exc
        model = self.edit_model if image_path else self.generation_model
        return ImageCallResult(output, self.provider_id, model, prompt_id, {
            "seed": seed, "elapsed_seconds": round(time.monotonic() - started, 2),
            "workflow": graph,
        })

    def _upload(self, path):
        body, mime = _encode_multipart({"subfolder": "tanghua", "overwrite": "false"}, "image", path)
        req = request.Request(f"{URL}/upload/image", body, {"Content-Type": mime})
        with request.urlopen(req, timeout=10) as response:
            result = json.load(response)
        return "/".join(filter(None, (result.get("subfolder"), result["name"])))

