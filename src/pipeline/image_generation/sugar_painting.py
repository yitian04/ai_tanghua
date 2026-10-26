from __future__ import annotations

import json
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from PIL import Image

from src.pipeline.image_generation.providers import (
    ImageCallResult,
    ImageProvider,
    ImageRequestOptions,
)
from src.pipeline.image_generation.quality import ImageQualityReport, evaluate_traceable_line_image
from src.pipeline.image_generation.project_defaults import ProjectDefaultsStore


PROMPT_VERSION = 6


SAMPLE_PROMPT_TEMPLATE_ZH = """生成一幅以“{{OBJECT}}”为主体的中国传统民间糖画。

画面为纯白背景上的琥珀金色糖线图案，主体完整、居中、轮廓清楚，具有传统糖画的手工曲线韵味。

糖线设计：
- 使用清晰、流畅、粗细协调的单线糖丝塑造主体。
- 主轮廓由尽可能连续的长曲线构成，转折自然圆润。
- 所有糖线相互关联并归入主体结构，形成完整连贯的糖线网络。
- 每一条内部糖线至少有一端自然连接主轮廓或主体主干线。
- 内部纹样保持简洁，只保留能够帮助识别主体的线条。
- 主体确实需要内部纹样时，只使用少量、必要的独立结构线；每条线都有清楚的造型作用。
- 相邻糖线之间保留稳定、清楚的白色间隔，整体疏密均衡。

呈现一幅线条清晰、连续、简洁、具有传统民间气质的中国糖画。"""


SAMPLE_PROMPT_TEMPLATE_EN = """Create a traditional Chinese folk sugar painting of {{OBJECT}}.

Present a complete centered subject as amber-gold sugar lines on a pure white background, with a clear silhouette and the flowing handmade character of traditional sugar painting.

Sugar-line design:
- Shape the subject with clear, smooth, coordinated single sugar-strand lines.
- Build the main contour from long continuous curves with naturally rounded turns.
- Connect every sugar line into the subject structure so the artwork forms one coherent line network.
- Connect at least one end of every interior sugar line to the main contour or a structural line.
- Keep interior detail simple and retain only lines that help identify the subject.
- Where interior pattern is essential to recognition, use only a few necessary independent structural lines, each with a clear descriptive purpose.
- Preserve stable white spacing between neighboring sugar lines and keep the overall density balanced.

Present a clear, continuous, concise Chinese folk sugar painting made from expressive sugar lines."""


LINE_ART_PROMPT_TEMPLATE_ZH = """对所提供的“{{OBJECT}}”糖画参考图执行糖线几何中轴提取，输出纯黑白单中心线稿。

这是中轴线（medial axis）/骨架线提取任务，不是轮廓描边、边缘检测或重新设计任务。

保持参考图的主体、姿态、比例、轮廓和糖线拓扑，使用纯白背景与粗细均匀的纯黑中心线重新表达。

线稿结构：
- 主轮廓保持为尽可能完整、连续的长线。
- 一根输入糖线只对应一根输出中心线，严格一对一转换。
- 将每条琶珀色糖线视为一个有宽度的连续笔画区域，只沿该区域的几何中轴输出一根线。
- 无论原糖线多粗，都只保留位于糖线正中间的一根均匀单线；忽略左右两侧边界。
- 输出线不得呈空心管、带状轮廓或成对平行边线。
- 保持参考图中独立糖线的原有数量和位置关系，不增加装饰线。
- 所有内部线条归入同一个主体线网，每条内部线至少有一端连接主轮廓或主体主干线。
- 只有参考图中清楚存在多根彼此独立的糖线时，才按原数量逐根转换；每根仍只输出一根中心线。
- 曲线连接自然，交点明确，主体从轮廓到内部纹样保持连贯。
- 细节数量适中，线条分布疏密均衡。

最终结果只表示原糖线的中轴路径：每条糖线一条中心线，不保留糖线宽度，不保留糖线两侧边缘。"""


