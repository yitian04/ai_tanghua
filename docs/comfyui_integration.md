# ComfyUI integration

This project integrates ComfyUI only as an image-generation provider for the design-input stage.
The output contract is a normal image file under `data/images/`; downstream vectorization,
trajectory planning, and UR5 execution do not need to know whether the image came from upload
or AI generation.

## ComfyUI setup

1. Start ComfyUI as a local server. Default address:

```powershell
python main.py --disable-auto-launch
```

ComfyUI usually listens at:

```text
http://127.0.0.1:8188
```

2. Build a sugar-painting-friendly workflow in the ComfyUI UI.

Recommended prompt style:

```text
simple black line art, single subject, clean white background,
vector-like outline, smooth continuous strokes, no shading,
no gray, no texture, no background, suitable for sugar painting
```

Recommended negative prompt:

```text
photo, realistic, shadow, gradient, color, complex background,
text, watermark, small details, noisy lines, filled texture
```

3. Export API workflow, not the normal editable workflow:

```text
File -> Export Workflow (API)
```

Save it for example as:

```text
workflows/comfyui/tanghua_line_art_api.json
```

The API workflow is the JSON object accepted by ComfyUI `POST /prompt`.

## Python usage

```python
from pathlib import Path
from src.pipeline.image_generation import ComfyUIClient, load_workflow_json

workflow = load_workflow_json("workflows/comfyui/tanghua_line_art_api.json")
client = ComfyUIClient("http://127.0.0.1:8188")
output = client.queue_and_download_first_image(
    workflow,
    Path("data/images/comfyui_test.png"),
    timeout_s=300,
)
print(output)
```

The client uses:

- `POST /prompt` to submit the API workflow
- `GET /history/{prompt_id}` to wait for completion
- `GET /view?filename=...&subfolder=...&type=...` to download the generated image

## Next integration step

Add workflow patching so the project can replace these node inputs before submission:

- positive prompt text
- negative prompt text
- seed
- width / height
- SaveImage filename prefix
