"""Shop creation data and shared, configuration-free image generation."""
from pathlib import Path
import hashlib
import json
import math
import random
from copy import deepcopy

from src.core.models import Curve2D, CurveList
from src.core.preferences import PreferenceStore
from src.pipeline.image_generation.project_defaults import ProjectDefaultsStore
from src.pipeline.image_generation.local_credentials import BananaProCredentialStore, SiliconFlowCredentialStore
from src.pipeline.image_generation.providers import ProviderConfig, ImageRequestOptions, create_image_provider

WEATHER = ['晴天', '彩虹', '枝叶', '雪花', '花朵', '雨天', '阴天']
WEATHER_MESSAGES = ['阳光正好，愿今天暖暖的。', '雨后有彩虹，好事正在路上。', '让心愿像枝叶一样慢慢生长。', '把冬日的安静收藏进小店。', '今天也有小小的花为你开放。', '听一场雨，让心情慢下来。', '云朵会陪你度过柔软的一天。']


def catalog(root):
    return json.loads((Path(__file__).resolve().parents[2]/'resources/shop_styles/catalog.json').read_text(encoding='utf-8'))


def inspiration(styles, style_id, previous='', rng=None):
    style = next(s for s in styles if s['id'] == style_id)
    choices = [p for p in style['themes'] if p != previous]
    return (rng or random.SystemRandom()).choice(choices)


def drawing_curves(strokes, width=800, height=456):
    if len(strokes) > 3000:
        raise ValueError('笔画过多，请分次绘制。')
    curves = []
    for stroke in strokes:
        if len(stroke) < 2:
            continue
        if len(stroke) > 30000:
            raise ValueError('单笔采样点过多。')
        points = []
        for p in stroke:
            if len(p) != 2 or any(not isinstance(v, (int,float)) or not math.isfinite(v) for v in p):
                raise ValueError('手绘坐标无效。')
            if not (0 <= p[0] <= width-1 and 0 <= p[1] <= height-1):
                raise ValueError('手绘坐标超出画布。')
            if not points or p != points[-1]:
                points.append(list(p))
        if len(points) >= 2:
            curves.append(Curve2D(points, curve_id=len(curves)))
    if not curves:
        raise ValueError('请先在橱窗中画至少一笔。')
    return CurveList(curves, 'image_px', {'source':'freehand', 'canvas_size':[width,height], 'timing_recorded':False})


def drawing_signature(strokes):
    return hashlib.sha256(json.dumps(strokes, separators=(',',':')).encode()).hexdigest()


def shared_image_provider(root, session=None):
    """Use the same saved sample-stage selection and credentials as AI image UI."""
    session = session or {}
    runtime=session.get('shared_sample_image_runtime')
    if runtime:
        return deepcopy(runtime[0]),deepcopy(runtime[1])
    selection = ProjectDefaultsStore(root).stage('sample')
    chosen = session.get('model_source_stage_1', '') or PreferenceStore(root).current('ai').get('model_source_stage_1', '')
    labels = {'硅基流动（中国大陆 API）':'siliconflow', 'BananaPro（多模型 API）':'bananapro',
              'Pi 模型中心（订阅 / OAuth / API Key）':'pi', '自定义兼容 API':'compatible',
              '本地 ComfyUI':'comfyui'}
    # Widget values are display labels. A saved id is already canonical.
    # An empty or unknown value keeps the saved sample-stage default.
    source = labels.get(chosen, chosen if chosen in set(labels.values()) else selection['source'])
    if source == "comfyui":
        from src.pipeline.image_generation.local_comfy import LocalImageProvider, LocalSettings
        return LocalImageProvider(LocalSettings.load(root)), ImageRequestOptions(size="1536x864")
    provider_id = source if source in ('bananapro','siliconflow') else selection['provider_id']
    model = selection['model_id']
    if provider_id == 'bananapro':
        saved = BananaProCredentialStore(root).load()
        model = session.get('bananapro_generation_model') or model
        if model == '自定义模型 ID…':model=session.get('bananapro_generation_model_custom') or selection['model_id']
        model = str(model).rsplit(' · ',1)[-1]
        config = ProviderConfig(provider_id, model, session.get('bananapro_api_key_stage_1') or saved.api_key,
                                session.get('bananapro_base_url_stage_1') or saved.base_url, edit_model=model, timeout_s=300)
        options = ImageRequestOptions(extra_body={'resolution':saved.resolution, 'aspect_ratio':'16:9', 'generation_mode':saved.generation_mode})
    elif provider_id == 'siliconflow':
        saved = SiliconFlowCredentialStore(root).load()
        model = session.get('siliconflow_generation_model') or model
        known={'Qwen Image（推荐）':'Qwen/Qwen-Image','Z-Image':'Tongyi-MAI/Z-Image','Kolors':'Kwai-Kolors/Kolors'}
        model = known.get(model,model)
        config = ProviderConfig(provider_id, model, session.get('siliconflow_api_key_stage_1') or saved.api_key,
                                session.get('siliconflow_base_url_stage_1') or saved.base_url, edit_model=saved.edit_model, timeout_s=300)
        options = ImageRequestOptions(size='1024x1024')
    elif selection['source'] == 'pi':
        from src.pipeline.image_generation.pi_gateway import PiModelGatewayClient, PiGatewayImageProvider
        return PiGatewayImageProvider(PiModelGatewayClient(root), provider_id=provider_id, model_id=model), ImageRequestOptions()
    else:
        config = ProviderConfig(provider_id, session.get('ai_sugar_model_'+provider_id) or model,
                                session.get('ai_sugar_api_key_'+provider_id,''),
                                session.get('ai_sugar_base_url_'+provider_id,''), timeout_s=300)
        options = ImageRequestOptions(size='1536x1024')
    return create_image_provider(config), options