LINE_ART_PROMPT_TEMPLATE_EN = """Extract the geometric center paths of the sugar strands in the provided {{OBJECT}} reference and output pure black-and-white single-centerline art.

This is a medial-axis/skeleton extraction task, not contour tracing, edge detection, or redesign.

Preserve the subject, pose, proportions, silhouette, and sugar-line layout. Re-express them as uniform solid-black centerlines on a pure white background.

Line-art structure:
- Keep the main contour as complete continuous long lines wherever possible.
- Convert exactly one input sugar strand into exactly one output centerline.
- Treat each amber sugar strand as one continuous stroke region with width, and output a line only along that region's geometric medial axis.
- Regardless of strand thickness, retain only one uniform line exactly through its middle and ignore both side boundaries.
- The output must never look like a hollow tube, ribbon outline, or paired parallel boundary lines.
- Preserve the original count and positional relationship of independent sugar strands; add no decorative lines.
- Integrate every interior line into one coherent subject network, connecting at least one end to the contour or a structural line.
- Only where the reference clearly contains several genuinely independent sugar strands, convert them one-for-one at the original count; still output only one centerline for each strand.
- Use natural connections and explicit junctions from the outer contour to interior structure.
- Keep a balanced, moderately sparse distribution of detail.

The final result represents only the medial paths of the original sugar strands: one centerline per strand, with neither strand width nor either side edge retained."""


SUBJECT_INSTRUCTION_TEMPLATES = {
    "zh": {
        "sample": "生成一幅以“{{OBJECT}}”为主体的中国传统民间糖画。",
        "line_art": "对所提供的“{{OBJECT}}”糖画参考图执行糖线几何中轴提取，输出纯黑白单中心线稿。",
    },
    "en": {
        "sample": "Create a traditional Chinese folk sugar painting of {{OBJECT}}.",
        "line_art": "Extract the geometric center paths of the sugar strands in the provided {{OBJECT}} reference and output pure black-and-white single-centerline art.",
    },
}


SAMPLE_PROMPT_TEMPLATES = {"zh": SAMPLE_PROMPT_TEMPLATE_ZH, "en": SAMPLE_PROMPT_TEMPLATE_EN}
LINE_ART_PROMPT_TEMPLATES = {"zh": LINE_ART_PROMPT_TEMPLATE_ZH, "en": LINE_ART_PROMPT_TEMPLATE_EN}
SAMPLE_PROMPT_TEMPLATE = SAMPLE_PROMPT_TEMPLATE_ZH
LINE_ART_PROMPT_TEMPLATE = LINE_ART_PROMPT_TEMPLATE_ZH

SAMPLE_NEGATIVE_PROMPTS = {
    "zh": "照片，写实场景，三维雕塑，文字，边框，阴影，渐变，高光，纹理，大面积填充，实心色块，黑色块，糖浆色块，粗带，面状糖片，双边轮廓，重复偏移轮廓，轮廓回声，单线变多线，拥挤线条，过密排线，粘连排线，交叉排线，混乱排线，断裂糖线，孤立糖线，悬空短线，无关装饰",
    "en": "photograph, photorealistic scene, 3D sculpture, text, frame, shadow, gradient, highlight, texture, filled region, solid block, black block, syrup mass, thick ribbon, sugar sheet, double-edge contour, repeated offset contour, contour echo, one line becoming multiple lines, crowded lines, dense hatching, merged hatching, crossing hatching, tangled hatching, broken sugar line, isolated sugar line, floating short stroke, unrelated decoration",
}

LINE_ART_NEGATIVE_PROMPTS = {
    "zh": "灰色背景，彩色背景，灰阶，阴影，渐变，纹理，反光，文字，大面积黑色填充，实心黑块，粗黑带，面状区域，边缘检测，轮廓描边，描画糖线两侧边缘，空心管状线，带状轮廓，成对平行边线，双边轮廓，重复轮廓，新增平行线，单线变多线，密集多排线，轮廓回声，等距复制轮廓，同心重复轮廓，重复偏移线，粘连线条，合并排线，交叉排线，弯折排线，混乱排线，断线，碎线，孤立线，悬空线，闭塞小色块，过密细节",
    "en": "gray background, colored background, grayscale tone, shadow, gradient, texture, reflection, text, large black fill, solid black block, thick black band, filled surface, edge detection, contour tracing, tracing both edges of a sugar strand, hollow tube line, ribbon outline, paired parallel boundary lines, double-edge contour, repeated contour, invented parallel line, one strand becoming multiple lines, dense multi-line band, contour echo, equally spaced contour copies, concentric duplicate outlines, repeated offset line, merged strokes, fused hatching, crossing hatching, bent hatching, tangled hatching, broken line, fragment, isolated line, floating line, enclosed small block, excessive detail",
}

