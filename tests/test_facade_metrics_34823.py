"""Small bounded cache for camera-independent facade statistics.

The renderer asks for the same alpha envelope and dominant wall colour at
many camera angles.  The source image is treated as immutable: on edit the
facade builder installs a new PIL Image object. Keep a strong reference to
prevent reuse of its id and bound the cache so old projects are released.
"""
from collections import Counter, OrderedDict
from statistics import median
import threading

_MAX=12
_cache=OrderedDict()
_lock=threading.Lock()


def _memo(image, operation, compute):
    key=(id(image),operation)
    with _lock:
        entry=_cache.get(key)
        if entry is not None and entry[0] is image:
            _cache.move_to_end(key)
            return entry[1]
    result=compute()
    with _lock:
        _cache[key]=(image,result)
        _cache.move_to_end(key)
        while len(_cache)>_MAX:
            _cache.popitem(last=False)
    return result


def dominant_opaque_colour(image, mirror=False):
    """Pixel-exact old Counter.most_common(1) sampling, including mirrored 270°."""
    def calculate():
        rgba=image if image.mode=='RGBA' else image.convert('RGBA')
        pixels=rgba.load()
        sample=Counter()
        for y in range(0,rgba.height,2):
            for x in range(0,rgba.width,2):
                colour=pixels[rgba.width-1-x if mirror else x,y]
                if colour[3]==255:
                    sample[colour[:3]]+=1
        return sample.most_common(1)[0][0] if sample else None
    return _memo(image,('dominant',mirror),calculate)


def iso_straight_height(image):
    """Physical straight wall height, matching original alpha-column median."""
    def calculate():
        rgba=image if image.mode=='RGBA' else image.convert('RGBA')
        alpha=rgba.getchannel('A').load()
        bottoms=[]
        for x in range(rgba.width):
            for y in range(rgba.height-1,-1,-1):
                if alpha[x,y]:
                    bottoms.append(y+1-x*0.5)
                    break
        return max(1.0,float(median(bottoms))) if bottoms else 1.0
    return _memo(image,'height',calculate)


def clear_metrics_cache():
    with _lock:
        _cache.clear()
