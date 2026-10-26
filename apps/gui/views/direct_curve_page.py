from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import streamlit as st

from src.pipeline.image_generation import (
    BananaProCredentialStore,
    BananaProSavedConfig,
    PROVIDER_SPECS,
    ImageProviderError,
    ImageRequestOptions,
    ImgBBImageHost,
    PiGatewayImageProvider,
    PiModelGatewayClient,
    ProviderConfig,
    PublicImageHostCredentialStore,
    PublicImageHostSavedConfig,
    ProjectDefaultsStore,
    SiliconFlowCredentialStore,
    SiliconFlowSavedConfig,
    SugarPaintingService,
    SugarPaintingTask,
    create_image_provider,
    negative_prompt_for,
    subject_instruction_for,
)


PI_SOURCE = "Pi 模型中心（订阅 / OAuth / API Key）"
SILICONFLOW_SOURCE = "硅基流动（中国大陆 API）"
BANANAPRO_SOURCE = "BananaPro（多模型 API）"
COMPATIBLE_SOURCE = "自定义兼容 API"
SOURCE_LABELS = {
    "siliconflow": SILICONFLOW_SOURCE,
    "bananapro": BANANAPRO_SOURCE,
    "pi": PI_SOURCE,
    "compatible": COMPATIBLE_SOURCE,
}

SILICONFLOW_GENERATION_MODELS = {
    "Qwen Image（推荐）": "Qwen/Qwen-Image",
    "Z-Image": "Tongyi-MAI/Z-Image",
    "Z-Image Turbo": "Tongyi-MAI/Z-Image-Turbo",
    "Kolors": "Kwai-Kolors/Kolors",
}
SILICONFLOW_EDIT_MODELS = {
    "Qwen Image Edit 2509（推荐）": "Qwen/Qwen-Image-Edit-2509",
    "Qwen Image Edit": "Qwen/Qwen-Image-Edit",
}
CUSTOM_MODEL_LABEL = "自定义模型 ID…"
BANANAPRO_FALLBACK_MODELS = [
    {"id": "nano-banana-pro", "name": "Nano Banana Pro", "type": "image", "types": ["text-to-image", "image-to-image"]},
    {"id": "seedream-5-pro", "name": "Seedream 5 Pro", "type": "image", "types": ["text-to-image", "image-to-image"]},
    {"id": "nano-banana-2", "name": "Nano Banana 2", "type": "image", "types": ["text-to-image", "image-to-image"]},
    {"id": "nano-banana-2-lite", "name": "Nano Banana 2 Lite", "type": "image", "types": ["text-to-image", "image-to-image"]},
    {"id": "gpt-image-2.5", "name": "GPT Image 2.5", "type": "image", "types": ["text-to-image", "image-to-image"]},
    {"id": "gpt-image-2", "name": "GPT Image 2", "type": "image", "types": ["text-to-image", "image-to-image"]},
]


def render(config: dict, root_dir: str) -> None:
    del config
    service = SugarPaintingService(root_dir)
    task = _load_current_task(service)

    st.subheader("AI 糖画样图与线稿")
    st.caption("先确认糖画样图，再基于同一张图提取黑白线稿。只有通过检查并确认的线稿才能进入曲线流程。")
    _render_step_status(task)
    default_stage = "第二阶段 · 提取单中心线" if task and task.sample_confirmed else "第一阶段 · 生成糖画"
    stage_label = st.segmented_control(
        "当前阶段",
        ["第一阶段 · 生成糖画", "第二阶段 · 提取单中心线"],
        default=default_stage,
        selection_mode="single",
        key="ai_sugar_active_stage",
    ) or default_stage

    if stage_label.startswith("第一阶段"):
        _render_stage_one_page(service, task, root_dir)
    else:
        _render_stage_two_page(service, task, root_dir)


def _render_stage_one_page(
    service: SugarPaintingService,
    task: SugarPaintingTask | None,
    root_dir: str,
) -> None:
    provider, ready, supports_reference, options, _, reference_image, _ = (
        _render_model_settings(service, root_dir, stage=1)
    )
    left, right = st.columns([0.88, 1.52], gap="large")
    with left:
        task = _render_task_controls(service, task)
        if task is not None:
            _render_sample_controls(
                service,
                task,
                provider,
                ready,
                supports_reference,
                options,
                reference_image,
            )
    with right:
        _render_stage_one_preview(task)


def _render_stage_two_page(
    service: SugarPaintingService,
    task: SugarPaintingTask | None,
    root_dir: str,
) -> None:
    provider, ready, supports_reference, options, auto_retry, _, image_host = (
        _render_model_settings(service, root_dir, stage=2)
    )
    left, right = st.columns([0.9, 1.5], gap="large")
    with left:
        task = _render_stage_two_task_input(service, task)
        if task is not None and task.sample_confirmed:
            _render_line_art_controls(
                service,
                task,
                provider,
                ready,
                supports_reference,
                options,
                auto_retry,
                image_host=image_host,
            )
    with right:
        _render_stage_two_preview(task)


def _render_step_status(task: SugarPaintingTask | None) -> None:
    sample_ready = bool(task and task.sample_confirmed)
    line_ready = bool(task and task.line_art_confirmed)
    labels = [
        ("1", "生成糖画样图", bool(task and task.sample_image), sample_ready),
        ("2", "提取黑白线稿", bool(task and task.line_art_image), line_ready),
        ("3", "进入曲线流程", line_ready, line_ready),
    ]
    columns = st.columns(3)
    for column, (number, label, has_output, confirmed) in zip(columns, labels):
        if confirmed:
            state = "已确认"
        elif has_output:
            state = "等待确认"
        else:
            state = "未开始"
        column.markdown(f"**{number}. {label}**")
        column.caption(state)
    st.divider()


