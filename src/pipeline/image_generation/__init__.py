from __future__ import annotations

from src.pipeline.image_generation.comfyui_client import (
    ComfyUIClient,
    ComfyUIError,
    ComfyUIImageRef,
    load_workflow_json,
)

__all__ = [
    "ComfyUIClient",
    "ComfyUIError",
    "ComfyUIImageRef",
    "load_workflow_json",
]

from src.pipeline.image_generation.siliconflow_image_client import (
    SiliconFlowImageClient,
    SiliconFlowImageError,
    SiliconFlowImageRequest,
)
from src.pipeline.image_generation.quality import (
    ImageQualityReport,
    build_retry_prompt,
    evaluate_traceable_line_image,
)
from src.pipeline.image_generation.providers import (
    PROVIDER_SPECS,
    ImageCallResult,
    ImageProviderError,
    ImageRequestOptions,
    ProviderConfig,
    ProviderSpec,
    SiliconFlowImagesProvider,
    UnsupportedImageCapability,
    create_image_provider,
)
from src.pipeline.image_generation.sugar_painting import (
    LINE_ART_PROMPT_TEMPLATE,
    SAMPLE_PROMPT_TEMPLATE,
    SugarPaintingService,
    SugarPaintingTask,
    build_reference_sample_prompt,
    negative_prompt_for,
    subject_instruction_for,
)
from src.pipeline.image_generation.pi_gateway import (
    PiGatewayError,
    PiGatewayImageProvider,
    PiModelGatewayClient,
)
from src.pipeline.image_generation.local_credentials import (
    BananaProCredentialStore,
    BananaProSavedConfig,
    PublicImageHostCredentialStore,
    PublicImageHostSavedConfig,
    SiliconFlowCredentialStore,
    SiliconFlowSavedConfig,
)
from src.pipeline.image_generation.banana_pro import BananaProImagesProvider
from src.pipeline.image_generation.public_image_host import (
    ImgBBImageHost,
    PublicImageHostError,
)
from src.pipeline.image_generation.project_defaults import ProjectDefaultsStore

__all__.extend([
    "SiliconFlowImageClient",
    "SiliconFlowImageError",
    "SiliconFlowImageRequest",
    "ImageQualityReport",
    "build_retry_prompt",
    "evaluate_traceable_line_image",
    "PROVIDER_SPECS",
    "ImageCallResult",
    "ImageProviderError",
    "ImageRequestOptions",
    "ProviderConfig",
    "ProviderSpec",
    "SiliconFlowImagesProvider",
    "UnsupportedImageCapability",
    "create_image_provider",
    "LINE_ART_PROMPT_TEMPLATE",
    "SAMPLE_PROMPT_TEMPLATE",
    "SugarPaintingService",
    "SugarPaintingTask",
    "build_reference_sample_prompt",
    "negative_prompt_for",
    "subject_instruction_for",
    "PiGatewayError",
    "PiGatewayImageProvider",
    "PiModelGatewayClient",
    "BananaProImagesProvider",
    "BananaProCredentialStore",
    "BananaProSavedConfig",
    "ImgBBImageHost",
    "PublicImageHostError",
    "PublicImageHostCredentialStore",
    "PublicImageHostSavedConfig",
    "SiliconFlowCredentialStore",
    "SiliconFlowSavedConfig",
    "ProjectDefaultsStore",
])
