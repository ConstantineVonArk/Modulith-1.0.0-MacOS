"""Exact, viewport-only nearest-neighbour sampling of a Pillow image.

The integer coordinate maps are themselves resized by Pillow NEAREST,
so pixel ties and rounding match Pillow's full-frame image.resize exactly.
NumPy is optional: callers must keep a legacy fallback when absent.
"""
from functools import lru_cache
from PIL import Image
try:
    import numpy as np
except ImportError:
    np = None


@lru_cache(maxsize=24)
def _mapping(source_len, target_len):
    if np is None:
        raise RuntimeError('NumPy is not installed')
    reference = Image.new('I', (source_len, 1))
    reference.putdata(range(source_len))
    scaled = reference.resize((target_len, 1), Image.Resampling.NEAREST)
    result = np.asarray(scaled, dtype=np.intp)[0].copy()
    result.flags.writeable = False
    return result


def visible_box(size, canvas_size, left, top):
    sw, sh = size
    cw, ch = canvas_size
    x0 = max(0, -left)
    y0 = max(0, -top)
    x1 = min(sw, cw-left)
    y1 = min(sh, ch-top)
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


# Retain arrays for the *current* native scene only. Repeated wheel events
# sample different rectangles from the same source; converting it to NumPy
# on every event was an avoidable full-image copy.
_last_native_arrays = None


def _native_arrays(source, masks):
    global _last_native_arrays
    if (_last_native_arrays is not None
            and _last_native_arrays[0] is source
            and _last_native_arrays[1] is masks[0]
            and _last_native_arrays[2] is masks[1]):
        return _last_native_arrays[3:]
    rgb = np.asarray(source if source.mode == 'RGB' else source.convert('RGB'))
    obj = np.asarray(masks[0])
    shadow = np.asarray(masks[1]) if masks[1] is not None else None
    _last_native_arrays = (source, masks[0], masks[1], rgb, obj, shadow)
    return rgb, obj, shadow


def sample(source, masks, scaled_size, box):
    """Return RGB, object mask, shadow mask for the visible *scaled* rectangle."""
    if np is None:
        raise RuntimeError('NumPy is not installed')
    x0, y0, x1, y1 = box
    dw, dh = scaled_size
    xs = _mapping(source.width, dw)[x0:x1]
    ys = _mapping(source.height, dh)[y0:y1]
    sel = np.ix_(ys, xs)
    native_rgb, native_obj, native_shadow = _native_arrays(source, masks)
    rgb = Image.fromarray(np.ascontiguousarray(native_rgb[sel]))
    object_mask = Image.fromarray(np.ascontiguousarray(native_obj[sel]))
    shadow_mask = (Image.fromarray(np.ascontiguousarray(native_shadow[sel]))
                   if native_shadow is not None else None)
    return rgb, object_mask, shadow_mask