def _render_model_settings(
    service: SugarPaintingService,
    root_dir: str,
    *,
    stage: int,
) -> tuple[Any | None, bool, bool, ImageRequestOptions, bool, str, Any | None]:
    image_provider: Any | None = None
    model_ready = False
    supports_reference = False
    project_store = ProjectDefaultsStore(root_dir)
    stage_key = "sample" if stage == 1 else "line_art"
    project_default = project_store.stage(stage_key)

    stage_name = "第一阶段" if stage == 1 else "第二阶段"
    with st.expander(f"{stage_name}模型配置", expanded=False):
        sources = (
            [SILICONFLOW_SOURCE, BANANAPRO_SOURCE, PI_SOURCE, COMPATIBLE_SOURCE]
            if stage == 1
            else [BANANAPRO_SOURCE, SILICONFLOW_SOURCE, PI_SOURCE, COMPATIBLE_SOURCE]
        )
        default_source = SOURCE_LABELS.get(project_default["source"], sources[0])
        source = st.selectbox(
            "模型服务商",
            sources,
            index=sources.index(default_source) if default_source in sources else 0,
            help="每个服务商独立保存配置；切换服务商不会覆盖其他密钥。",
            key=f"model_source_stage_{stage}",
        )

        selected_generation_model = ""
        provider_options: dict[str, Any] = {}
        if source == SILICONFLOW_SOURCE:
            image_provider, model_ready, supports_reference, selected_generation_model = (
                _render_siliconflow_provider(
                    root_dir,
                    stage=stage,
                    default_model=(
                        project_default["model_id"]
                        if project_default["source"] == "siliconflow"
                        else ""
                    ),
                )
            )
        elif source == BANANAPRO_SOURCE:
            (
                image_provider,
                model_ready,
                supports_reference,
                selected_generation_model,
                provider_options,
            ) = _render_bananapro_provider(
                root_dir,
                stage=stage,
                default_model=(
                    project_default["model_id"]
                    if project_default["source"] == "bananapro"
                    else ""
                ),
            )
        elif source == PI_SOURCE:
            image_provider, model_ready, supports_reference = _render_pi_model_center(
                root_dir,
                default_provider_id=(
                    project_default["provider_id"]
                    if project_default["source"] == "pi"
                    else ""
                ),
                default_model_id=(
                    project_default["model_id"]
                    if project_default["source"] == "pi"
                    else ""
                ),
            )
            selected_generation_model = str(getattr(image_provider, "model_id", "") or "")
        else:
            image_provider, model_ready, supports_reference = _render_compatible_provider(
                default_provider_id=(
                    project_default["provider_id"]
                    if project_default["source"] == "compatible"
                    else ""
                ),
                default_model_id=(
                    project_default["model_id"]
                    if project_default["source"] == "compatible"
                    else ""
                ),
            )
            selected_generation_model = str(getattr(image_provider, "model", "") or "")

        selected_provider_id = str(getattr(image_provider, "provider_id", "") or "")
        source_id = next(
            (source_id for source_id, label in SOURCE_LABELS.items() if label == source),
            "compatible",
        )
        default_matches = (
            project_default["source"] == source_id
            and project_default["provider_id"] == selected_provider_id
            and project_default["model_id"] == selected_generation_model
        )
        if st.button(
            "保存为项目默认模型",
            width="stretch",
            disabled=not bool(selected_provider_id and selected_generation_model),
            key=f"save_project_model_default_stage_{stage}",
            help="只保存服务商和模型 ID 到 config，不保存 API Key。该配置可以提交到 GitHub。",
        ):
            try:
                project_store.save_stage(
                    stage_key,
                    source=source_id,
                    provider_id=selected_provider_id,
                    model_id=selected_generation_model,
                )
            except Exception as exc:
                st.error(f"默认模型保存失败：{exc}")
            else:
                st.success("已保存为项目默认模型；该设置可以随代码上传 GitHub。")
        elif default_matches:
            st.caption("当前选择是项目默认模型。")

        st.markdown("**运行选项**")
        if stage == 2 or source in {PI_SOURCE, BANANAPRO_SOURCE}:
            size, quality = "1024x1024", "medium"
            if source == PI_SOURCE:
                st.caption("Pi 会按所选模型的原生能力决定输出尺寸与质量。")
        elif source == SILICONFLOW_SOURCE:
            size_choices = _siliconflow_size_choices(selected_generation_model)
            size = st.selectbox(
                "样图尺寸",
                size_choices,
                index=0,
                help="尺寸选项会跟随样图模型切换；第二阶段编辑模型不接收尺寸参数。",
            )
            quality = "medium"
        else:
            size = st.selectbox("图片尺寸", ["1024x1024", "1024x1536", "1536x1024"], index=0)
            quality = st.selectbox("生成质量", ["low", "medium", "high", "xhigh", "max"], index=1)
        auto_retry_once = False
        reference_image = ""
        image_host = None
        if stage == 1:
            approved_samples = service.list_approved_samples()
            use_reference = st.checkbox(
                "参考已批准样本",
                value=False,
                disabled=not approved_samples,
                help="默认关闭，只参考一个已批准样本的线条风格和复杂度。",
                key="stage1_use_reference",
            )
            if use_reference and approved_samples:
                sample_labels = {
                    f"{item.get('objectName', '未命名')} · {item.get('taskId', '')}": str(item.get("sampleImage") or "")
                    for item in approved_samples
                }
                selected_sample = st.selectbox(
                    "参考样本", list(sample_labels.keys()), key="stage1_reference_sample"
                )
                reference_image = sample_labels[selected_sample]
                if not supports_reference:
                    st.warning("所选模型不支持参考图输入，请关闭参考样本或更换模型。")
            elif not approved_samples:
                st.caption("样本库为空；只有主动批准的线稿才会进入样本库。")
        else:
            auto_retry_once = st.checkbox(
                "质量未通过时自动修复一次",
                value=True,
                help="单次操作最多调用两次编辑接口。",
                key="stage2_auto_retry",
            )
            if bool(getattr(image_provider, "requires_public_reference_image", False)):
                image_host = _render_public_image_host(root_dir)

    return (
        image_provider,
        model_ready,
        supports_reference,
        ImageRequestOptions(
            size=size,
            quality=quality,
            extra_body=(
                {
                    "num_inference_steps": 30,
                    "cfg": 4.0,
                }
                if source == SILICONFLOW_SOURCE
                else provider_options
            ),
        ),
        auto_retry_once,
        reference_image,
        image_host,
    )


def _render_siliconflow_provider(
    root_dir: str, *, stage: int, default_model: str = ""
) -> tuple[Any | None, bool, bool, str]:
    spec = PROVIDER_SPECS["siliconflow"]
    store = SiliconFlowCredentialStore(root_dir)
    saved = store.load()
    st.caption("本阶段使用硅基流动独立 API；密钥与另一阶段共用。")
    generation_model = saved.generation_model or spec.default_model
    edit_model = saved.edit_model or spec.default_edit_model
    if stage == 1:
        generation_model = _render_model_dropdown(
            "糖画样图模型",
            SILICONFLOW_GENERATION_MODELS,
            os.getenv("SILICONFLOW_GENERATION_MODEL", default_model or generation_model),
            key="siliconflow_generation_model_v2",
        )
    else:
        edit_model = _render_model_dropdown(
            "单中心线提取模型",
            SILICONFLOW_EDIT_MODELS,
            os.getenv("SILICONFLOW_EDIT_MODEL", default_model or edit_model),
            key="siliconflow_edit_model_v2",
        )
    base_url = st.text_input(
        "API 地址",
        value=os.getenv("SILICONFLOW_BASE_URL", saved.base_url or spec.default_base_url),
        key=f"siliconflow_base_url_stage_{stage}",
    )
    entered_api_key = st.text_input(
        "API Key（留空则使用已保存的密钥）",
        type="password",
        key=f"siliconflow_api_key_stage_{stage}",
        help="点击“保存配置”后会写入本机 data/model_gateway/siliconflow.json；该目录不会提交到 Git。",
    )
    environment_key = os.getenv("SILICONFLOW_API_KEY", "").strip() or os.getenv(
        "AI_IMAGE_API_KEY", ""
    ).strip()
    effective_api_key = entered_api_key.strip() or environment_key or saved.api_key
    provider = create_image_provider(
        ProviderConfig(
            provider_id="siliconflow",
            model=generation_model,
            edit_model=edit_model,
            api_key=effective_api_key,
            base_url=base_url,
        )
    )

    save_col, clear_col = st.columns(2)
    with save_col:
        if st.button(
            "保存配置",
            width="stretch",
            disabled=not bool(effective_api_key),
            key=f"save_siliconflow_config_stage_{stage}",
        ):
            try:
                store.save(
                    SiliconFlowSavedConfig(
                        api_key=effective_api_key,
                        base_url=base_url.strip(),
                        generation_model=generation_model.strip(),
                        edit_model=edit_model.strip(),
                    )
                )
            except Exception as exc:
                st.error(f"保存失败：{exc}")
            else:
                st.success("配置已保存在本机，重启后会自动使用。")
    with clear_col:
        if st.button(
            "删除已保存密钥",
            width="stretch",
            disabled=not bool(saved.api_key),
            key=f"clear_siliconflow_config_stage_{stage}",
        ):
            store.clear()
            st.session_state.pop(f"siliconflow_api_key_stage_{stage}", None)
            st.rerun()

    if saved.api_key:
        st.caption("已检测到本机保存的硅基流动密钥；输入框可以留空。")
    elif environment_key:
        st.caption("正在使用环境变量中的硅基流动密钥。")
    if st.button(
        "测试并保存连接",
        type="primary",
        width="stretch",
        key=f"test_siliconflow_stage_{stage}",
    ):
        ok, message = provider.test_connection()
        if ok:
            try:
                store.save(
                    SiliconFlowSavedConfig(
                        api_key=effective_api_key,
                        base_url=base_url.strip(),
                        generation_model=generation_model.strip(),
                        edit_model=edit_model.strip(),
                    )
                )
            except Exception as exc:
                st.error(f"连接成功，但保存配置失败：{exc}")
            else:
                st.success(f"{message}；配置已保存。")
        else:
            st.error(message)
    models_ready = bool(
        generation_model.strip() if stage == 1 else edit_model.strip()
    )
    selected_model = generation_model if stage == 1 else edit_model
    return provider, bool(effective_api_key and models_ready), True, selected_model


