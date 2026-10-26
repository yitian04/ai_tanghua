from __future__ import annotations

import io
import unittest
import warnings

import matplotlib.pyplot as plt

from apps.gui.plot_fonts import (
    CHINESE_SANS_SERIF_FALLBACKS,
    configure_matplotlib_chinese_font,
)


class PlotFontTests(unittest.TestCase):
    def test_chinese_plot_labels_render_without_missing_glyph_warning(self) -> None:
        selected = configure_matplotlib_chinese_font()
        self.assertIn(selected, CHINESE_SANS_SERIF_FALLBACKS)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fig, ax = plt.subplots()
            ax.set_title("曲线预览")
            ax.set_xlabel("图像 X 坐标 / 像素")
            ax.set_ylabel("图像 Y 坐标 / 像素")
            fig.savefig(io.BytesIO(), format="png")
            plt.close(fig)

        glyph_warnings = [item for item in caught if "Glyph" in str(item.message)]
        self.assertEqual(glyph_warnings, [])


if __name__ == "__main__":
    unittest.main()
