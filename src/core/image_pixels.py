"""Consistent white-background interpretation for transparent source images."""
import numpy as np
from PIL import Image


def white_background(image: Image.Image) -> Image.Image:
    rgba = image.convert('RGBA')
    background = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
    return Image.alpha_composite(background, rgba).convert('RGB')


def white_background_array(image: np.ndarray) -> np.ndarray:
    if image is None or image.size == 0 or image.ndim != 3 or image.shape[2] != 4:
        return image
    rgba=image.astype(np.float32)
    alpha=rgba[:,:,3:4]/255.0
    return np.rint(rgba[:,:,:3]*alpha+255.0*(1.0-alpha)).clip(0,255).astype(np.uint8)