def _render_bananapro_provider(
    root_dir: str,
    *,
    stage: int,
    default_model: str = "",
) -> tuple[Any | None, bool, bool, str, dict[str, Any]]:
    spec = PROVIDER_SPECS["bananapro"]
    store = BananaProCredentialStore(root_dir)
    saved = store.load()

    st.caption(
        "第一阶段默认 Nano Banana Pro。"
        if stage == 1
        else "第二阶段默认 Seedream 5 Pro，可读取第一阶段的公开参考图。"
    )
    st.markdown("**账户连接**")
    entered_api_key = st.text_input(
        "API Key（留空则使用已保存的密钥）",
        type="password",
        key=f"bananapro_api_key_stage_{stage}",
        help="保存后仅写入本机 data/model_gateway/bananapro.json，不进入项目版本库。",
    )
    environment_key = (
        os.getenv("BANANAPRO_API_KEY", "").strip()
        or os.getenv("NANOBANANA_API_KEY", "").strip()
        or os.getenv("AI_IMAGE_API_KEY", "").strip()
    )
    effective_api_key = entered_api_key.strip() or environment_key or saved.api_key
    with st.expander("高级连接设置", expanded=False):
        base_url = st.text_input(
            "API 地址",
            value=os.getenv("BANANAPRO_BASE_URL", saved.base_url or spec.default_base_url),
            key=f"bananapro_base_url_stage_{stage}",
        )

    discovery_provider = create_image_provider(
        ProviderConfig(
            provider_id="bananapro",
            model=saved.generation_model or spec.default_model,
            edit_model=saved.edit_model or spec.default_edit_model,
            api_key=effective_api_key,
            base_url=base_url,
            timeout_s=300,
        )
    )
    refresh_col, clear_col = st.columns(2)
    with refresh_col:
        if st.button(
            "测试连接并刷新模型",
            type="primary",
            width="stretch",
            disabled=not bool(effective_api_key),
            key=f"refresh_bananapro_models_stage_{stage}",
        ):
            try:
                st.session_state["bananapro_models"] = discovery_provider.list_models()
            except Exception as exc:
                st.error(f"连接或读取模型列表失败：{exc}")
            else:
                ok, message = discovery_provider.test_connection()
                (st.success if ok else st.warning)(message)
    with clear_col:
        if st.button(
            "删除本机密钥",
            width="stretch",
            disabled=not bool(saved.api_key),
            key=f"clear_bananapro_config_stage_{stage}",
        ):
            store.clear()
            st.session_state.pop(f"bananapro_api_key_stage_{stage}", None)
            st.session_state.pop("bananapro_models", None)
            st.rerun()

    if saved.api_key:
        st.caption("已检测到本机保存的 BananaPro 密钥，输入框可留空。")
    elif environment_key:
        st.caption("正在使用环境变量中的 BananaPro 密钥。")

    models = st.session_state.get("bananapro_models") or BANANAPRO_FALLBACK_MODELS
    generation_models = _bananapro_model_options(models, "text-to-image")
    edit_models = _bananapro_model_options(models, "image-to-image")
    st.markdown("**本阶段模型**")
    generation_model = saved.generation_model or spec.default_model
    edit_model = saved.edit_model or spec.default_edit_model
    if stage == 1:
        generation_model = _render_model_dropdown(
            "糖画样图模型",
            generation_models,
            os.getenv(
                "BANANAPRO_GENERATION_MODEL",
                default_model or saved.generation_model or spec.default_model,
            ),
            key="bananapro_generation_model",
        )
        st.caption("默认：Nano Banana Pro")
    else:
        edit_model = _render_model_dropdown(
            "单中心线提取模型",
            edit_models,
            os.getenv(
                "BANANAPRO_EDIT_MODEL",
                default_model or saved.edit_model or spec.default_edit_model,
            ),
            key="bananapro_edit_model",
        )
        st.caption("默认：Seedream 5 Pro")

    st.markdown("**图像参数**")
    resolution_col, ratio_col, mode_col = st.columns(3)
    with resolution_col:
        resolution_choices = ["1K", "2K", "4K"]
        resolution = st.selectbox(
            "分辨率",
            resolution_choices,
            index=_choice_index(resolution_choices, saved.resolution, 0),
            key="bananapro_resolution",
            help="只传给明确支持分辨率参数的模型；Seedream 5 Pro 最高 2K。",
        )
    with ratio_col:
        ratio_choices = ["1:1", "4:3", "3:4", "16:9", "9:16", "2:3", "3:2"]
        aspect_ratio = st.selectbox(
            "画面比例",
            ratio_choices,
            index=_choice_index(ratio_choices, saved.aspect_ratio, 0),
            key="bananapro_aspect_ratio",
        )
    with mode_col:
        mode_choices = ["standard", "economy"]
        generation_mode = st.selectbox(
            "Seedream 模式",
            mode_choices,
            index=_choice_index(mode_choices, saved.generation_mode, 0),
            key="bananapro_generation_mode",
            help="只作用于 Seedream 5 Pro。",
        )

    provider = create_image_provider(
        ProviderConfig(
            provider_id="bananapro",
            model=generation_model,
            edit_model=edit_model,
            api_key=effective_api_key,
            base_url=base_url,
            timeout_s=300,
        )
    )
    if st.button(
        "保存 BananaPro 配置",
        width="stretch",
        disabled=not bool(
            effective_api_key and (generation_model if stage == 1 else edit_model)
        ),
        key=f"save_bananapro_config_stage_{stage}",
    ):
        try:
            store.save(
                BananaProSavedConfig(
                    api_key=effective_api_key,
                    base_url=base_url.strip(),
                    generation_model=generation_model,
                    edit_model=edit_model,
                    resolution=resolution,
                    aspect_ratio=aspect_ratio,
                    generation_mode=generation_mode,
                )
            )
        except Exception as exc:
            st.error(f"保存失败：{exc}")
        else:
            st.success("BananaPro 配置已保存在本机，重启后会自动使用。")

    return (
        provider,
        bool(effective_api_key and (generation_model if stage == 1 else edit_model)),
        True,
        generation_model if stage == 1 else edit_model,
        {
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "generation_mode": generation_mode,
        },
    )


