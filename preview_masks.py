"""Reusable native-resolution alpha masks for SC3K's pixel-art scene.

Nearest-neighbour scaling commutes with exact per-pixel classification.
Making masks once at source resolution avoids repeated RGB difference scans
on much larger scaled images during zoom and camera movement.
"""
from PIL import Image, ImageChops


def native_masks(image, background, shadow_colour, shadows):
    source = image.convert('RGB')
    nonbg = ImageChops.difference(source, Image.new('RGB', source.size, background)).convert('L')
    nonbg = nonbg.point(lambda v: 255 if v else 0)
    shadow_mask = None
    if shadows:
        d = ImageChops.difference(source, Image.new('RGB', source.size, shadow_colour)).convert('L')
        shadow_mask = d.point(lambda v: 255 if v == 0 else 0)
        nonbg = ImageChops.subtract(nonbg, shadow_mask)
    return nonbg, shadow_mask


def scaled_masks(masks, size):
    nonbg, shadow_mask = masks
    if nonbg.size == size:
        return nonbg, shadow_mask
    return (nonbg.resize(size, Image.Resampling.NEAREST),
            shadow_mask.resize(size, Image.Resampling.NEAREST) if shadow_mask is not None else None)
