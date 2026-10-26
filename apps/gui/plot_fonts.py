from __future__ import annotations

from functools import lru_cache

import matplotlib as mpl
from matplotlib import font_manager


CHINESE_SANS_SERIF_FALLBACKS = [
    "Microsoft YaHei",
    "Source Han Sans SC",
    "Noto Sans CJK SC",
    "PingFang SC",
    "Hiragino Sans GB",
    "SimHei",
    "WenQuanYi Zen Hei",
    "Arial Unicode MS",
    "DejaVu Sans",
]


@lru_cache(maxsize=1)
def configure_matplotlib_chinese_font() -> str:
    """Select an installed CJK font and configure a portable fallback chain."""
    installed = {font.name for font in font_manager.fontManager.ttflist}
    selected = next(
        (name for name in CHINESE_SANS_SERIF_FALLBACKS if name in installed),
        "DejaVu Sans",
    )
    ordered = [selected, *[name for name in CHINESE_SANS_SERIF_FALLBACKS if name != selected]]
    mpl.rcParams["font.family"] = "sans-serif"
    mpl.rcParams["font.sans-serif"] = ordered
    mpl.rcParams["axes.unicode_minus"] = False
    return selected