def _bananapro_model_options(models: list[dict[str, Any]], capability: str) -> dict[str, str]:
    options: dict[str, str] = {}
    for item in models:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        capabilities = item.get("types") or []
        if not model_id or (capabilities and capability not in capabilities):
            continue
        name = str(item.get("name") or model_id).strip()
        label = name if name == model_id else f"{name} · {model_id}"
        options[label] = model_id
    if not options:
        options["自定义模型"] = ""
    return options


def _choice_index(choices: list[str], current: str, fallback: int) -> int:
    return choices.index(current) if current in choices else fallback


def _render_public_image_host(root_dir: str) -> ImgBBImageHost | None:
    store = PublicImageHostCredentialStore(root_dir)
    saved = store.load()
    st.markdown("**本地图片转公开 URL**")
    st.caption("当前编辑模型需要公网图片地址；本地测试图会在点击提取时自动上传。任何持有该地址的人在有效期内都可访问图片。")
    st.link_button("获取 ImgBB API Key", "https://api.imgbb.com/", width="stretch")
    entered_key = st.text_input(
        "ImgBB API Key（留空则使用已保存密钥）",
        type="password",
        key="imgbb_api_key",
        help="图片只用于模型读取；默认 24 小时后由图床自动删除。",
    )
    environment_key = os.getenv("IMGBB_API_KEY", "").strip()
    effective_key = entered_key.strip() or environment_key or saved.imgbb_api_key
    expiration_labels = {
        "1 小时": 3600,
        "24 小时": 86400,
        "7 天": 604800,
    }
    current_label = next(
        (
            label
            for label, seconds in expiration_labels.items()
            if seconds == saved.expiration_s
        ),
        "24 小时",
    )
    expiration_label = st.selectbox(
        "公开地址有效期",
        list(expiration_labels),
        index=list(expiration_labels).index(current_label),
        key="imgbb_expiration",
    )
    save_col, clear_col = st.columns(2)
    with save_col:
        if st.button(
            "保存图片托管配置",
            width="stretch",
            disabled=not bool(effective_key),
            key="save_imgbb_config",
        ):
            try:
                store.save(
                    PublicImageHostSavedConfig(
                        imgbb_api_key=effective_key,
                        expiration_s=expiration_labels[expiration_label],
                    )
                )
            except Exception as exc:
                st.error(f"保存失败：{exc}")
            else:
                st.success("图片托管配置已保存在本机。")
    with clear_col:
        if st.button(
            "删除托管密钥",
            width="stretch",
            disabled=not bool(saved.imgbb_api_key),
            key="clear_imgbb_config",
        ):
            store.clear()
            st.session_state.pop("imgbb_api_key", None)
            st.rerun()
    if saved.imgbb_api_key:
        st.caption("已检测到本机保存的 ImgBB 密钥。")
    if not effective_key:
        st.warning("若使用本地上传图或无公开地址的模型输出，需要先配置 ImgBB API Key。")
        return None
    return ImgBBImageHost(
        effective_key,
        expiration_s=expiration_labels[expiration_label],
    )


def _render_model_dropdown(
    label: str,
    models: dict[str, str],
    current_model: str,
    *,
    key: str,
) -> str:
    """Select a known model while retaining arbitrary future model IDs."""
    current = current_model.strip()
    label_by_id = {model_id: model_label for model_label, model_id in models.items()}
    choices = list(models.keys())
    if current and current not in label_by_id:
        current_label = f"当前模型 · {current}"
        choices.append(current_label)
        label_by_id[current] = current_label
    choices.append(CUSTOM_MODEL_LABEL)
    default_label = label_by_id.get(current, next(iter(models)))
    selected_label = st.selectbox(label, choices, index=choices.index(default_label), key=key)
    if selected_label == CUSTOM_MODEL_LABEL:
        return st.text_input(
            f"{label}：自定义 ID",
            value=current if current not in models.values() else "",
            key=f"{key}_custom",
            placeholder="例如：厂商/模型名称",
        ).strip()
    if selected_label.startswith("当前模型 · "):
        return current
    return models[selected_label]


def _siliconflow_size_choices(model_id: str) -> list[str]:
    if model_id == "Qwen/Qwen-Image":
        return [
            "1328x1328",
            "1472x1140",
            "1140x1472",
            "1664x928",
            "928x1664",
            "1584x1056",
            "1056x1584",
        ]
    if model_id == "Kwai-Kolors/Kolors":
        return ["1024x1024", "960x1280", "768x1024", "720x1440", "720x1280"]
    return ["1024x1024"]


def _render_pi_model_center(
    root_dir: str,
    *,
    default_provider_id: str = "",
    default_model_id: str = "",
) -> tuple[Any | None, bool, bool]:
    client = PiModelGatewayClient(root_dir)
    try:
        health = client.ensure_running()
        providers = client.providers()
        image_models = client.image_models()
    except Exception as exc:
        st.error(str(exc))
        st.caption("请确认 Node.js ≥ 22.19，并在项目目录执行 npm install。")
        return None, False, False

    st.caption(f"模型网关已连接 · pi-ai {health.get('piVersion', 'unknown')}")
    model_tab, account_tab = st.tabs(["生图模型", "订阅与凭据"])

    provider_by_id = {str(item.get("id")): item for item in providers}
    with account_tab:
        _render_pi_account_manager(client, providers)

    with model_tab:
        if not image_models:
            st.warning("pi 当前模型目录中没有可用生图模型。")
            return None, False, False
        region_blocked = set(st.session_state.get("pi_region_blocked_models") or [])
        if region_blocked:
            available_models = [item for item in image_models if item.get("id") not in region_blocked]
            if available_models:
                image_models = available_models
            st.warning(
                f"已隐藏 {len(region_blocked)} 个被 OpenRouter 判定为当前地区不可用的模型。"
            )
            if st.button("重新显示这些模型", key="pi_clear_region_blocked"):
                st.session_state.pop("pi_region_blocked_models", None)
                st.rerun()
        image_provider_ids = sorted({str(item.get("providerId")) for item in image_models})
        provider_labels = {
            provider_id: str(provider_by_id.get(provider_id, {}).get("name") or provider_id)
            for provider_id in image_provider_ids
        }
        provider_choices = list(provider_labels.values())
        default_provider_label = provider_labels.get(default_provider_id, provider_choices[0])
        selected_provider_label = st.selectbox(
            "生图服务商",
            provider_choices,
            index=provider_choices.index(default_provider_label),
        )
        provider_id = next(key for key, value in provider_labels.items() if value == selected_provider_label)
        provider_models = [item for item in image_models if item.get("providerId") == provider_id]
        model_labels = {
            f"{item.get('name')} · {item.get('id')}": item for item in provider_models
        }
        default_label = next(
            (
                label
                for label, item in model_labels.items()
                if item.get("id") == default_model_id
            ),
            next(
                (
                    label
                    for label, item in model_labels.items()
                    if item.get("id") == "qwen/qwen-image-2.1-turbo"
                ),
                next(iter(model_labels)),
            ),
        )
        selected_label = st.selectbox(
            "生图模型",
            list(model_labels.keys()),
            index=list(model_labels.keys()).index(default_label),
            key="pi_image_model_v2",
        )
        selected_model = model_labels[selected_label]
        supports_reference = bool(selected_model.get("supportsReferenceImage"))
        configured = bool(provider_by_id.get(provider_id, {}).get("configured"))
        if configured:
            st.success(
                f"{provider_labels[provider_id]} 已连接 · "
                f"支持参考图：{'是' if supports_reference else '否'}"
            )
        else:
            st.warning("该服务商尚未登录。请在“订阅与凭据”中完成 OAuth 登录或保存 API Key。")
        st.caption("模型列表和输入能力直接来自 pi 的 ImageModel 目录；第二阶段只允许支持 image 输入的模型。")
        return (
            PiGatewayImageProvider(
                client,
                provider_id=provider_id,
                model_id=str(selected_model.get("id")),
            ),
            configured and supports_reference,
            supports_reference,
        )