LINE_ART_RETRY_SUFFIXES = {
    "zh": "\n\n严格改为几何中轴提取：将每根有宽度的糖线视为一个笔画区域，只沿区域正中间输出一根连续中轴线；忽略两侧边界；输出不得是空心管、带状轮廓或成对平行线；保持同一主体和姿态。",
    "en": "\n\nStrictly perform medial-axis extraction: treat every sugar strand with width as one stroke region and output one continuous line only through its exact middle; ignore both side boundaries; never output a hollow tube, ribbon outline, or paired parallel lines. Preserve the same subject and pose.",
}

SAMPLE_REFERENCE_SUFFIXES = {
    "zh": "\n\n附带的已批准糖画样本用于参考线条风格、间距和路径复杂度。以当前指定主体形成新的构图，并保持同样简洁、连续、疏朗的单线糖丝特征。",
    "en": "\n\nUse the attached approved sample as a reference for line style, spacing, and path complexity. Compose the requested subject as a new design with the same sparse, continuous, single-strand character.",
}


@dataclass
class SugarPaintingTask:
    task_id: str
    object_name: str
    created_at: str
    updated_at: str
    sample_prompt: str
    line_art_prompt: str
    prompt_language: str = "zh"
    prompt_version: int = PROMPT_VERSION
    sample_negative_prompt: str | None = None
    line_art_negative_prompt: str | None = None
    sample_image: str = ""
    sample_public_url: str = ""
    sample_public_url_expires_at: int = 0
    sample_reference_image: str = ""
    line_art_image: str = ""
    sample_confirmed: bool = False
    line_art_confirmed: bool = False
    line_art_quality: dict[str, Any] = field(default_factory=dict)
    sample_attempts: list[dict[str, Any]] = field(default_factory=list)
    line_art_attempts: list[dict[str, Any]] = field(default_factory=list)
    approved_for_sample_library: bool = False
    line_art_quality_overridden: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SugarPaintingTask":
        fields = cls.__dataclass_fields__
        values = {key: value for key, value in data.items() if key in fields}
        if "prompt_language" not in values:
            prompt = str(values.get("sample_prompt") or "").strip()
            contains_cjk = any("\u4e00" <= char <= "\u9fff" for char in prompt)
            values["prompt_language"] = "zh" if contains_cjk else "en"
        if "prompt_version" not in values:
            values["prompt_version"] = 1
        return cls(**values)


