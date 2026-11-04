"""Asset-dependent pixel sprite logic, unchanged from SC3K 3.47.8.

This is the first strictly mechanical module extraction. Paths stay relative
 to this file, located next to volume_editor.py, so existing asset loading
and cached artist-painted sprite transformations remain identical.
"""
from pathlib import Path
from PIL import Image

DORMER_SPRITES_PATH=Path(__file__).resolve().parent/"library"/"roof"
COLUMN_SPRITES_PATH=Path(__file__).resolve().parent/"library"/"column"
_COLUMN_CACHE={}
_DORMER_CACHE={}

DORMER_COMPONENTS=(('glass','glass_roof_7x9.png'),('frame','frame_roof_7x9.png'),('casing','casing_roof_7x9.png'))

def dormer_window_sprite(variant=1, front=False, offsets=None):
    """Compose a MATCHED ISO/FRONT pair, keeping the three 7x9 layers native.

    Offsets are per-projection pixel displacements inside a larger transparent
    working canvas. No part is ever stretched, and the complete matched set is
    always indexed together: (variant - 1)*2 + perspective.
    """
    variant=max(1,min(2,int(variant)))
    perspective='front' if front else 'iso'
    offsets=offsets or {}
    key=(variant,bool(front),tuple(tuple(offsets.get(perspective,{}).get(name,(0,0))) for name,_ in DORMER_COMPONENTS))
    if key in _DORMER_CACHE:return _DORMER_CACHE[key]
    cell=(variant-1)*2+int(bool(front))
    result=Image.new('RGBA',(19,21))
    for name,filename in DORMER_COMPONENTS:
        path=DORMER_SPRITES_PATH/filename
        if not path.is_file():continue
        with Image.open(path) as sheet:image=sheet.convert('RGBA')
        if image.width<(cell+1)*7 or image.height<9:continue
        sprite=image.crop((cell*7,0,(cell+1)*7,9))
        dx,dy=offsets.get(perspective,{}).get(name,(0,0))
        result.alpha_composite(sprite,(6+int(dx),6+int(dy)))
    _DORMER_CACHE[key]=result
    return result


def _column_sheet_frame(part='up', cell=0):
    path=COLUMN_SPRITES_PATH/(f'column_{part}_16x18.png')
    if not path.exists():
        return None
    cell=max(0,int(cell))
    with Image.open(path) as image:
        image=image.convert('RGBA')
        if image.width<(cell+1)*16 or image.height<18:
            return None
        return image.crop((cell*16,0,(cell+1)*16,18))


def column_part_sprite(style=1, part='up', diagonal=False):
    """Return native sprite cells from the column library.

    For `mid`, only the even cells are true shaft modules. The odd cells in the
    updated library are reserved for PROFILE capital art and must never be used
    to stretch the circular shaft.
    """
    style=max(1,min(3,int(style)))
    if part=='mid':
        # Only even cells are shafts; odd cells are profile capitals.
        frame=(style-1)*2
    elif part=='low':
        # Updated artist sheet: Ionic (style 2) uses cell 2 for a dedicated
        # reverse-lit ISO capital, so its unchanged foot has moved to cell 3.
        # Other styles still take the native ISO foot from cells 0 and 4.
        frame={1:0,2:3,3:4}[style]
    else:
        frame=(style-1)*2+int(bool(diagonal))
    return _column_sheet_frame(part,frame)


def column_capital_source(style=1, mode='iso', mirror=False):
    """Fetch the capital source art.

    mode='iso'    -> column_up even cell
    mode='front'  -> column_up odd cell
    mode='profile'-> column_mid odd cell (repurposed artist cells)
    """
    style=max(1,min(3,int(style)))
    if mode=='profile':
        # Both profile sectors use the very same painted profile (no mirror).
        sprite=_column_sheet_frame('mid',(style-1)*2+1)
        mirror=False
    elif mode=='front':
        sprite=_column_sheet_frame('up',(style-1)*2+1)
    elif mode=='iso' and mirror and style==2:
        # The Ionic reverse ISO is NOT a flipped original: its lighting is
        # hand-painted for the other view, stored in column_low cell 2.
        sprite=_column_sheet_frame('low',2)
        mirror=False
    else:
        sprite=_column_sheet_frame('up',(style-1)*2)
    if sprite is not None and mirror:
        sprite=sprite.transpose(Image.FLIP_LEFT_RIGHT)
    return sprite