def _render_pi_account_manager(
    client: PiModelGatewayClient,
    providers: list[dict[str, Any]],
) -> None:
    account_rows = [
        item for item in providers if item.get("oauth") or int(item.get("imageModelCount") or 0) > 0
    ]
    labels = {
        f"{item.get('name')} · {item.get('id')}": item for item in account_rows
    }
    if not labels:
        st.info("Pi 模型目录中暂无可配置的账户或生图服务商。")
        return
    selected_label = st.selectbox("账户 / 服务商", list(labels.keys()), key="pi_account_provider")
    provider = labels[selected_label]
    provider_id = str(provider.get("id"))

    if provider.get("configured"):
        st.success(f"已连接：{provider.get('authSource') or provider.get('authType')}")
        if st.button("退出该账户", width="stretch", key=f"pi_logout_{provider_id}"):
            try:
                client.logout(provider_id)
            except Exception as exc:
                st.error(str(exc))
            else:
                st.session_state.pop("pi_oauth_session_id", None)
                st.rerun()
    else:
        st.caption("尚未配置凭据。OAuth 登录信息和 API Key 由本机 pi CredentialStore 保存。")

    if provider.get("oauth"):
        label = str(provider.get("oauthLabel") or "使用订阅 / OAuth 登录")
        if st.button(label, type="primary", width="stretch", key=f"pi_oauth_{provider_id}"):
            try:
                session = client.start_oauth(provider_id)
            except Exception as exc:
                st.error(str(exc))
            else:
                st.session_state["pi_oauth_session_id"] = session.get("id")
                st.rerun()

    if provider.get("apiKey"):
        with st.expander("使用 API Key", expanded=False):
            api_key = st.text_input(
                "API Key",
                type="password",
                key=f"pi_api_key_{provider_id}",
                help="凭据保存到 data/model_gateway/credentials.json；该目录已被 Git 忽略。",
            )
            if st.button(
                "保存 API Key",
                width="stretch",
                disabled=not api_key.strip(),
                key=f"pi_save_key_{provider_id}",
            ):
                try:
                    client.save_api_key(provider_id, api_key.strip())
                except Exception as exc:
                    st.error(str(exc))
                else:
                    st.rerun()

    session_id = str(st.session_state.get("pi_oauth_session_id") or "")
    if session_id:
        _render_oauth_session(client, session_id)

    if provider_id == "openai":
        st.info(
            "ChatGPT 订阅可以在这里完成 OAuth 配置，但 OpenAI 当前的订阅共享预览不支持 image generation。"
            "因此它不会出现在上方生图模型列表中；糖画生图可使用 OpenRouter 登录后的 GPT Image、Gemini、FLUX 等模型。"
        )


def _render_oauth_session(client: PiModelGatewayClient, session_id: str) -> None:
    try:
        session = client.oauth_status(session_id)
    except Exception as exc:
        st.error(str(exc))
        return

    for event in session.get("events") or []:
        event_type = event.get("type")
        if event_type == "auth_url":
            st.link_button("在浏览器中继续登录", str(event.get("url")), width="stretch")
            if event.get("instructions"):
                st.caption(str(event.get("instructions")))
        elif event_type == "device_code":
            st.code(str(event.get("userCode") or ""))
            st.link_button("打开验证页面", str(event.get("verificationUri")), width="stretch")
        elif event_type in {"info", "progress"}:
            st.caption(str(event.get("message") or ""))

    prompt = session.get("prompt") or {}
    if prompt:
        options = prompt.get("options") or []
        if prompt.get("type") == "select" and options:
            option_labels = {str(item.get("label")): str(item.get("id")) for item in options}
            selected = st.selectbox(str(prompt.get("message") or "请选择"), list(option_labels.keys()))
            response_value = option_labels[selected]
        else:
            response_value = st.text_input(
                str(prompt.get("message") or "登录信息"),
                type="password" if prompt.get("type") == "secret" else "default",
                placeholder=str(prompt.get("placeholder") or ""),
                key=f"pi_oauth_prompt_{session_id}",
            )
        if st.button("提交登录信息", disabled=not response_value, width="stretch"):
            client.oauth_respond(session_id, response_value)
            st.rerun()

    status = str(session.get("status") or "")
    if status == "complete":
        st.success("登录完成。")
        if st.button("刷新模型状态", width="stretch"):
            st.session_state.pop("pi_oauth_session_id", None)
            st.rerun()
    elif status == "error":
        st.error(str(session.get("error") or "登录失败"))
    else:
        st.caption("登录流程仍在进行。完成浏览器授权后点击下方按钮。")
        if st.button("刷新登录状态", width="stretch"):
            st.rerun()


def _render_compatible_provider(
    *,
    default_provider_id: str = "",
    default_model_id: str = "",
) -> tuple[Any | None, bool, bool]:
    compatible_specs = {
        key: value
        for key, value in PROVIDER_SPECS.items()
        if key not in {"siliconflow", "bananapro"}
    }
    labels = {provider_id: spec.label for provider_id, spec in compatible_specs.items()}
    provider_labels = list(labels.values())
    default_label = labels.get(default_provider_id, provider_labels[0])
    selected_label = st.selectbox(
        "兼容接口",
        provider_labels,
        index=provider_labels.index(default_label),
    )
    provider_id = next(key for key, value in labels.items() if value == selected_label)
    spec = compatible_specs[provider_id]
    model = st.text_input(
        "模型 ID",
        value=os.getenv("AI_SUGAR_MODEL", default_model_id or spec.default_model),
        key=f"ai_sugar_model_{provider_id}",
    )
    base_url = st.text_input(
        "API 地址",
        value=os.getenv("AI_SUGAR_BASE_URL", spec.default_base_url),
        key=f"ai_sugar_base_url_{provider_id}",
    )
    api_key = st.text_input("API Key", type="password", key=f"ai_sugar_api_key_{provider_id}")
    config = ProviderConfig(
        provider_id=provider_id,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )
    provider = create_image_provider(config)
    if st.button("测试兼容接口", width="stretch", key=f"test_{provider_id}"):
        ok, message = provider.test_connection()
        (st.success if ok else st.error)(message)
    st.caption("兼容接口必须同时支持 /images/generations 与 /images/edits，才能完成两阶段流程。")
    environment_key = os.getenv("AI_IMAGE_API_KEY") or (
        os.getenv("OPENAI_API_KEY") if provider_id == "openai" else ""
    )
    return provider, bool(api_key.strip() or environment_key), True


