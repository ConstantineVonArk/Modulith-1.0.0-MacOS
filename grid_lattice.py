"""Continuous, camera-anchored isometric construction lattice.

Unlike the earlier preview implementation, the grid doesn't quantise its
scale to an integer. No scene geometry or export rendering depends on this.
"""
import math
from PIL import ImageDraw


def paint_scene_grid(image, left, top, zoom):
    """Draw the 2:1 isometric lattice aligned to the rendered scene origin."""
    width, height = image.size
    zoom = max(0.001, float(zoom))
    drawer = ImageDraw.Draw(image)
    # A fixed world-space 12-unit intercept interval; scaling continuously
    # avoids the 24-pixel lattice snapping between integer zoom levels.
    period = 12.0 * zoom
    stroke = max(1, round(zoom))
    for slope in (-0.5, 0.5):
        offset = top - slope * left
        start = -abs(slope) * width - stroke
        end = height + abs(slope) * width + stroke
        kmin = math.floor((start - offset) / period) - 1
        kmax = math.ceil((end - offset) / period) + 1
        for k in range(kmin, kmax + 1):
            intercept = offset + k * period
            drawer.line([(0, round(intercept)),
                         (width, round(intercept + slope * width))],
                        fill='#686d71', width=stroke)