def image_prompt(style, theme):
    language=style.get('line_language','Rounded broad contours and smooth connected curves.')
    return ('Create a pure-white 16:9 landscape illustration. '
            'Use uniform black monoline strokes with round caps and joins. '
            'Minimal lines are mandatory for every style: 3 to 5 large elements, only essential contours, '
            'long uninterrupted curves, roughly 8 to 20 main strokes. '
            'Each connected contour should be drawn with a continuous stroke; do not force unrelated objects into one path. '
            'No artificial linking loops, ribbon outlines or retracing. Line width is approximately 0.4 percent of image height. '
            'No variable stroke width, broken dashes, short fragments, hatching, fur, leaf veins, '
            'shading, texture, filled black areas, doubled outlines or text. '
            'No frame, border, building, shopfront, door or window. '
            f'Line language: {language} Theme: {theme}. '
            'If a reference image is attached, use only its bold uniform line quality and simplicity. '
            'Do not copy its animals, objects, trees or composition. The written theme alone determines content.')


def sdxl_line_prompt(style, theme):
    language = style.get('line_language', 'Rounded smooth contours.')
    return (f'{theme}. Minimal black ink line drawing, simple isolated clipart, plain white background. '
            f'Thin even outline, long smooth strokes, spacious layout. {language}')


SDXL_LINE_NEGATIVE = (
    'photograph, color, gray, gradients, shadow, shading, engraving, hatching, '
    'texture, thick strokes, filled shapes, double outlines, tiny details, text, border'
)


def generate_reference(root, style, theme, output, session=None):
    provider, options = shared_image_provider(root, session)
    prompt = image_prompt(style, theme)
    # A single production reference prevents colored/dense artist examples and montage layouts leaking in.
    reference = Path(__file__).resolve().parents[2]/'resources/shop_styles/line_density_reference.png'
    options=deepcopy(options)
    options.size='1536x864'
    options.extra_body={**options.extra_body,'aspect_ratio':'16:9'}
    if getattr(provider,'provider_id','') == 'bananapro':
        provider.edit_model=provider.generation_model
    runtime=(session or {}).get('shared_sample_image_runtime')
    if (runtime and not runtime[2]) or getattr(provider,'provider_id','')=='siliconflow' or getattr(provider,'requires_public_reference_image',False):
        # The current generation model remains authoritative when it has no image input.
        prompt += ' No reference image input was supplied. Generate from the written theme and line-language description only.'
        result=provider.generate(prompt,output,options)
    else:
        result = provider.edit(prompt, reference, output, options)
    from PIL import Image
    with Image.open(result.output_path) as image:
        width,height=image.size
    if abs(width/height-16/9)/(16/9)>.015:
        raise ValueError(f'模型返回 {width}×{height}，未满足16:9；本次不作为有效参考图。原始输出保留，不拉伸。')
    if width*9!=height*16:
        # Some providers round native sizes to model blocks (e.g. 1376×768).
        # Add only a narrow white margin; preserve all original pixels and retain the native file.
        import shutil
        native=Path(result.output_path)
        shutil.copy2(native,native.with_name(native.stem+'.native'+native.suffix))
        k=math.ceil(max(width/16,height/9))
        with Image.open(native) as image:
            canvas=Image.new('RGB',(16*k,9*k),'white')
            canvas.paste(image.convert('RGB'),((16*k-width)//2,(9*k-height)//2));canvas.save(native)
        result.usage.update(native_dimensions=[width,height],canvas_dimensions=[16*k,9*k],ratio_adjustment='white_padding_only')
    return result, prompt