def _render_task_controls(
    service: SugarPaintingService,
    task: SugarPaintingTask | None,
) -> SugarPaintingTask | None:
    st.markdown("#### 新建生成任务")
    current_language = task.prompt_language if task else "zh"
    language_label = st.radio(
        "提示词语言",
        ["中文", "English"],
        index=1 if current_language == "en" else 0,
        horizontal=True,
        key="ai_sugar_prompt_language",
        help="切换后，样图提示词和线稿提示词会同时更新。",
    )
    prompt_language = "en" if language_label == "English" else "zh"
    if task is not None and prompt_language != task.prompt_language:
        task = service.set_prompt_language(task, prompt_language)
    object_name = st.text_input(
        "主体名称",
        value=task.object_name if task else "马",
        placeholder="例如：马、兔子、龙",
        help="第一轮建议只输入一个主体，不添加文字或复杂背景。",
    )
    if st.button("新建任务", type="primary", width="stretch", disabled=not object_name.strip()):
        try:
            task = service.create_task(object_name, prompt_language=prompt_language)
        except Exception as exc:
            st.error(str(exc))
        else:
            st.session_state["ai_sugar_task_id"] = task.task_id
            st.session_state["job_name"] = task.object_name
            st.rerun()

    if task is None:
        st.info("先建立任务，系统会将样图、线稿、提示词和模型记录关联在同一个任务中。")
        return None
    st.caption(f"当前任务：{task.task_id}")
    return task


def _render_sample_controls(
    service: SugarPaintingService,
    task: SugarPaintingTask,
    image_provider: Any | None,
    model_ready: bool,
    supports_reference: bool,
    options: ImageRequestOptions,
    reference_image: str,
) -> SugarPaintingTask:
    st.divider()
    st.markdown("#### 阶段一：糖画样图")
    _render_prompt_editor(service, task, stage="sample", image_provider=image_provider)
    if reference_image:
        st.caption(f"本次参考：{reference_image}")

    button_label = "重新生成样图" if task.sample_image else "生成糖画样图"
    reference_supported = not reference_image or supports_reference
    if not model_ready:
        st.info("请先在“模型配置”中填写并测试所选服务商的凭据。")
    if st.button(
        button_label,
        type="primary",
        width="stretch",
        disabled=not model_ready or not reference_supported,
    ):
        if image_provider is None:
            st.error("模型配置不完整。")
        else:
            try:
                with st.spinner("正在通过已连接模型生成糖画样图……"):
                    task = service.generate_sample(
                        task,
                        image_provider,
                        options,
                        reference_image=reference_image or None,
                    )
            except ImageProviderError as exc:
                _remember_region_blocked_model(image_provider, exc)
                st.error(str(exc))
            except Exception as exc:
                st.error(f"样图生成失败：{exc}")
            else:
                st.success("样图生成完成，请在右侧检查并确认。")
                st.rerun()

    if task.sample_image and not task.sample_confirmed:
        if st.button("确认使用这张样图", type="primary", width="stretch"):
            try:
                service.confirm_sample(task)
            except Exception as exc:
                st.error(str(exc))
            else:
                st.rerun()
    elif task.sample_confirmed:
        st.success("样图已确认。更换样图会清除当前线稿确认状态。")
    return task


def _render_prompt_editor(
    service: SugarPaintingService,
    task: SugarPaintingTask,
    *,
    stage: str,
    image_provider: Any | None,
) -> None:
    is_sample = stage == "sample"
    stage_label = "第一阶段" if is_sample else "第二阶段"
    positive = task.sample_prompt if is_sample else task.line_art_prompt
    stored_negative = (
        task.sample_negative_prompt if is_sample else task.line_art_negative_prompt
    )
    negative = (
        negative_prompt_for(stage, task.prompt_language)
        if stored_negative is None
        else stored_negative
    )
    fixed_subject_instruction = subject_instruction_for(
        stage,
        task.object_name,
        task.prompt_language,
    )
    negative_mode = str(
        getattr(image_provider, "negative_prompt_mode", "unsupported") or "unsupported"
    )
    language_label = "中文" if task.prompt_language == "zh" else "English"
    with st.expander(f"{stage_label}提示词设置", expanded=False):
        st.caption(
            f"当前编辑：{language_label}。临时应用只影响本任务；保存为项目默认后，"
            "后续新任务会使用该版本，并写入可提交到 GitHub 的 config 配置。"
        )
        st.text_input(
            "固定主体指令（自动生成，不保存到默认提示词）",
            value=fixed_subject_instruction,
            disabled=True,
            key=f"subject_instruction_{stage}_{task.task_id}_{task.prompt_language}",
        )
        st.caption("发送时，系统会把上面的固定主体指令作为第一行，与下面的提示词正文合并后一起提交给模型。")
        with st.form(f"prompt_editor_{stage}_{task.task_id}_{task.prompt_language}"):
            edited_positive = st.text_area(
                "提示词正文（可修改并保存为默认）",
                value=positive,
                height=260 if is_sample else 340,
                key=f"positive_prompt_{stage}_{task.task_id}_{task.prompt_language}",
            )
            edited_negative = st.text_area(
                "反向提示词（可留空）",
                value=negative,
                height=120,
                key=f"negative_prompt_{stage}_{task.task_id}_{task.prompt_language}",
            )
            if negative_mode == "native":
                st.caption("当前适配器会把反向提示词作为独立参数发送；具体效果仍取决于所选模型。")
            elif negative_mode == "prompt_suffix":
                st.caption("当前适配器没有独立反向参数，会把非空内容追加到主提示词中；留空则不追加。")
            else:
                st.caption("当前适配器不支持独立反向提示词，此内容不会发送；可以保持为空。")
            apply_col, default_col = st.columns(2)
            with apply_col:
                apply_current = st.form_submit_button(
                    "应用到当前任务",
                    width="stretch",
                )
            with default_col:
                save_default = st.form_submit_button(
                    "应用并保存为项目默认",
                    width="stretch",
                    type="primary",
                )
        if apply_current or save_default:
            try:
                service.set_stage_prompts(
                    task,
                    stage,
                    positive=edited_positive,
                    negative=edited_negative,
                )
                if save_default:
                    service.save_stage_prompt_defaults(
                        task,
                        stage,
                        positive=edited_positive,
                        negative=edited_negative,
                    )
            except Exception as exc:
                st.error(f"提示词保存失败：{exc}")
            else:
                if save_default:
                    st.success("已应用，并保存为项目默认提示词。")
                else:
                    st.success("已应用到当前任务，不会改变项目默认值。")