def capital_angle_mapping(angle_deg):
    """Map camera angle to capital sprite family.

    Artistic map agreed from the reference chart:
      ISO master:      0, 180
      ISO mirrored:    90, 270
      PROFILE:         30, 45, 60
      PROFILE (unmirrored): 210, 225, 240
      FRONT:           105, 120, 135, 150, 165,
                       285, 300, 315, 330, 345

    The exact showcase masters stay raw on 45, 135, 225 and 315.
    Neighbouring angles in the same family are projected in screen space.

    Remaining transition angles (15, 75, 195, 255) fall back to the nearest
    isometric family so the capital never defaults to FRONT at the canonical
    turns.
    """
    ang=int(round(angle_deg))%360

    if ang in (0, 15, 180, 195):
        return 'iso', False, False
    if ang in (75, 90, 255, 270):
        return 'iso', True, False

    if ang in (30, 45, 60):
        return 'profile', False, ang==45
    if ang in (210, 225, 240):
        return 'profile', False, ang==225

    if ang in (105, 120, 135, 150, 165,
               285, 300, 315, 330, 345):
        return 'front', False, ang in (135, 315)

    # Safety fallback: nearest canonical isometric family.
    if ang < 90:
        return ('iso', False, False) if ang < 45 else ('iso', True, False)
    if ang < 180:
        return 'front', False, False
    if ang < 270:
        return ('iso', False, False) if ang < 225 else ('iso', True, False)
    return 'front', False, False


def projected_column_capital(style=1, mode='iso', rise_px=0, mirror=False, raw=False):
    """Prepare the upper column sprite for the current camera.

    Returns the transformed sprite, its X anchor offset, and the bottom row
    of the visible shaft seam inside the transformed art. The seam metric lets
    the capital attach to the middle module without artificial gaps.
    """
    style=max(1,min(3,int(style)))
    rise_px=int(round(rise_px))
    mode=str(mode or 'iso')
    key=('capital_projected',style,mode,rise_px,bool(mirror),bool(raw))
    if key in _COLUMN_CACHE:return _COLUMN_CACHE[key]
    sprite=column_capital_source(style,mode=mode,mirror=mirror)
    if sprite is None:
        return None,0,0
    # Use the shaft footprint from the middle module to identify the joint area.
    mid_ref=column_part_sprite(style,'mid',diagonal=False)
    shaft_bbox=mid_ref.getbbox() if mid_ref is not None else (4,0,12,18)
    seam_cols=range(max(0,shaft_bbox[0]),min(sprite.size[0],shaft_bbox[2]))
    # In v3.30 the old boolean `diagonal` argument was replaced by `mode`.
    # Referring to the removed name raised NameError whenever a scene with
    # columns was re-rendered (including after pressing Apply extrusion).
    if raw or mode=='iso' or rise_px==0:
        seam_bottom=max((y for x in seam_cols for y in range(sprite.size[1]-1,-1,-1)
                         if sprite.getpixel((x,y))[3]), default=sprite.size[1]-1)
        _COLUMN_CACHE[key]=(sprite,0,seam_bottom)
        return sprite,0,seam_bottom
    w,h=sprite.size
    shifts=[round((sx-(w-1)/2)*rise_px/max(1,w-1)) for sx in range(w)]
    min_shift=min(shifts); max_shift=max(shifts)
    out=Image.new('RGBA',(w,h+max_shift-min_shift),(0,0,0,0))
    for sx in range(w):
        dy=shifts[sx]-min_shift
        for sy in range(h):
            rgba=sprite.getpixel((sx,sy))
            if rgba[3]:
                out.putpixel((sx,sy+dy),rgba)
    seam_bottom=max((y+(shifts[x]-min_shift)
                     for x in seam_cols for y in range(h-1,-1,-1)
                     if sprite.getpixel((x,y))[3]), default=h-1)
    _COLUMN_CACHE[key]=(out,0,seam_bottom)
    return out,0,seam_bottom


def tile_sprite_y(sprite, target_h):
    """Lengthen a shaft by repeating its native centre row; never resize pixels.

    The first/last source rows remain intact, preserving the seams with the
    capital and circular base. No Pillow resize or image interpolation occurs.
    """
    if sprite is None:
        return None
    w,h=sprite.size
    target_h=max(h,int(target_h))
    if target_h==h:
        return sprite.copy()
    seam=h//2
    out=Image.new('RGBA',(w,target_h),(0,0,0,0))
    out.paste(sprite.crop((0,0,w,seam)),(0,0))
    for y in range(seam,target_h-(h-seam)):
        out.paste(sprite.crop((0,seam,w,seam+1)),(0,y))
    out.paste(sprite.crop((0,seam,w,h)),(0,target_h-(h-seam)))
    return out