class SugarPaintingService:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.task_root = self.root_dir / "data" / "ai_generation" / "tasks"
        self.sample_root = self.root_dir / "data" / "ai_generation" / "approved_samples"
        self.project_defaults = ProjectDefaultsStore(self.root_dir)
        self.task_root.mkdir(parents=True, exist_ok=True)

    def create_task(
        self,
        object_name: str,
        *,
        prompt_language: str = "zh",
        sample_prompt_template: str | None = None,
        line_art_prompt_template: str | None = None,
    ) -> SugarPaintingTask:
        subject = " ".join(object_name.strip().split())
        if not subject:
            raise ValueError("请输入要生成的主体名称。")
        if len(subject) > 80:
            raise ValueError("主体名称过长，请控制在 80 个字符以内。")
        language = _normalize_prompt_language(prompt_language)
        default_sample, default_sample_negative = self.project_defaults.prompt(
            "sample",
            language,
            fallback_positive=_prompt_body(SAMPLE_PROMPT_TEMPLATES[language]),
            fallback_negative=SAMPLE_NEGATIVE_PROMPTS[language],
        )
        default_line_art, default_line_art_negative = self.project_defaults.prompt(
            "line_art",
            language,
            fallback_positive=_prompt_body(LINE_ART_PROMPT_TEMPLATES[language]),
            fallback_negative=LINE_ART_NEGATIVE_PROMPTS[language],
        )
        sample_template = sample_prompt_template or default_sample
        line_art_template = line_art_prompt_template or default_line_art
        now = _timestamp()
        task = SugarPaintingTask(
            task_id=f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
            object_name=subject,
            created_at=now,
            updated_at=now,
            sample_prompt=_render_prompt(sample_template, subject),
            line_art_prompt=_render_prompt(line_art_template, subject),
            prompt_language=language,
            prompt_version=PROMPT_VERSION,
            sample_negative_prompt=default_sample_negative,
            line_art_negative_prompt=default_line_art_negative,
        )
        self.save(task)
        return task

    def set_prompt_language(self, task: SugarPaintingTask, prompt_language: str) -> SugarPaintingTask:
        language = _normalize_prompt_language(prompt_language)
        sample_positive, sample_negative = self.project_defaults.prompt(
            "sample",
            language,
            fallback_positive=_prompt_body(SAMPLE_PROMPT_TEMPLATES[language]),
            fallback_negative=SAMPLE_NEGATIVE_PROMPTS[language],
        )
        line_positive, line_negative = self.project_defaults.prompt(
            "line_art",
            language,
            fallback_positive=_prompt_body(LINE_ART_PROMPT_TEMPLATES[language]),
            fallback_negative=LINE_ART_NEGATIVE_PROMPTS[language],
        )
        task.prompt_language = language
        task.prompt_version = PROMPT_VERSION
        task.sample_prompt = _render_prompt(sample_positive, task.object_name)
        task.sample_negative_prompt = sample_negative
        task.line_art_prompt = _render_prompt(line_positive, task.object_name)
        task.line_art_negative_prompt = line_negative
        self.save(task)
        return task

    def set_stage_prompts(
        self,
        task: SugarPaintingTask,
        stage: str,
        *,
        positive: str,
        negative: str,
    ) -> SugarPaintingTask:
        if not positive.strip():
            raise ValueError("默认提示词正文不能为空。")
        if stage == "sample":
            task.sample_prompt = positive.strip()
            task.sample_negative_prompt = negative.strip()
        elif stage == "line_art":
            task.line_art_prompt = positive.strip()
            task.line_art_negative_prompt = negative.strip()
        else:
            raise ValueError(f"未知提示词阶段：{stage}")
        self.save(task)
        return task

    def save_stage_prompt_defaults(
        self,
        task: SugarPaintingTask,
        stage: str,
        *,
        positive: str,
        negative: str,
    ) -> Path:
        return self.project_defaults.save_prompt(
            stage,
            task.prompt_language,
            positive=positive.strip(),
            negative=negative,
        )

    def load(self, task_id: str) -> SugarPaintingTask:
        path = self._task_dir(task_id) / "task.json"
        if not path.is_file():
            raise FileNotFoundError(f"AI 生成任务不存在：{task_id}")
        task = SugarPaintingTask.from_dict(json.loads(path.read_text(encoding="utf-8")))
        if task.prompt_version < PROMPT_VERSION:
            task.prompt_language = _normalize_prompt_language(task.prompt_language)
            sample_positive, sample_negative = self.project_defaults.prompt(
                "sample",
                task.prompt_language,
                fallback_positive=_prompt_body(SAMPLE_PROMPT_TEMPLATES[task.prompt_language]),
                fallback_negative=SAMPLE_NEGATIVE_PROMPTS[task.prompt_language],
            )
            line_positive, line_negative = self.project_defaults.prompt(
                "line_art",
                task.prompt_language,
                fallback_positive=_prompt_body(LINE_ART_PROMPT_TEMPLATES[task.prompt_language]),
                fallback_negative=LINE_ART_NEGATIVE_PROMPTS[task.prompt_language],
            )
            task.sample_prompt = _render_prompt(sample_positive, task.object_name)
            task.sample_negative_prompt = sample_negative
            task.line_art_prompt = _render_prompt(line_positive, task.object_name)
            task.line_art_negative_prompt = line_negative
            if task.line_art_image and Path(task.line_art_image).is_file():
                refreshed = _quality_to_dict(evaluate_traceable_line_image(task.line_art_image))
                task.line_art_quality = refreshed
                if task.line_art_attempts:
                    task.line_art_attempts[-1]["quality"] = refreshed
            task.prompt_version = PROMPT_VERSION
            self.save(task)
        if task.sample_negative_prompt is None:
            task.sample_negative_prompt = self.project_defaults.prompt(
                "sample",
                task.prompt_language,
                fallback_positive=_prompt_body(SAMPLE_PROMPT_TEMPLATES[task.prompt_language]),
                fallback_negative=SAMPLE_NEGATIVE_PROMPTS[task.prompt_language],
            )[1]
        if task.line_art_negative_prompt is None:
            task.line_art_negative_prompt = self.project_defaults.prompt(
                "line_art",
                task.prompt_language,
                fallback_positive=_prompt_body(LINE_ART_PROMPT_TEMPLATES[task.prompt_language]),
                fallback_negative=LINE_ART_NEGATIVE_PROMPTS[task.prompt_language],
            )[1]
        return task

    def save(self, task: SugarPaintingTask) -> Path:
        task.updated_at = _timestamp()
        directory = self._task_dir(task.task_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "task.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        active_path = self.task_root.parent / "current_task.txt"
        active_temporary = active_path.with_suffix(".txt.tmp")
        active_temporary.write_text(task.task_id + "\n", encoding="utf-8")
        active_temporary.replace(active_path)
        return path

    def load_active_task(self) -> SugarPaintingTask | None:
        active_path = self.task_root.parent / "current_task.txt"
        if not active_path.is_file():
            return None
        task_id = active_path.read_text(encoding="utf-8").strip()
        if not task_id:
            return None
        try:
            return self.load(task_id)
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            active_path.unlink(missing_ok=True)
            return None

    def clear_active_task(self) -> None:
        (self.task_root.parent / "current_task.txt").unlink(missing_ok=True)

    def generate_sample(
        self,
        task: SugarPaintingTask,
        provider: ImageProvider,
        options: ImageRequestOptions,
        *,
        reference_image: str | Path | None = None,
    ) -> SugarPaintingTask:
        attempt = len(task.sample_attempts) + 1
        output = self._task_dir(task.task_id) / f"sample_a{attempt}.{options.output_format}"
        stage_options = (
            _with_stage_negative_prompt(
                options,
                "sample",
                task.prompt_language,
                override=task.sample_negative_prompt,
            )
            if getattr(provider, "provider_id", "") in {"siliconflow", "bananapro"}
            else options
        )
        base_prompt = compose_stage_prompt(task, "sample")
        prompt = (
            build_reference_sample_prompt(base_prompt, task.prompt_language)
            if reference_image
            else base_prompt
        )
        if reference_image:
            result = provider.edit(prompt, reference_image, output, stage_options)
        else:
            result = provider.generate(prompt, output, stage_options)
        task.sample_image = str(result.output_path)
        task.sample_public_url = str(result.usage.get("result_url") or "")
        task.sample_public_url_expires_at = 0
        task.sample_reference_image = str(reference_image or "")
        task.sample_confirmed = False
        task.line_art_image = ""
        task.line_art_confirmed = False
        task.line_art_quality = {}
        task.line_art_quality_overridden = False
        record = _attempt_record(attempt, result, prompt)
        record["negativePrompt"] = str(stage_options.extra_body.get("negative_prompt") or "")
        if reference_image:
            record["referenceImage"] = str(reference_image)
        task.sample_attempts.append(record)
        self.save(task)
        return task

    def import_sample(
        self,
        task: SugarPaintingTask,
        payload: bytes,
        filename: str,
        *,
        reference_image: str | Path | None = None,
    ) -> SugarPaintingTask:
        attempt = len(task.sample_attempts) + 1
        output = self._task_dir(task.task_id) / f"sample_a{attempt}.png"
        _save_uploaded_image(payload, output)
        task.sample_image = str(output)
        task.sample_public_url = ""
        task.sample_public_url_expires_at = 0
        task.sample_reference_image = str(reference_image or "")
        task.sample_confirmed = False
        task.line_art_image = ""
        task.line_art_confirmed = False
        task.line_art_quality = {}
        task.line_art_quality_overridden = False
        task.sample_attempts.append(
            {
                "attempt": attempt,
                "providerId": "manual_upload",
                "modelId": "local-file",
                "prompt": (
                    build_reference_sample_prompt(
                        compose_stage_prompt(task, "sample"), task.prompt_language
                    )
                    if reference_image
                    else compose_stage_prompt(task, "sample")
                ),
                "outputPath": str(output),
                "referenceImage": str(reference_image or ""),
                "sourceFilename": filename,
                "createdAt": _timestamp(),
            }
        )
        self.save(task)
        return task

    def set_sample_public_url(
        self,
        task: SugarPaintingTask,
        public_url: str,
        *,
        expires_at: int = 0,
    ) -> SugarPaintingTask:
        parsed_url = public_url.strip()
        if not parsed_url.startswith(("https://", "http://")):
            raise ValueError("请输入可从公网访问的 HTTP(S) 图片地址。")
        task.sample_public_url = parsed_url
        task.sample_public_url_expires_at = max(0, int(expires_at))
        if task.sample_attempts:
            usage = dict(task.sample_attempts[-1].get("usage") or {})
            usage["result_url"] = parsed_url
            task.sample_attempts[-1]["usage"] = usage
        self.save(task)
        return task

    def publish_sample(self, task: SugarPaintingTask, image_host: Any) -> SugarPaintingTask:
        if task.sample_public_url and (
            task.sample_public_url_expires_at == 0
            or task.sample_public_url_expires_at > int(time.time()) + 300
        ):
            return task
        if not task.sample_image or not Path(task.sample_image).is_file():
            raise ValueError("当前任务没有可发布的第一阶段图片。")
        expiration_s = max(0, int(getattr(image_host, "expiration_s", 0)))
        expires_at = int(time.time()) + expiration_s if expiration_s else 0
        return self.set_sample_public_url(
            task,
            image_host.upload(task.sample_image),
            expires_at=expires_at,
        )

    def list_approved_samples(self) -> list[dict[str, Any]]:
        if not self.sample_root.is_dir():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(self.sample_root.glob("*/record.json"), reverse=True):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            sample_path = Path(str(record.get("sampleImage") or ""))
            if sample_path.is_file():
                records.append(record)
        return records

    def confirm_sample(self, task: SugarPaintingTask) -> SugarPaintingTask:
        if not task.sample_image or not Path(task.sample_image).is_file():
            raise ValueError("请先生成糖画样图。")
        task.sample_confirmed = True
        task.line_art_image = ""
        task.line_art_confirmed = False
        task.line_art_quality = {}
        task.line_art_quality_overridden = False
        self.save(task)
        return task

    def extract_line_art(
        self,
        task: SugarPaintingTask,
        provider: ImageProvider,
        options: ImageRequestOptions,
        *,
        auto_retry_once: bool = True,
    ) -> SugarPaintingTask:
        if not task.sample_confirmed:
            raise ValueError("必须先确认糖画样图，才能提取线稿。")
        best_result: tuple[ImageCallResult, ImageQualityReport] | None = None
        run_count = 2 if auto_retry_once else 1
        for run_index in range(run_count):
            attempt = len(task.line_art_attempts) + 1
            output = self._task_dir(task.task_id) / f"lineart_a{attempt}.{options.output_format}"
            retry_suffix = LINE_ART_RETRY_SUFFIXES[_normalize_prompt_language(task.prompt_language)]
            prompt = compose_stage_prompt(task, "line_art") + (
                retry_suffix if run_index else ""
            )
            stage_options = (
                _with_stage_negative_prompt(
                    options,
                    "line_art",
                    task.prompt_language,
                    override=task.line_art_negative_prompt,
                )
                if getattr(provider, "provider_id", "") in {"siliconflow", "bananapro"}
                else options
            )
            if getattr(provider, "provider_id", "") == "bananapro":
                reference_url = task.sample_public_url
                if reference_url:
                    stage_options = _with_extra_option(
                        stage_options, "reference_image_url", reference_url
                    )
            result = provider.edit(prompt, task.sample_image, output, stage_options)
            report = evaluate_traceable_line_image(result.output_path)
            task.line_art_attempts.append(
                {
                    **_attempt_record(attempt, result, prompt),
                    "negativePrompt": str(stage_options.extra_body.get("negative_prompt") or ""),
                    "quality": _quality_to_dict(report),
                    "sourceImage": task.sample_image,
                }
            )
            if best_result is None or report.score > best_result[1].score:
                best_result = (result, report)
            if report.accepted:
                break
        if best_result is None:
            raise RuntimeError("模型没有返回可用线稿。")
        task.line_art_image = str(best_result[0].output_path)
        task.line_art_quality = _quality_to_dict(best_result[1])
        task.line_art_confirmed = False
        task.line_art_quality_overridden = False
        self.save(task)
        return task

    def recover_line_art(
        self,
        task: SugarPaintingTask,
        provider: Any,
        remote_task_id: str,
        options: ImageRequestOptions,
    ) -> SugarPaintingTask:
        if not task.sample_confirmed:
            raise ValueError("必须先确认糖画参考图，才能恢复第二阶段结果。")
        attempt = len(task.line_art_attempts) + 1
        output = self._task_dir(task.task_id) / f"lineart_a{attempt}.{options.output_format}"
        result = provider.recover_completed_task(remote_task_id, output)
        report = evaluate_traceable_line_image(result.output_path)
        task.line_art_image = str(result.output_path)
        task.line_art_quality = _quality_to_dict(report)
        task.line_art_confirmed = False
        task.line_art_quality_overridden = False
        task.line_art_attempts.append(
            {
                **_attempt_record(attempt, result, "从 BananaPro 最近任务恢复"),
                "quality": _quality_to_dict(report),
                "sourceImage": task.sample_image,
                "recoveredRemoteTaskId": remote_task_id,
            }
        )
        self.save(task)
        return task

    def import_line_art(self, task: SugarPaintingTask, payload: bytes, filename: str) -> SugarPaintingTask:
        if not task.sample_confirmed:
            raise ValueError("必须先确认糖画样图，才能上传对应线稿。")
        attempt = len(task.line_art_attempts) + 1
        output = self._task_dir(task.task_id) / f"lineart_a{attempt}.png"
        _save_uploaded_image(payload, output)
        report = evaluate_traceable_line_image(output)
        task.line_art_image = str(output)
        task.line_art_quality = _quality_to_dict(report)
        task.line_art_confirmed = False
        task.line_art_quality_overridden = False
        task.line_art_attempts.append(
            {
                "attempt": attempt,
                "providerId": "manual_upload",
                "modelId": "local-file",
                "prompt": compose_stage_prompt(task, "line_art"),
                "outputPath": str(output),
                "sourceImage": task.sample_image,
                "sourceFilename": filename,
                "quality": task.line_art_quality,
                "createdAt": _timestamp(),
            }
        )
        self.save(task)
        return task

    def confirm_line_art(
        self,
        task: SugarPaintingTask,
        *,
        add_to_sample_library: bool = False,
        allow_quality_override: bool = False,
    ) -> SugarPaintingTask:
        if not task.line_art_image or not Path(task.line_art_image).is_file():
            raise ValueError("请先生成或上传黑白线稿。")
        quality_accepted = bool(task.line_art_quality.get("accepted"))
        if not quality_accepted and not allow_quality_override:
            raise ValueError("当前线稿未通过确定性质量检查，不能进入机械臂曲线流程。")
        if not quality_accepted and add_to_sample_library:
            raise ValueError("人工放行的低质量线稿不能加入已批准样本库。")
        task.line_art_confirmed = True
        task.line_art_quality_overridden = bool(not quality_accepted and allow_quality_override)
        task.approved_for_sample_library = bool(add_to_sample_library and quality_accepted)
        if task.line_art_quality_overridden and task.line_art_attempts:
            task.line_art_attempts[-1]["manualQualityOverride"] = True
            task.line_art_attempts[-1]["manualQualityOverrideAt"] = _timestamp()
        self.save(task)
        if add_to_sample_library:
            self._save_approved_sample(task)
        return task

    def _save_approved_sample(self, task: SugarPaintingTask) -> None:
        destination = self.sample_root / task.task_id
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(task.sample_image, destination / "sample.png")
        shutil.copy2(task.line_art_image, destination / "lineart.png")
        record = {
            "taskId": task.task_id,
            "objectName": task.object_name,
            "sampleImage": str(destination / "sample.png"),
            "lineArtImage": str(destination / "lineart.png"),
            "approvedAt": _timestamp(),
            "useAsReferenceByDefault": False,
        }
        (destination / "record.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _task_dir(self, task_id: str) -> Path:
        safe = "".join(char for char in task_id if char.isalnum() or char in "_-")
        if not safe or safe != task_id:
            raise ValueError("任务编号无效。")
        return self.task_root / safe


def _render_prompt(template: str, object_name: str) -> str:
    return template.replace("{{OBJECT}}", object_name.strip())


def _prompt_body(template: str) -> str:
    """Remove the fixed subject instruction from a legacy full prompt template."""
    parts = template.strip().split("\n\n", 1)
    return parts[1].strip() if len(parts) == 2 else template.strip()


def subject_instruction_for(
    stage: str,
    object_name: str,
    prompt_language: str = "zh",
) -> str:
    language = _normalize_prompt_language(prompt_language)
    stage_key = "line_art" if stage == "line_art" else "sample"
    return _render_prompt(SUBJECT_INSTRUCTION_TEMPLATES[language][stage_key], object_name)


def compose_stage_prompt(task: SugarPaintingTask, stage: str) -> str:
    body = task.line_art_prompt if stage == "line_art" else task.sample_prompt
    fixed = subject_instruction_for(stage, task.object_name, task.prompt_language)
    return f"{fixed}\n\n{body.strip()}" if body.strip() else fixed


def build_reference_sample_prompt(base_prompt: str, prompt_language: str = "zh") -> str:
    language = _normalize_prompt_language(prompt_language)
    return base_prompt.rstrip() + SAMPLE_REFERENCE_SUFFIXES[language]


def negative_prompt_for(stage: str, prompt_language: str = "zh") -> str:
    language = _normalize_prompt_language(prompt_language)
    prompts = LINE_ART_NEGATIVE_PROMPTS if stage == "line_art" else SAMPLE_NEGATIVE_PROMPTS
    return prompts[language]


def _with_stage_negative_prompt(
    options: ImageRequestOptions,
    stage: str,
    prompt_language: str,
    *,
    override: str | None = None,
) -> ImageRequestOptions:
    extra_body = dict(options.extra_body)
    value = negative_prompt_for(stage, prompt_language) if override is None else override.strip()
    if value:
        extra_body["negative_prompt"] = value
    else:
        extra_body.pop("negative_prompt", None)
    return replace(options, extra_body=extra_body)


def _with_extra_option(options: ImageRequestOptions, key: str, value: Any) -> ImageRequestOptions:
    extra_body = dict(options.extra_body)
    extra_body[key] = value
    return replace(options, extra_body=extra_body)


def _normalize_prompt_language(value: str) -> str:
    return "en" if str(value).strip().lower().startswith("en") else "zh"


def _save_uploaded_image(payload: bytes, output: Path) -> None:
    if not payload:
        raise ValueError("上传的图像为空。")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        from io import BytesIO

        image = Image.open(BytesIO(payload)).convert("RGB")
        image.save(output, format="PNG")
    except Exception as exc:
        raise ValueError("上传文件不是可识别的图像。") from exc


def _attempt_record(attempt: int, result: ImageCallResult, prompt: str) -> dict[str, Any]:
    return {
        "attempt": int(attempt),
        "providerId": result.provider_id,
        "modelId": result.model_id,
        "prompt": prompt,
        "outputPath": str(result.output_path),
        "requestId": result.request_id,
        "usage": result.usage,
        "revisedPrompt": result.revised_prompt,
        "createdAt": _timestamp(),
    }


def _quality_to_dict(report: ImageQualityReport) -> dict[str, Any]:
    return {
        "accepted": bool(report.accepted),
        "score": int(report.score),
        "reasons": list(report.reasons),
        "metrics": dict(report.metrics),
    }


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