def _render_stage_two_task_input(
    service: SugarPaintingService,
    task: SugarPaintingTask | None,
) -> SugarPaintingTask | None:
    st.markdown("#### 第二阶段输入")
    if task is None:
        object_name = st.text_input(
            "参考图主体",
            value="马",
            key="stage2_object_name",
            help="用于建立测试记录和生成对应的中心线提示词。",
        )
        language_label = st.radio(
            "提示词语言",
            ["中文", "English"],
            horizontal=True,
            key="stage2_prompt_language",
        )
    else:
        object_name = task.object_name
        language_label = "English" if task.prompt_language == "en" else "中文"
        st.caption(f"当前任务：{task.object_name} · {task.task_id}")
        if st.button(
            "新建独立的第二阶段测试",
            width="stretch",
            key=f"stage2_new_task_{task.task_id}",
        ):
            service.clear_active_task()
            st.session_state.pop("ai_sugar_task_id", None)
            st.rerun()

    uploaded_sample = st.file_uploader(
        "上传糖画参考图",
        type=["png", "jpg", "jpeg", "webp", "bmp"],
        key=f"stage2_sample_upload_{task.task_id if task else 'new'}",
        help="这是第二阶段测试入口；上传后直接作为单中心线提取的输入。",
    )
    public_url = st.text_input(
        "已有公开图片 URL（可选）",
        value="",
        key=f"stage2_public_url_{task.task_id if task else 'new'}",
        placeholder="https://...",
        help="若留空，使用 Seedream 5 Pro 时会通过已配置图床自动生成 URL。",
    )
    if task is not None and task.sample_image and public_url.strip():
        if st.button(
            "将此 URL 绑定到当前参考图",
            width="stretch",
            key=f"stage2_bind_url_{task.task_id}",
        ):
            try:
                service.set_sample_public_url(task, public_url)
            except Exception as exc:
                st.error(str(exc))
            else:
                st.success("公开 URL 已保存。")
                st.rerun()
    if st.button(
        "载入参考图并进入第二阶段",
        type="primary",
        width="stretch",
        disabled=uploaded_sample is None or not object_name.strip(),
        key=f"stage2_import_sample_{task.task_id if task else 'new'}",
    ):
        try:
            if task is None:
                task = service.create_task(
                    object_name,
                    prompt_language="en" if language_label == "English" else "zh",
                )
            task = service.import_sample(task, uploaded_sample.getvalue(), uploaded_sample.name)
            if public_url.strip():
                task = service.set_sample_public_url(task, public_url)
            task = service.confirm_sample(task)
        except Exception as exc:
            st.error(f"参考图载入失败：{exc}")
        else:
            st.session_state["ai_sugar_task_id"] = task.task_id
            st.session_state["job_name"] = task.object_name
            st.success("参考图已载入，可以开始提取单中心线。")
            st.rerun()

    if task is None:
        st.info("可以直接上传本地糖画图开始第二阶段，不必先运行第一阶段。")
        return None
    if task.sample_image and not task.sample_confirmed:
        if st.button(
            "确认当前图片并进入第二阶段",
            type="primary",
            width="stretch",
            key=f"stage2_confirm_sample_{task.task_id}",
        ):
            service.confirm_sample(task)
            st.rerun()
    elif task.sample_confirmed:
        if task.sample_public_url:
            st.success("参考图已确认，公开 URL 已准备。")
        else:
            st.success("参考图已确认；需要公网 URL 时会在提取前自动上传。")
    return task


def _render_line_art_controls(
    service: SugarPaintingService,
    task: SugarPaintingTask,
    image_provider: Any | None,
    model_ready: bool,
    supports_reference: bool,
    options: ImageRequestOptions,
    auto_retry_once: bool,
    *,
    image_host: Any | None = None,
) -> SugarPaintingTask:
    st.divider()
    st.markdown("#### 阶段二：黑白线稿")
    _render_prompt_editor(
        service,
        task,
        stage="line_art",
        image_provider=image_provider,
    )

    if getattr(image_provider, "provider_id", "") == "bananapro":
        _render_bananapro_recovery(service, task, image_provider, options)

    with st.expander("测试入口：上传黑白线稿", expanded=False):
        st.caption("跳过 AI 线稿提取，直接上传本地线稿进行质量检查和转曲线测试。")
        uploaded_line_art = st.file_uploader(
            "选择黑白线稿",
            type=["png", "jpg", "jpeg", "webp", "bmp"],
            key=f"ai_line_art_upload_{task.task_id}",
        )
        if st.button(
            "使用上传图片作为线稿",
            width="stretch",
            disabled=uploaded_line_art is None,
            key=f"ai_import_line_art_{task.task_id}",
        ):
            try:
                task = service.import_line_art(
                    task,
                    uploaded_line_art.getvalue(),
                    uploaded_line_art.name,
                )
            except Exception as exc:
                st.error(f"线稿上传失败：{exc}")
            else:
                st.success("线稿已上传并完成质量检查。")
                st.rerun()

    if not supports_reference:
        st.warning("所选模型不支持图片输入，无法根据已确认样图提取线稿；请更换支持参考图的模型。")
    elif not model_ready:
        st.info("请先连接所选模型服务商。")
    button_label = "重新提取线稿" if task.line_art_image else "从确认样图提取线稿"
    if st.button(
        button_label,
        type="primary",
        width="stretch",
        disabled=not model_ready or not supports_reference,
    ):
        if image_provider is None:
            st.error("模型配置不完整。")
        else:
            try:
                with st.spinner("正在通过已连接模型提取黑白线稿……"):
                    if bool(
                        getattr(image_provider, "requires_public_reference_image", False)
                    ) and (
                        not task.sample_public_url
                        or (
                            task.sample_public_url_expires_at > 0
                            and task.sample_public_url_expires_at <= int(time.time()) + 300
                        )
                    ):
                        if image_host is None:
                            raise ImageProviderError(
                                "当前模型需要公开图片 URL。请在第二阶段模型配置中填写 ImgBB API Key，"
                                "或在上传参考图时填写已有公开 URL。"
                            )
                        task = service.publish_sample(task, image_host)
                    task = service.extract_line_art(
                        task,
                        image_provider,
                        options,
                        auto_retry_once=auto_retry_once,
                    )
            except ImageProviderError as exc:
                _remember_region_blocked_model(image_provider, exc)
                st.error(str(exc))
            except Exception as exc:
                st.error(f"线稿提取失败：{exc}")
            else:
                st.rerun()

    quality_ok = bool(task.line_art_quality.get("accepted"))
    if task.line_art_image and not task.line_art_confirmed:
        add_to_library = st.checkbox(
            "同时加入已批准样本库",
            value=False,
            disabled=not quality_ok,
            help="默认不加入，且样本库不会自动参与后续生成。",
        )
        allow_quality_override = False
        if not quality_ok:
            st.warning(
                "当前线稿未通过自动质量检查。人工放行只用于转曲线测试，"
                "不会将该图像加入已批准样本库。"
            )
            allow_quality_override = st.checkbox(
                "我已人工检查该线稿，仍要进入曲线测试",
                value=False,
                key=f"ai_quality_override_{task.task_id}_{len(task.line_art_attempts)}",
                help="可能产生断线、过密路径或异常曲线；请勿直接发送给机械臂。",
            )
        can_continue = quality_ok or allow_quality_override
        confirm_label = (
            "人工放行并进入曲线测试"
            if allow_quality_override and not quality_ok
            else "确认线稿并交给曲线模块"
        )
        if st.button(confirm_label, type="primary", width="stretch", disabled=not can_continue):
            try:
                task = service.confirm_line_art(
                    task,
                    add_to_sample_library=add_to_library if quality_ok else False,
                    allow_quality_override=allow_quality_override,
                )
            except Exception as exc:
                st.error(str(exc))
            else:
                st.session_state["latest_image_path"] = task.line_art_image
                st.session_state["vector_image_path"] = task.line_art_image
                st.session_state["vectorizer_method_label"] = "仅提取线条骨架"
                st.session_state["job_name"] = task.object_name
                st.session_state["pending_navigation"] = "图像转曲线"
                st.rerun()
    elif task.line_art_confirmed:
        if task.line_art_quality_overridden:
            st.warning("该线稿由人工放行，已设为“图像转曲线”的测试输入；请先检查曲线再进行机械臂操作。")
        else:
            st.success("线稿已确认，并已设为“图像转曲线”的输入。")
    return task


