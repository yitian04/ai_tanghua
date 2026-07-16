from __future__ import annotations

from apps.gui.views.design_page import render_image_generation_page


def render(config: dict, root_dir: str) -> None:
    render_image_generation_page(config, root_dir, title="AI生成图片")