def _render_bananapro_recovery(
    service: SugarPaintingService,
    task: SugarPaintingTask,
    image_provider: Any,
    options: ImageRequestOptions,
) -> None:
    with st.expander("找回刷新前已扣费的结果", expanded=False):
        st.caption("只读取 BananaPro 最近任务，不会重新生成，也不会再次扣费。")
        if st.button(
            "查询最近的 BananaPro 图片任务",
            width="stretch",
            key=f"query_bananapro_tasks_{task.task_id}",
        ):
            try:
                recent = image_provider.list_recent_image_tasks(20)
            except Exception as exc:
                st.error(f"查询失败：{exc}")
            else:
                st.session_state[f"bananapro_recent_tasks_{task.task_id}"] = recent
                st.rerun()

        recent_tasks = st.session_state.get(f"bananapro_recent_tasks_{task.task_id}") or []
        completed = [item for item in recent_tasks if item.get("status") == "completed"]
        if not completed:
            st.caption("尚未读取到可恢复的已完成任务。")
            return
        labels = {
            (
                f"{item.get('created_at', '未知时间')} · {item.get('model', '未知模型')} · "
                f"{item.get('credits_used', '—')} credits · {item.get('task_id')}"
            ): str(item.get("task_id") or "")
            for item in completed
        }
        selected = st.selectbox(
            "选择要恢复的远程结果",
            list(labels),
            key=f"recover_bananapro_task_{task.task_id}",
        )
        if st.button(
            "下载并恢复到当前任务",
            type="primary",
            width="stretch",
            key=f"recover_bananapro_result_{task.task_id}",
        ):
            try:
                service.recover_line_art(task, image_provider, labels[selected], options)
            except Exception as exc:
                st.error(f"恢复失败：{exc}")
            else:
                st.success("结果已恢复到当前任务，不会再次扣费。")
                st.rerun()


def _remember_region_blocked_model(image_provider: Any | None, error: Exception) -> None:
    message = str(error).lower()
    if "not available in your region" not in message and "当前地区" not in message:
        return
    model_id = str(getattr(image_provider, "model_id", "") or "")
    if not model_id:
        return
    blocked = set(st.session_state.get("pi_region_blocked_models") or [])
    blocked.add(model_id)
    st.session_state["pi_region_blocked_models"] = sorted(blocked)
    st.warning(
        "该模型已从本次会话的模型列表隐藏。请重新打开模型配置，改用 "
        "Qwen Image 或 Seedream 等支持参考图的模型。"
    )


def _render_stage_one_preview(task: SugarPaintingTask | None) -> None:
    st.markdown("#### 第一阶段结果")
    if task and task.sample_image and Path(task.sample_image).is_file():
        st.image(task.sample_image, width="stretch")
        if task.sample_confirmed:
            st.success("糖画样图已确认，可以切换到第二阶段。")
        else:
            st.caption("等待确认")
    else:
        st.info("生成后的糖画样图会显示在这里。")


def _render_stage_two_preview(task: SugarPaintingTask | None) -> None:
    st.markdown("#### 第二阶段工作区")
    if task is None:
        st.info("上传糖画参考图后，这里会同时显示输入图和单中心线结果。")
        return
    input_col, output_col = st.columns(2, gap="medium")
    with input_col:
        st.markdown("**输入 · 糖画参考图**")
        if task.sample_image and Path(task.sample_image).is_file():
            st.image(task.sample_image, width="stretch")
            st.caption("已确认" if task.sample_confirmed else "等待确认")
        else:
            st.info("尚未载入参考图")
    with output_col:
        st.markdown("**输出 · 单中心线稿**")
        if task.line_art_image and Path(task.line_art_image).is_file():
            st.image(task.line_art_image, width="stretch")
            st.caption("已确认" if task.line_art_confirmed else "等待确认")
        else:
            st.info("尚未提取线稿")
    if task.line_art_quality:
        _render_quality(task.line_art_quality)


def _render_previews(task: SugarPaintingTask | None) -> None:
    if task is None:
        st.info("建立任务后，样图和线稿会在这里并排展示。")
        return

    st.markdown("#### 生成结果")
    sample_col, line_col = st.columns(2)
    with sample_col:
        st.markdown("**糖画样图**")
        if task.sample_image and Path(task.sample_image).is_file():
            st.image(task.sample_image, width="stretch")
            st.caption("已确认" if task.sample_confirmed else "等待确认")
        else:
            st.info("尚未生成样图")
    with line_col:
        st.markdown("**黑白线稿**")
        if task.line_art_image and Path(task.line_art_image).is_file():
            st.image(task.line_art_image, width="stretch")
            st.caption("已确认" if task.line_art_confirmed else "等待确认")
        else:
            st.info("确认样图后才能提取线稿")

    if task.line_art_quality:
        _render_quality(task.line_art_quality)

    with st.expander("任务记录", expanded=False):
        rows = _task_attempt_rows(task)
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        task_file = Path(task.sample_image).parent / "task.json" if task.sample_image else task.task_id
        st.caption(f"任务文件：{task_file}")


def _task_attempt_rows(task: SugarPaintingTask) -> list[dict]:
    """Build Arrow-safe rows by keeping each column on one stable value type."""
    rows: list[dict] = []
    for stage, attempts in (("样图", task.sample_attempts), ("线稿", task.line_art_attempts)):
        for item in attempts:
            quality = item.get("quality") or {}
            raw_score = quality.get("score")
            score = int(raw_score) if isinstance(raw_score, (int, float)) else None
            rows.append(
                {
                    "阶段": stage,
                    "尝试": item.get("attempt"),
                    "服务商": item.get("providerId"),
                    "模型": item.get("modelId"),
                    "质量分": score,
                    "时间": item.get("createdAt"),
                }
            )
    return rows


def _render_quality(report: dict) -> None:
    score = int(report.get("score", 0))
    accepted = bool(report.get("accepted"))
    st.markdown("#### 线稿可绘制性检查")
    metric_cols = st.columns(4)
    metrics = report.get("metrics") or {}
    metric_cols[0].metric("质量分", f"{score}/100")
    metric_cols[1].metric("有效连通区", metrics.get("component_count", "—"))
    metric_cols[2].metric("碎小噪声", metrics.get("small_component_count", "—"))
    metric_cols[3].metric("填充块", metrics.get("large_filled_component_count", "—"))
    reasons = "；".join(str(item) for item in report.get("reasons", []))
    if accepted:
        st.success(reasons or "已通过确定性质量检查。")
    else:
        st.error(reasons or "未通过确定性质量检查。")


def _load_current_task(service: SugarPaintingService) -> SugarPaintingTask | None:
    task_id = st.session_state.get("ai_sugar_task_id", "")
    if not task_id:
        task = service.load_active_task()
        if task is not None:
            st.session_state["ai_sugar_task_id"] = task.task_id
        return task
    try:
        return service.load(task_id)
    except Exception:
        st.session_state.pop("ai_sugar_task_id", None)
        return None
