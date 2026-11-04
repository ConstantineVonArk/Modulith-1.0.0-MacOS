#!/usr/bin/env python3
"""SC3K Volume Editor v13.5: coherent ground edges and analytic wall shadows."""
import json, math, time, tkinter as tk
import threading, copy
from collections import OrderedDict, deque
from functools import lru_cache
from PIL import ImageFilter
from pathlib import Path
from dataclasses import dataclass,asdict,field
from tkinter import ttk, filedialog, messagebox
from PIL import Image,ImageDraw,ImageTk
from toolbar_icons import thumbnail, attach_tooltip
from facade_metrics import dominant_opaque_colour, iso_straight_height

BG="#f3f3f1"
PREVIEW="#777a7d"
WALL_LIGHT=(226,225,222)
WALL_DARK=(185,186,183)
ROOF_LIGHT=(198,138,115)
ROOF_DARK=(163,101,79)
ROOF_FLAT=(221,173,148)
EDGE=(112,112,110)
CAST_SHADOW=(91,94,98)
ROOF_PALETTE_PATH=Path(__file__).resolve().parent/"library"/"palette_roof.png"
# Compatibility re-exports: legacy call sites and external tests keep the
# exact same public symbol names during staged migration.
from sprite_assets import (
    DORMER_SPRITES_PATH, COLUMN_SPRITES_PATH, _COLUMN_CACHE, _DORMER_CACHE,
    DORMER_COMPONENTS, dormer_window_sprite, _column_sheet_frame,
    column_part_sprite, column_capital_source, capital_angle_mapping,
    projected_column_capital, tile_sprite_y,
)


@dataclass
class Block:
    name:str='Body'
    x:int=0
    y:int=0
    w:int=48
    d:int=24
    h:int=36
    rise:int=12
    axis:str="X"
    roof_type:str='Gable'
    ridge:int=20
    overhang:int=1
    thickness:int=1
    eave_drop:int=0
    thickness_enabled:bool=False
    extended_gable:bool=True

    def roof_bounds(self):
        # Isometric horizontal coordinates: 1 world unit projects to 2
        # screen pixels over a symmetric eave extension. Half-units give
        # consistent 1-pixel increments for successive spinbox values.
        e=self.overhang/2
        return (self.x-e,self.y-e,self.x+self.w+e,self.y+self.d+e)

    def roof_contains(self,x,y):
        x0,y0,x1,y1=self.roof_bounds()
        return x0-1e-8<=x<=x1+1e-8 and y0-1e-8<=y<=y1+1e-8

    def planes(self, disabled_hips=()):
        """Roof as the lower envelope of 2 or 4 planes.

        The ridge is anchored to the BODY and always stays at h+rise.
        All slopes terminate at the same eave height, h-eave_drop,
        at the OUTER roof boundary (including lateral overhang).
        Thus adjusting overhang/drop/ridge never sends one facet
        arbitrarily beneath the others at the edge.
        """
        x0,y0,x1,y1=self.roof_bounds()
        high=self.h+self.rise
        low=self.h-self.eave_drop
        span=high-low
        midx=self.x+self.w/2
        midy=self.y+self.d/2
        if self.axis=="X":
            sy0=span/max(0.5,midy-y0)
            sy1=span/max(0.5,y1-midy)
            planes=[(0, sy0, high-sy0*midy),
                    (0,-sy1, high+sy1*midy)]
            if self.roof_type=='Hip':
                ridge=max(0,min(self.ridge,self.w))
                left=midx-ridge/2
                right=midx+ridge/2
                sx0=span/max(0.5,left-x0)
                sx1=span/max(0.5,x1-right)
                if "start" not in disabled_hips:
                    planes.append((sx0,0,high-sx0*left))
                if "end" not in disabled_hips:
                    planes.append((-sx1,0,high+sx1*right))
        else:
            sx0=span/max(0.5,midx-x0)
            sx1=span/max(0.5,x1-midx)
            planes=[( sx0,0,high-sx0*midx),
                    (-sx1,0,high+sx1*midx)]
            if self.roof_type=='Hip':
                ridge=max(0,min(self.ridge,self.d))
                near=midy-ridge/2
                far=midy+ridge/2
                sy0=span/max(0.5,near-y0)
                sy1=span/max(0.5,y1-far)
                if "start" not in disabled_hips:
                    planes.append((0,sy0,high-sy0*near))
                if "end" not in disabled_hips:
                    planes.append((0,-sy1,high+sy1*far))
        return planes

    def height_at(self,x,y,disabled_hips=()):
        if not self.roof_contains(x,y):
            return None
        return min(a*x+b*y+c for a,b,c in self.planes(disabled_hips))

    def contains(self,x,y):
        return self.x<=x<self.x+self.w and self.y<=y<self.y+self.d

@dataclass
class RoofAccessory:
    """A small roof-mounted solid with coordinates relative to a parent roof."""
    kind:str='Dormer'
    parent:int=0
    side:int=1
    along:int=50           # 0..100 percent along ridge
    slope:int=90           # 0..100 percent from ridge to eave
    width:int=8
    depth:int=20
    height:int=6
    roof_rise:int=2
    window_variant:int=1    # 1 or 2, each with ISO and FRONT sprites
    repeat_along:int=1     # symmetric copies along the ridge
    repeat_slope:int=1     # symmetric rows toward the eave
    gap_along:int=16      # additional world units between neighbours
    gap_slope:int=1       # additional world units between rows
    window_offsets:dict=field(default_factory=dict) # separate ISO/FRONT layer shifts



def expanded_accessories(blocks, accessories):
    """Regular centered arrays, in roof-local coordinates (not screen-space).

    One stored accessory remains the editable array prototype. Coordinates are
    recomputed when the parent roof changes, so arrays follow roof edits.
    """
    from dataclasses import replace
    for obj in accessories or ():
        if not 0 <= obj.parent < len(blocks):
            continue
        b=blocks[obj.parent]
        long_dim=b.w if b.axis=='X' else b.d
        half_slope=(b.d if b.axis=='X' else b.w)/2
        n=max(1,min(12,int(getattr(obj,'repeat_along',1))))
        m=max(1,min(6,int(getattr(obj,'repeat_slope',1))))
        # Reserve at least 1 world unit at both edges. Compress pitches on
        # cramped roofs rather than moving the group out of its parent.
        along_margin=min(.45,max(.06,(obj.width/2+1)/max(1,long_dim)))
        slope_margin=min(.35,max(.08,(obj.depth/2+1)/max(1,half_slope)))
        along_lo,along_hi=along_margin,1-along_margin
        slope_lo,slope_hi=slope_margin,1-slope_margin
        along_pitch=min((obj.width+max(0,obj.gap_along))/max(1,long_dim),
                        (along_hi-along_lo)/max(1,n-1))
        slope_pitch=min((obj.depth+max(0,obj.gap_slope))/max(1,half_slope),
                        (slope_hi-slope_lo)/max(1,m-1))
        ac=min(along_hi-(n-1)*along_pitch/2,
               max(along_lo+(n-1)*along_pitch/2,obj.along/100))
        sc=min(slope_hi-(m-1)*slope_pitch/2,
               max(slope_lo+(m-1)*slope_pitch/2,obj.slope/100))
        for i in range(n):
            for j in range(m):
                yield replace(obj,
                    along=round(100*(ac+(i-(n-1)/2)*along_pitch)),
                    slope=round(100*(sc+(j-(m-1)/2)*slope_pitch)),
                    repeat_along=1,repeat_slope=1)


def accessory_mesh(blocks, accessories):
    """Create genuine depth-tested world-space faces, attached to roof planes.

    The parent roof is not cut: the accessory walls begin slightly below its
    local surface so the existing depth buffer hides their submerged portions.
    """
    mesh=[]
    def face(points,kind,normal):
        for i in range(1,len(points)-1):
            mesh.append(((points[0],points[i],points[i+1]),kind,normal))
    for obj in expanded_accessories(blocks, accessories):
        b=blocks[obj.parent]
        if obj.kind not in ('Dormer','Chimney'):continue
        length=b.w if b.axis=="X" else b.d
        span=b.d if b.axis=="X" else b.w
        w=max(3,min(float(obj.width),length*.7))
        d=max(3,min(float(obj.depth),span*.44))
        along=max(.05,min(.95,obj.along/100))
        slope=max(.15,min(.85,obj.slope/100))
        ridge=(b.x+b.w*along) if b.axis=="X" else (b.y+b.d*along)
        mid=(b.y+b.d/2) if b.axis=="X" else (b.x+b.w/2)
        sign=1 if obj.side else -1
        center=mid+sign*slope*(span/2)
        # Avoid spilling off eaves, yet permit substantial freedom to position.
        center=max((b.y if b.axis=="X" else b.x)+d/2+1,
                   min((b.y+b.d if b.axis=="X" else b.x+b.w)-d/2-1,center))
        if b.axis=="X":
            x0,x1=ridge-w/2,ridge+w/2
            y0,y1=center-d/2,center+d/2
        else:
            x0,x1=center-d/2,center+d/2
            y0,y1=ridge-w/2,ridge+w/2
        # The solid is vertical; its submerged sections are hidden by the roof.
        corners=[(x0,y0),(x1,y0),(x1,y1),(x0,y1)]
        bottoms=[min(b.h,b.height_at(x,y) if b.height_at(x,y) is not None else b.h)-2
                 for x,y in corners]
        # Constant datum independent of depth: more depth sinks a larger part
        # into the roof instead of increasing the apparent wall height.
        top=b.h+max(3,obj.height)
        if obj.kind=='Chimney':
            wall_top=top
        else:
            wall_top=top
        for a,bb,normal in ((0,1,(0,-1,0)),(1,2,(1,0,0)),
                            (2,3,(0,1,0)),(3,0,(-1,0,0))):
            pa,pb=corners[a],corners[bb]
            bot_a=(pa[0],pa[1],bottoms[a]);bot_b=(pb[0],pb[1],bottoms[bb])
            up_a=(pa[0],pa[1],wall_top);up_b=(pb[0],pb[1],wall_top)
            wall_kind="accessory_wall"
            if obj.kind=='Dormer' and ((b.axis=="X" and a in (0,2)) or
                                         (b.axis=="Y" and a in (1,3))):
                # Paint windows directly on the gable wall, not onto a
                # parallel polygon. This guarantees identical depth/visibility
                # and prevents z-buffer precision from hiding the decals.
                side_axis='x' if b.axis=='X' else 'y'
                center_u=(x0+x1)/2 if b.axis=='X' else (y0+y1)/2
                # Store the real gable plane so canonical 2:1 ISO views
                # can paste the hand-painted 7x9 master without UV shearing.
                fixed_plane=pa[1] if b.axis=='X' else pa[0]
                wall_kind=('accessory_window_wall',int(obj.window_variant),
                           obj.window_offsets,side_axis,center_u-3.5,
                           top-5.0,7.,4.5,fixed_plane)
            face((bot_a,bot_b,up_b,up_a),wall_kind,normal)
        if obj.kind=='Chimney':
            # A slightly projecting dark cap; an inset reads as an opening.
            e=.85
            cap=[(x0-e,y0-e,top+.4),(x1+e,y0-e,top+.4),
                 (x1+e,y1+e,top+.4),(x0-e,y1+e,top+.4)]
            face(cap,"chimney_cap",(0,0,1))
            opening=[(x0+1,y0+1,top+.48),(x1-1,y0+1,top+.48),
                     (x1-1,y1-1,top+.48),(x0+1,y1-1,top+.48)]
            if x1-x0>3 and y1-y0>3:face(opening,"chimney_opening",(0,0,1))
        else:
            # Gable window artwork is drawn on the existing wall triangles.
            # No extra window rectangle is added to the scene mesh.
            rise=max(1,obj.roof_rise)
            # Ridge is perpendicular to the main building ridge, running
            # inward/outward along the slope of the parent roof.
            if b.axis=="X":
                q0=(x0,y0,top);q1=(x1,y0,top)
                q2=(x1,y1,top);q3=(x0,y1,top)
                r0=((x0+x1)/2,y0,top+rise)
                r1=((x0+x1)/2,y1,top+rise)
                face((q0,r0,r1,q3),"accessory_roof",(-1,0,1))
                face((r0,q1,q2,r1),"accessory_roof",(1,0,1))
                face((q0,q1,r0),"accessory_wall",(0,-1,0))
                face((q3,r1,q2),"accessory_wall",(0,1,0))
            else:
                q0=(x0,y0,top);q1=(x1,y0,top)
                q2=(x1,y1,top);q3=(x0,y1,top)
                r0=(x0,(y0+y1)/2,top+rise)
                r1=(x1,(y0+y1)/2,top+rise)
                face((q0,q1,r1,r0),"accessory_roof",(0,-1,1))
                face((r0,r1,q2,q3),"accessory_roof",(0,1,1))
                face((q0,r0,q3),"accessory_wall",(-1,0,0))
                face((q1,q2,r1),"accessory_wall",(1,0,0))
    return mesh


def iso(p):
    x,y,z=p
    return x-y,0.5*(x+y)-2*z

@lru_cache(maxsize=96)
def _angle_trig(angle):
    """One trigonometric evaluation per camera angle, not per vertex."""
    a=math.radians(angle)
    return math.cos(a), math.sin(a)

def rotate(p,angle,cx,cy):
    x,y,z=p
    x-=cx;y-=cy
    ca,sa=_angle_trig(angle)
    return x*ca-y*sa,x*sa+y*ca,z

def visible_color(normal,roof=False):
    # SimCity-style light/dark relative to the screen, not the building.
    nx,ny,nz=normal
    if not roof and abs(nx-ny)<1e-7 and abs(nz)<1e-7:
        return tuple(round((light+dark)/2) for light,dark in zip(WALL_LIGHT,WALL_DARK))
    return (ROOF_LIGHT if nx-ny<0 else ROOF_DARK) if roof else (
        WALL_LIGHT if nx-ny<0 else WALL_DARK)

def art_shade_factor(normal):
    """Unified light/half-light/shadow for facades, dormers and pitched roofs."""
    nx,ny,_=normal
    difference=nx-ny
    if abs(difference)<max(1e-7,0.035*math.hypot(nx,ny)):
        return 0.91
    return 1.0 if difference<0 else 0.82


def connected_hip_ends(blocks):
    """Remove a hip at an end of a wing embedded in another building.

    A roof branch that joins the middle of a perpendicular main block
    should have two longitudinal slopes and only its OUTER end hip.
    In a through-crossing, neither end is inside the other footprint,
    so both hips remain. No manual switch is required.
    """
    disabled={id(b):set() for b in blocks}
    for wing in blocks:
        if wing.roof_type!='Hip':
            continue
        for main in blocks:
            if main is wing or main.axis==wing.axis:
                continue
            if wing.axis=="Y":
                # Require genuine overlap across the wing's width.
                overlap=min(wing.x+wing.w,main.x+main.w)-max(wing.x,main.x)
                if overlap<min(wing.w,main.w)*0.35:
                    continue
                for end,y in (("start",wing.y),("end",wing.y+wing.d)):
                    # Embedded end must be in the main's INTERIOR,
                    # not just touching its wall.
                    if main.y+0.01<y<main.y+main.d-0.01:
                        disabled[id(wing)].add(end)
            else:
                overlap=min(wing.y+wing.d,main.y+main.d)-max(wing.y,main.y)
                if overlap<min(wing.d,main.d)*0.35:
                    continue
                for end,x in (("start",wing.x),("end",wing.x+wing.w)):
                    if main.x+0.01<x<main.x+main.w-0.01:
                        disabled[id(wing)].add(end)
    return disabled

def _scene_mesh_uncached(blocks,step=4):
    """Build the exact upper envelope of planar gable/hip roof facets.

    Roof pieces are clipped by analytical plane intersections, not
    interpolated through a coarse height grid. Wall solids use the original
    building footprint; roof eaves can extend beyond it.
    """
    if not blocks:return []


    def clip(poly,plane,keep_positive=True):
        """Sutherland-Hodgman clip of a 2D polygon by a linear inequality."""
        if not poly:return []
        a,b,c=plane
        def value(p):
            v=a*p[0]+b*p[1]+c
            return v if keep_positive else -v
        result=[]
        prev=poly[-1];pv=value(prev)
        for cur in poly:
            cv=value(cur)
            inside=cv>=-1e-9
            was_inside=pv>=-1e-9
            if inside!=was_inside:
                ratio=pv/(pv-cv)
                result.append((prev[0]+ratio*(cur[0]-prev[0]),
                               prev[1]+ratio*(cur[1]-prev[1])))
            if inside:result.append(cur)
            prev,pv=cur,cv
        return result

    def subtract_planes(p,q):
        return tuple(a-b for a,b in zip(p,q))

    def add_poly(mesh,poly,plane,kind):
        if len(poly)<3:return
        a,b,c=plane
        pts=[(x,y,a*x+b*y+c) for x,y in poly]
        normal=(-a,-b,1) if kind=="roof" else (0,0,1)
        for k in range(1,len(pts)-1):
            mesh.append(((pts[0],pts[k],pts[k+1]),kind,normal))

    # Grid lines at every footprint and eave boundary, ridge centre, and
    # start/end of each hip ridge. Within a cell each roof facet is planar.
    xs=set();ys=set()
    for b in blocks:
        x0,y0,x1,y1=b.roof_bounds()
        xs.update((x0,x1,b.x,b.x+b.w,b.x+b.w/2))
        ys.update((y0,y1,b.y,b.y+b.d,b.y+b.d/2))
        if b.axis=="X":
            xs.update((b.x+(b.w-b.ridge)/2,b.x+(b.w+b.ridge)/2))
        else:
            ys.update((b.y+(b.d-b.ridge)/2,b.y+(b.d+b.ridge)/2))
    xmin=min(xs);xmax=max(xs);ymin=min(ys);ymax=max(ys)
    xs.update(xmin+i*step for i in range(math.ceil((xmax-xmin)/step)+1) if xmin+i*step<xmax)
    ys.update(ymin+i*step for i in range(math.ceil((ymax-ymin)/step)+1) if ymin+i*step<ymax)
    xs=sorted(xs);ys=sorted(ys)
    if (len(xs)-1)*(len(ys)-1)>16000:
        raise ValueError('Scene too large to join roofs precisely')

    mesh=[]
    suppressed_hips=connected_hip_ends(blocks)
    cached_planes={id(b):b.planes(suppressed_hips[id(b)]) for b in blocks}


    for i in range(len(xs)-1):
        x0,x1=xs[i:i+2]
        if x1-x0<1e-7:continue
        for j in range(len(ys)-1):
            y0,y1=ys[j:j+2]
            if y1-y0<1e-7:continue
            mx=(x0+x1)/2;my=(y0+y1)/2
            active=[b for b in blocks if b.roof_contains(mx,my)]
            if not active:continue
            square=[(x0,y0),(x1,y0),(x1,y1),(x0,y1)]
            # Exact facet arrangement: for each candidate facet, first
            # choose the MIN facet of its own roof; then choose the MAX
            # roof of all overlapping blocks. This forms hips and valleys.
            for current in active:
                planes=cached_planes[id(current)]
                for plane in planes:
                    poly=square[:]
                    for own in planes:
                        if own is plane:continue
                        poly=clip(poly,subtract_planes(own,plane))
                        if len(poly)<3:break
                    if len(poly)<3:continue
                    regions=[poly]
                    for other in active:
                        if other is current:continue
                        new_regions=[]
                        others=cached_planes[id(other)]
                        for region in regions:
                            for other_plane in others:
                                part=region
                                for p in others:
                                    if p is other_plane:continue
                                    part=clip(part,subtract_planes(p,other_plane))
                                    if len(part)<3:break
                                if len(part)<3:continue
                                part=clip(part,subtract_planes(plane,other_plane))
                                if len(part)>=3:new_regions.append(part)
                        regions=new_regions
                        if not regions:break
                    for region in regions:
                        add_poly(mesh,region,plane,"roof")

            # External walls stop at wall height (under the eave).
            # Determine which walls are exposed using neighbour probes.
            covered=[b for b in blocks if b.contains(mx,my)]
            if not covered:continue
            for di,dj,p0,p1,normal in (
                (-1,0,(x0,y0),(x0,y1),(-1,0,0)),
                (1,0,(x1,y0),(x1,y1),(1,0,0)),
                (0,-1,(x0,y0),(x1,y0),(0,-1,0)),
                (0,1,(x0,y1),(x1,y1),(0,1,0)),
            ):
                eps=0.0001
                bx=(p0[0]+p1[0])/2+di*eps
                by=(p0[1]+p1[1])/2+dj*eps
                neighbours=[b for b in blocks if b.contains(bx,by)]
                top=max(b.h for b in covered)
                bottom=max((b.h for b in neighbours),default=0)
                if top<=bottom:continue
                q0=(p0[0],p0[1],bottom);q1=(p1[0],p1[1],bottom)
                # Continue external walls up to the UNDERSIDE of the
                # roof at the true building boundary. A widened eave
                # otherwise leaves a spurious background-coloured gap.
                def wall_top(point):
                    heights=[b.height_at(*point,suppressed_hips[id(b)])
                             for b in covered if b.roof_contains(*point)]
                    return max([z for z in heights if z is not None],default=top)
                r0=(p0[0],p0[1],wall_top(p0))
                r1=(p1[0],p1[1],wall_top(p1))
                mesh.append(((q0,q1,r1),"wall",normal))
                mesh.append(((q0,r1,r0),"wall",normal))

    # Triangular gable infill: the vertical triangle between the wall
    # top and the roof ridge at each end of a gable roof. Without these
    # pieces, gable roofs have holes when viewed from their ends.
    for b in blocks:
        if b.roof_type!='Gable':
            continue
        x0,y0,x1,y1=b.roof_bounds()
        # The gable end wall may either extend to the eave edge (legacy)
        # or stop at the actual body end, leaving visible roof overhang.
        for side in (0,1):
            if b.axis=="X":
                fixed=(x0 if side==0 else x1) if b.extended_gable else (b.x if side==0 else b.x+b.w)
                ystart,yend=(y0,y1) if b.extended_gable else (b.y,b.y+b.d)
                p0=(fixed,ystart);p1=(fixed,yend)
                pm=(fixed,(ystart+yend)/2)
                normal=(-1,0,0) if side==0 else (1,0,0)
            else:
                fixed=(y0 if side==0 else y1) if b.extended_gable else (b.y if side==0 else b.y+b.d)
                xstart,xend=(x0,x1) if b.extended_gable else (b.x,b.x+b.w)
                p0=(xstart,fixed);p1=(xend,fixed)
                pm=((xstart+xend)/2,fixed)
                normal=(0,-1,0) if side==0 else (0,1,0)
            midx,midy=pm
            z0=b.height_at(*p0)
            z1=b.height_at(*p1)
            zm=b.height_at(*pm)
            baseline=min(z0,z1)
            # Gable fill can be occluded by a second roof through Z-buffer.
            if zm>baseline+1e-6:
                mesh.append((((p0[0],p0[1],baseline),
                              (p1[0],p1[1],baseline),
                              (pm[0],pm[1],zm)),"wall",normal))

    # Roof thickness (fascia) for a gable roof: build it as real 3D strips
    # under the visible roof edge, not as a later 2D overlay. This makes the
    # trim follow the roof boundary pixel-for-pixel and removes gaps at the
    # ridge and eaves.
    for b in blocks:
        if b.roof_type!='Gable' or not b.thickness_enabled or b.thickness<=0:
            continue
        dz=b.thickness*0.5  # 0.5 world-z -> 1 screen pixel vertically
        eps=0.01
        x0,y0,x1,y1=b.roof_bounds()
        for side in (0,1):
            if b.axis=="X":
                fixed=x0 if side==0 else x1
                a=(fixed,y0)
                m=(fixed,(y0+y1)/2)
                c=(fixed,y1)
                shift=(-eps,0) if side==0 else (eps,0)
                normal=(-1,0,0) if side==0 else (1,0,0)
            else:
                fixed=y0 if side==0 else y1
                a=(x0,fixed)
                m=((x0+x1)/2,fixed)
                c=(x1,fixed)
                shift=(0,-eps) if side==0 else (0,eps)
                normal=(0,-1,0) if side==0 else (0,1,0)
            az=b.height_at(*a)
            mz=b.height_at(*m)
            cz=b.height_at(*c)
            top=[(a[0]+shift[0],a[1]+shift[1],az),
                 (m[0]+shift[0],m[1]+shift[1],mz),
                 (c[0]+shift[0],c[1]+shift[1],cz)]
            bot=[(top[0][0],top[0][1],az-dz),
                 (top[1][0],top[1][1],mz-dz),
                 (top[2][0],top[2][1],cz-dz)]
            # quad a-m and quad m-c
            mesh.append(((top[0],top[1],bot[1]),"fascia",normal))
            mesh.append(((top[0],bot[1],bot[0]),"fascia",normal))
            mesh.append(((top[1],top[2],bot[2]),"fascia",normal))
            mesh.append(((top[1],bot[2],bot[1]),"fascia",normal))
    return mesh

# Memoize the unmodified structural roof/body triangles across camera angles.
# The key contains *every* Block dataclass field, so edits to dimensions,
# roof styles and neighbouring blocks naturally invalidate the cache.
# Return a fresh list because render_scene appends optional accessory meshes.
_BLOCK_FIELDS=tuple(Block.__dataclass_fields__)

@lru_cache(maxsize=12)
def _cached_scene_mesh(block_state, step):
    blocks=[Block(**dict(zip(_BLOCK_FIELDS,fields))) for fields in block_state]
    return tuple(_scene_mesh_uncached(blocks,step))

def scene_mesh(blocks,step=4):
    if not blocks:
        return []
    key=tuple(tuple(getattr(b,name) for name in _BLOCK_FIELDS) for b in blocks)
    return list(_cached_scene_mesh(key,step))

def apply_wall_edits(mesh,blocks,edits):
    """Parametric rectangular insets/extrusions on existing planar wall faces.

    Subdivide wall triangles by the editing rectangle instead of overlaying a
    second box: original wall pixels in the opening are actually removed.
    Local wall axes are horizontal distance and Z, preserving floor bands.
    This first version intentionally leaves roofs and neighbouring blocks
    unchanged; edit rectangles are limited to the main body below eaves.
    """
    if not edits:return mesh
    # Adjacent equal-depth recesses form one vertical opening: do not
    # generate a horizontal ceiling/shelf at their shared storey boundary.
    def shared_edge(e, upper):
        for other in edits:
            if other is e:continue
            if (other.get('block')==e.get('block') and other.get('wall')==e.get('wall')
                and abs(float(other.get('depth',0))-float(e.get('depth',0)))<1e-6
                and abs(float(other.get('t0',0))-float(e.get('t0',0)))<1e-6
                and abs(float(other.get('t1',0))-float(e.get('t1',0)))<1e-6
                and abs(float(other['z0' if upper else 'z1'])-float(e['z1' if upper else 'z0']))<1e-6):
                return True
        return False
    result=list(mesh)
    for edit_idx,edit in enumerate(edits):
        bi=int(edit['block'])
        if not 0<=bi<len(blocks):continue
        b=blocks[bi];wall=edit['wall']
        t0,t1=sorted((float(edit['t0']),float(edit['t1'])))
        z0,z1=sorted((float(edit['z0']),float(edit['z1'])))
        z0=max(0,min(b.h,z0));z1=max(0,min(b.h,z1))
        if t1-t0<1e-5 or z1-z0<1e-5:continue
        distance=max(-min(b.w,b.d)*0.80,min(30.0,float(edit['depth'])))
        if abs(distance)<1e-5:continue
        if wall=='front':
            axis=0;fixed=b.y+b.d;normal=(0,1,0);length=b.w
            a0=b.x+t0*b.w;a1=b.x+t1*b.w
        elif wall=='back':
            axis=0;fixed=b.y;normal=(0,-1,0);length=b.w
            a0=b.x+(1-t1)*b.w;a1=b.x+(1-t0)*b.w
        elif wall=='left':
            axis=1;fixed=b.x;normal=(-1,0,0);length=b.d
            a0=b.y+t0*b.d;a1=b.y+t1*b.d
        elif wall=='right':
            axis=1;fixed=b.x+b.w;normal=(1,0,0);length=b.d
            a0=b.y+(1-t1)*b.d;a1=b.y+(1-t0)*b.d
        else:continue
        fixed_axis=1-axis
        def clip(poly,coordinate,bound,keep_greater):
            if not poly:return []
            def signed(pt):
                v=pt[coordinate]-bound
                return v if keep_greater else -v
            out=[];prev=poly[-1];pv=signed(prev)
            for curr in poly:
                cv=signed(curr)
                if (pv>=-1e-8)!=(cv>=-1e-8):
                    q=pv/(pv-cv)
                    out.append(tuple(prev[k]+q*(curr[k]-prev[k]) for k in range(3)))
                if cv>=-1e-8:out.append(curr)
                prev,pv=curr,cv
            return out
        def triangulate(poly,kind,norm):
            if len(poly)<3:return []
            return [( (poly[0],poly[i],poly[i+1]),kind,norm)
                    for i in range(1,len(poly)-1)]
        after=[];did_cut=False
        for tri,kind,norm in result:
            if kind!='wall' or any(abs(pt[fixed_axis]-fixed)>1e-5 for pt in tri) or norm!=normal:
                after.append((tri,kind,norm));continue
            # Clip polygon against four boundaries, emit outside pieces.
            inside=list(tri)
            for coordinate,bound,greater in ((axis,a0,True),(axis,a1,False),
                                             (2,z0,True),(2,z1,False)):
                outside=clip(inside,coordinate,bound,not greater)
                after.extend(triangulate(outside,kind,norm))
                inside=clip(inside,coordinate,bound,greater)
                if not inside:break
            if inside:did_cut=True
        if not did_cut:
            result=after;continue
        # A fully edge-open recess is a REAL cut through the front strip of
        # the body's adjacent lateral walls, not merely a missing front wall.
        # Otherwise skinny side-wall slivers remain, even at t=0 and t=1.
        # Leave ordinary inset cuts and all other blocks unchanged.
        open_edges=bool(edit.get('open_sides',False)) and distance<0
        side_open_lo=open_edges and abs(a0-(b.x if axis==0 else b.y))<1e-6
        side_open_hi=open_edges and abs(a1-((b.x+b.w) if axis==0 else (b.y+b.d)))<1e-6
        if side_open_lo or side_open_hi:
            side_min,side_max=sorted((fixed,fixed+normal[fixed_axis]*distance))
            cut_sides=[]
            for tri,kind,norm in after:
                is_side=False
                if kind=='wall':
                    for active,bound,sign in (
                        (side_open_lo,a0,-1),(side_open_hi,a1,1)):
                        expected=[0,0,0];expected[axis]=sign
                        if (active and norm==tuple(expected)
                            and all(abs(p[axis]-bound)<1e-6 for p in tri)):
                            is_side=True
                            break
                if not is_side:
                    cut_sides.append((tri,kind,norm))
                    continue
                # Subtract the rectangle [side_min,side_max] × [z0,z1]
                # from the neighbouring exterior lateral face. All remaining
                # pieces are still honest triangles in the original z-buffer.
                inside=list(tri)
                for coordinate,bound,greater in (
                    (fixed_axis,side_min,True),(fixed_axis,side_max,False),
                    (2,z0,True),(2,z1,False)):
                    outside=clip(inside,coordinate,bound,not greater)
                    cut_sides.extend(triangulate(outside,kind,norm))
                    inside=clip(inside,coordinate,bound,greater)
                    if not inside:break
            after=cut_sides
        # A negative distance produces an inset; a positive distance creates
        # a protrusion. Keep front plane within b geometry for now.
        shift=tuple(normal[k]*distance for k in range(3))
        def pt(u,z,shifted=False):
            vec=[0.,0.,float(z)]
            vec[axis]=u;vec[fixed_axis]=fixed
            if shifted:vec=[vec[k]+shift[k] for k in range(3)]
            return tuple(vec)
        def quad(p,q,r,s,kind,n):
            after.append(((p,q,r),kind,n));after.append(((p,r,s),kind,n))
        A=pt(a0,z0);B=pt(a1,z0);C=pt(a1,z1);D=pt(a0,z1)
        Ap=pt(a0,z0,True);Bp=pt(a1,z0,True)
        Cp=pt(a1,z1,True);Dp=pt(a0,z1,True)
        quad(Ap,Bp,Cp,Dp,('edited_wall_face',normal,distance,edit_idx),normal)
        if not shared_edge(edit,False):quad(A,B,Bp,Ap,('edited_wall',edit_idx,'floor'),(0,0,-1))
        if not shared_edge(edit,True):quad(Dp,Cp,C,D,('edited_wall',edit_idx,'ceiling'),(0,0,1))
        # Do not rebuild the lateral return walls at an open body edge.
        # In the normal niche mode both returns stay exactly as before.
        side=[0,0,0];side[axis]=-1
        if not side_open_lo:
            quad(A,Ap,Dp,D,('edited_wall',edit_idx,'side'),tuple(side))
        side[axis]=1
        if not side_open_hi:
            quad(Bp,B,C,Cp,('edited_wall',edit_idx,'side'),tuple(side))
        # The painted PNGs are the ONLY shafts, capitals and circular bases.
        # Their two simple square supports are real geometry: a lower podium
        # and an upper abacus. Both use the SAME anchor and footprint. Their
        # 0.5-unit thickness renders as exactly one vertical screen pixel.
        count=max(0,min(12,int(edit.get('columns',0))))
        if distance<0 and count:
            cell=(a1-a0)/count
            # An 8x8 world-unit square whenever the opening is large enough;
            # for narrow cuts clamp it so neither slab escapes the recess.
            size=min(8.0,cell*.96,max(0.0,abs(distance)-.5))
            if size>.05:
                centers=portico_column_positions(a0,a1,count,size)
                ent_bottom=portico_entablature_bottom(z0,z1)
                def prism(lo_a,hi_a,lo_f,hi_f,lo_z,hi_z,kind):
                    if hi_a-lo_a<=1e-6 or hi_f-lo_f<=1e-6 or hi_z-lo_z<=1e-6:
                        return
                    if axis==0:
                        v=[(lo_a,lo_f,lo_z),(hi_a,lo_f,lo_z),(hi_a,hi_f,lo_z),(lo_a,hi_f,lo_z),
                           (lo_a,lo_f,hi_z),(hi_a,lo_f,hi_z),(hi_a,hi_f,hi_z),(lo_a,hi_f,hi_z)]
                    else:
                        v=[(lo_f,lo_a,lo_z),(lo_f,hi_a,lo_z),(hi_f,hi_a,lo_z),(hi_f,lo_a,lo_z),
                           (lo_f,lo_a,hi_z),(lo_f,hi_a,hi_z),(hi_f,hi_a,hi_z),(hi_f,lo_a,hi_z)]
                    for j,k,l,m,n in ((0,3,2,1,(0,0,-1)),(4,5,6,7,(0,0,1)),
                                      (0,1,5,4,(0,-1,0)),(1,2,6,5,(1,0,0)),
                                      (2,3,7,6,(0,1,0)),(3,0,4,7,(-1,0,0))):
                        after.append(((v[j],v[k],v[l]),kind,n))
                        after.append(((v[j],v[l],v[m]),kind,n))
                def square_support(x,y,lo,hi,kind):
                    q=size/2
                    prism(x-q,x+q,y-q,y+q,lo,hi,kind)
                depth_in=size/2+.25
                front_center=fixed-normal[fixed_axis]*depth_in
                front_lo=front_center-size/2
                front_hi=front_center+size/2
                # A single WATERTIGHT stepped entablature, instead of three
                # overlapping boxes. This avoids z-fighting and the isolated
                # light pixels seen near the frieze at 345 degrees.
                if ent_bottom<z1-.1:
                    lip=min(1.15,max(0.55,size*0.14),size*0.55)
                    # The front profile must read clearly even in the flat
                    # frontal projection: the frieze is recessed, while the
                    # lower architrave band and the upper cornice both project
                    # past it, including a small LEFT/RIGHT overhang.
                    # Make the lower architrave band flush with the frieze.
                    # This removes the tiny remaining side artefacts visible at
                    # 345°, while keeping the cornice as the only projecting
                    # outer band.
                    frieze_lo,frieze_hi=front_lo+lip*.72,front_hi-lip*.72
                    arch_lo,arch_hi=frieze_lo,frieze_hi
                    extra_projection=min(1.05,size*.16)
                    corn_lo=front_lo-lip*.92-extra_projection
                    corn_hi=front_hi+lip*.92+extra_projection
                    ent_h=z1-ent_bottom
                    arch_h=max(.75,min(1.05,ent_h*.20))
                    # One screen pixel = 0.5 world unit vertically in iso().
                    # Keep the cornice slightly thinner and donate that pixel
                    # to the frieze so the middle strip reads more substantial.
                    old_corn_h=max(.75,min(1.10,ent_h*.22))
                    corn_h=max(.50,old_corn_h-.50)
                    z_base=ent_bottom+.05
                    z_top=z1-.05
                    z_arch_top=ent_bottom+arch_h
                    z_frieze_top=z_top-corn_h
                    # Lateral overhangs make the profile readable at the flat
                    # front view, where pure depth offsets almost disappear.
                    # Lower band stays flush with the frieze in the front
                    # silhouette; only the cornice projects laterally.
                    arch_span=0.0
                    corn_span=min(1.65,size*.24)
                    # Allow the frieze to overlap adjacent bands slightly in
                    # Z. Combined with its tiny positive depth bias during
                    # rasterisation, this removes the last stray light
                    # pinstripes caused by pixel rounding on the shared joins.
                    seam_overlap=.12
                    tiers=[
                        (a0-arch_span,a1+arch_span,arch_lo,arch_hi,z_base,z_arch_top+seam_overlap,'portico_entablature_arch'),
                        (a0,a1,frieze_lo,frieze_hi,z_arch_top-seam_overlap,z_frieze_top+seam_overlap,'portico_entablature_frieze'),
                        (a0-corn_span,a1+corn_span,corn_lo,corn_hi,z_frieze_top-seam_overlap,z_top,'portico_entablature_cornice'),
                    ]
                    def point(along,depth,z):
                        return (along,depth,z) if axis==0 else (depth,along,z)
                    def face(v1,v2,v3,v4,kind,n):
                        after.append(((v1,v2,v3),kind,n))
                        after.append(((v1,v3,v4),kind,n))
                    near_normal=(0,-1,0) if axis==0 else (-1,0,0)
                    far_normal=(0,1,0) if axis==0 else (1,0,0)
                    start_normal=(-1,0,0) if axis==0 else (0,-1,0)
                    end_normal=(1,0,0) if axis==0 else (0,1,0)
                    def horizontal(al0,al1,lo,hi,z,kind,n):
                        if hi-lo>1e-7 and al1-al0>1e-7:
                            face(point(al0,lo,z),point(al1,lo,z),
                                 point(al1,hi,z),point(al0,hi,z),kind,n)
                    for al0,al1,lo,hi,zlo,zhi,kind in tiers:
                        face(point(al0,lo,zlo),point(al1,lo,zlo),
                             point(al1,lo,zhi),point(al0,lo,zhi),kind,near_normal)
                        face(point(al0,hi,zlo),point(al1,hi,zlo),
                             point(al1,hi,zhi),point(al0,hi,zhi),kind,far_normal)
                        face(point(al0,lo,zlo),point(al0,hi,zlo),
                             point(al0,hi,zhi),point(al0,lo,zhi),kind,start_normal)
                        face(point(al1,lo,zlo),point(al1,hi,zlo),
                             point(al1,hi,zhi),point(al1,lo,zhi),kind,end_normal)
                    horizontal(tiers[0][0],tiers[0][1],arch_lo,arch_hi,z_base,tiers[0][6],(0,0,-1))
                    horizontal(tiers[-1][0],tiers[-1][1],corn_lo,corn_hi,z_top,tiers[-1][6],(0,0,1))
                    # Connect successive tiers via only the OUTER exposed
                    # steps. Each boundary is exact: no overlap, and no
                    # invisible double surfaces in the z-buffer.
                    for lower,upper in zip(tiers,tiers[1:]):
                        al0_l,al1_l,lo0,hi0,_,join_z,lower_kind=lower
                        al0_u,al1_u,lo1,hi1,_,_,upper_kind=upper
                        al0=max(al0_l,al0_u)
                        al1=min(al1_l,al1_u)
                        if al1>al0:
                            if lo0<lo1:
                                horizontal(al0,al1,lo0,min(lo1,hi0),join_z,lower_kind,(0,0,1))
                            elif lo1<lo0:
                                horizontal(al0,al1,lo1,min(lo0,hi1),join_z,upper_kind,(0,0,-1))
                            if hi0>hi1:
                                horizontal(al0,al1,max(hi1,lo0),hi0,join_z,lower_kind,(0,0,1))
                            elif hi1>hi0:
                                horizontal(al0,al1,max(hi0,lo1),hi1,join_z,upper_kind,(0,0,-1))
                for along in centers:
                    center=[0.,0.]
                    center[axis]=along
                    # The same inset formula is used by render_scene when
                    # positioning all three pixel-art column components.
                    center[fixed_axis]=front_center
                    x,y=center
                    square_support(x,y,z0+.05,z0+.55,'portico_plinth')
                    # Reserve the top pixel just below the entablature.
                    if ent_bottom-z0>1.2:
                        square_support(x,y,ent_bottom-.55,ent_bottom-.05,'portico_abacus')
        result=after
    return result


def _smooth01(value):
    value=max(0.,min(1.,value))
    return value*value*(3.-2.*value)


def portico_entablature_height(z0,z1):
    """Architecturally readable total height of the procedural entablature.

    The old band was too thin next to the capitals. Keep it roughly twice as
    thick, but still scaled modestly to the overall niche height.
    """
    span=max(0.0,float(z1)-float(z0))
    return min(4.8,max(3.8,span*0.085))


def portico_column_positions(a0,a1,count,footprint):
    """Column centres along the opening.

    Architectural rule agreed with the user: крайние колонны стоят у самого
    края портика, so their square supports touch the side walls. Intermediate
    columns interpolate between those edge anchors. For a single column keep
    it centred. If the opening is too narrow, fall back to the old equal-cell
    centres.
    """
    count=max(0,int(count))
    if count<=0:
        return []
    if count==1:
        return [(a0+a1)/2.0]
    half=max(0.0,float(footprint))/2.0
    start=a0+half
    end=a1-half
    if end<start-1e-6:
        cell=(a1-a0)/count
        return [a0+(i+.5)*cell for i in range(count)]
    if abs(end-start)<1e-6:
        return [start for _ in range(count)]
    step=(end-start)/(count-1)
    return [start+i*step for i in range(count)]


def portico_entablature_bottom(z0,z1):
    """Bottom elevation of the procedural entablature volume."""
    ent_h=portico_entablature_height(z0,z1)
    return z1-ent_h if z1-z0>ent_h+1.4 else z1


def _niche_light_descriptors(blocks, edits, angle):
    """Each real recess gets one camera-aware light/aperture descriptor.

    Reconstruct exactly the same cut rectangle and podium/shaft positions as
    apply_wall_edits, without generating any visible procedural column art.
    """
    descriptors=[None]*len(edits)
    a=math.radians(angle)
    ca,sa=math.cos(a),math.sin(a)
    # Existing art-direction sunlight: upper-left in camera/screen space.
    sun_x=-.5*ca+.5*sa
    sun_y=.5*sa+.5*ca
    for i,e in enumerate(edits):
        try:
            bi=int(e['block']); b=blocks[bi]
            wall=e['wall']; depth=float(e['depth'])
            if depth>=-0.001:continue
            t0,t1=sorted((float(e['t0']),float(e['t1'])))
            z0,z1=sorted((float(e['z0']),float(e['z1'])))
            z0=max(0.,min(float(b.h),z0)); z1=max(0.,min(float(b.h),z1))
            if wall=='front':axis=0; fixed=b.y+b.d; normal=(0,1); length=b.w; origin=b.x
            elif wall=='back':axis=0; fixed=b.y; normal=(0,-1); length=b.w; origin=b.x; t0,t1=1-t1,1-t0
            elif wall=='left':axis=1; fixed=b.x; normal=(-1,0); length=b.d; origin=b.y
            elif wall=='right':axis=1; fixed=b.x+b.w; normal=(1,0); length=b.d; origin=b.y; t0,t1=1-t1,1-t0
            else:continue
            if z1-z0<.01 or t1-t0<.0001:continue
            a0=origin+length*t0; a1=origin+length*t1
            # Adjacent cuts are one continuous opening; an internal storey
            # edge should never cast a second invented lintel shadow.
            full_lo,full_hi=z0,z1
            changed=True
            while changed:
                changed=False
                for q in edits:
                    if (q.get('block')!=e.get('block') or q.get('wall')!=wall
                        or abs(float(q.get('depth',0))-depth)>1e-5
                        or abs(float(q.get('t0',0))-float(e['t0']))>1e-5
                        or abs(float(q.get('t1',0))-float(e['t1']))>1e-5):
                        continue
                    q0,q1=sorted((float(q['z0']),float(q['z1'])))
                    if q1>=full_lo-.0001 and q0<=full_hi+.0001:
                        new_lo=min(full_lo,q0);new_hi=max(full_hi,q1)
                        if new_lo!=full_lo or new_hi!=full_hi:
                            full_lo,full_hi=new_lo,new_hi;changed=True
            tangent_sun=sun_x if axis==0 else sun_y
            outward_sun=sun_x*normal[0]+sun_y*normal[1]
            # Direct sun should only cast interior shadows when it actually
            # reaches this facade. For openings turned away from the light we
            # keep only soft ambient dimming, with no invented cast shadows.
            # Use the SAME fixed screen-space sun as visible_color() and
            # art_shade_factor(), rather than a fabricated normal-facing sun.
            # This is what allows genuinely open lateral edges to admit a
            # sideways ray and make an angled cut under the overhang.
            lx,ly,lz=sun_x,sun_y,.60
            count=max(0,min(12,int(e.get('columns',0))))
            cell=(a1-a0)/count if count else 0
            podium_size=(min(8.,cell*.96,max(0.,abs(depth)-.5)) if count else 0.)
            col_depth=(podium_size/2+.25 if podium_size>.05 else 0.)
            columns=[]
            if col_depth:
                for u in portico_column_positions(a0,a1,count,podium_size):
                    pf=fixed-normal[1-axis]*col_depth
                    pos=(u,pf) if axis==0 else (pf,u)
                    columns.append(pos)
            cut_edges=bool(e.get('open_sides',False))
            # An open edge cannot cast a side-return shadow, because that
            # return wall was genuinely removed by apply_wall_edits.
            open_lo=cut_edges and abs(a0-origin)<1e-6
            open_hi=cut_edges and abs(a1-(origin+length))<1e-6
            descriptors[i]=(axis,fixed,normal,a0,a1,full_lo,full_hi,
                            abs(depth),lx,ly,lz,columns,
                            min(3.0,max(1.7,podium_size*.36)),open_lo,open_hi,
                            tangent_sun,outward_sun)
        except (KeyError,IndexError,TypeError,ValueError,ZeroDivisionError):
            continue
    return descriptors


def _niche_sun_aperture(desc, x, y, z):
    """Trace a receiver-to-sun ray through the *actual* recess boundaries.

    Returning (sun fraction, exit distance) is preferable to synthesizing an
    opening shadow from distance-to-edge: in an edge-open portico the ray may
    leave through an omitted lateral wall before meeting the lintel. The
    resulting bright triangular cut follows the real projected ray.
    """
    (axis,fixed,normal,a0,a1,z0,z1,depth,lx,ly,lz,columns,radius,
     open_lo,open_hi,tangent_sun,outward_sun)=desc
    # Keep the game art convention: truly dark-facing facades get no
    # direct cast shadows. However, near-frontal facades still benefit from a
    # weak stylised shadow cue for readability.
    frontal_stylized=(-.12<outward_sun<=.06)
    if outward_sun<=.06 and not frontal_stylized:
        return 0., 0.

    u=x if axis==0 else y
    pf=y if axis==0 else x
    tangent=lx if axis==0 else ly
    outward=lx*normal[0]+ly*normal[1]
    if frontal_stylized:
        outward=max(.22,abs(outward))
    distance=max(0.,min(depth,(fixed-pf)*normal[1-axis]))
    open_exits=[]
    solid_exits=[]
    eps=1e-6

    # Towards the actual front opening / towards the inset back wall.
    if outward>eps:
        open_exits.append(distance/outward)
    elif outward<-eps:
        solid_exits.append((depth-distance)/(-outward))

    # Left/right: absence of the side wall is a genuine new aperture, not
    # merely a slightly lighter strip on the wall texture.
    if tangent<-eps:
        t=(u-a0)/(-tangent)
        (open_exits if open_lo else solid_exits).append(max(0.,t))
    elif tangent>eps:
        t=(a1-u)/tangent
        (open_exits if open_hi else solid_exits).append(max(0.,t))

    # The solid underside of the roof always blocks direct sunlight. It
    # remains an occluder even when both lateral walls have been deleted.
    if lz>eps:
        solid_exits.append(max(0.,(z1-z)/lz))
    elif lz<-eps:
        solid_exits.append(max(0.,(z-z0)/(-lz)))
    if not open_exits:
        return 0.,0.
    t_open=min(open_exits)
    t_block=min(solid_exits) if solid_exits else float('inf')
    # 1-2 screen-pixel penumbra; the crossing of first-open and first-solid
    # exit times creates the diagonal cut of light on an open-side wall.
    # No blur is applied to any of the artists' sprites or facade pixels.
    if t_block==float('inf'):
        exposure=1.
    else:
        exposure=_smooth01(.5+(t_block-t_open)/2.0)
    return exposure, t_open


def _niche_shadow_strength(desc, surface, x, y, z):
    """Receiver-space lighting, sharing the game's fixed screen-space sun.

    Ambient depth is continuous; direct canopy/column shadows are evaluated
    only when the receiver actually sees the sun through an open boundary.
    """
    (axis,fixed,normal,a0,a1,z0,z1,depth,lx,ly,lz,columns,radius,
     open_lo,open_hi,tangent_sun,outward_sun)=desc
    u=x if axis==0 else y
    pf=y if axis==0 else x
    v=max(0.,min(1.,(u-a0)/max(.001,a1-a0)))
    h=max(0.,min(1.,(z-z0)/max(.001,z1-z0)))
    along_depth=max(0.,min(1.,((fixed-pf)*normal[1-axis])/max(.001,depth)))
    side_near=min(v if not open_lo else 1.,
                  (1.-v) if not open_hi else 1.)
    edge=_smooth01(side_near/.18)
    top_near=1.-_smooth01((1.-h)/.22)
    bottom_near=1.-_smooth01(h/.14)

    # Soft general dimming, retained at the reduced 3.26 strength.
    if surface=='back':
        ambient=.044+.024*min(1.,depth/15.)+.026*(1.-edge)+.016*top_near+.006*bottom_near
    elif surface=='side':
        ambient=.048+.038*along_depth+.013*top_near
    elif surface=='ceiling':
        ambient=.092+.022*along_depth
    else:
        ambient=.028+.025*along_depth+.009*(1.-edge)

    # There is no direct sunlight on the game's dark-facing facade.
    frontal_stylized=(-.12<outward_sun<=.06)
    if outward_sun<=.06 and not frontal_stylized:
        return min(.16,ambient)

    sun_fraction,exit_t=_niche_sun_aperture(desc,x,y,z)
    shadow_scale=.5 if frontal_stylized else 1.0
    canopy_shadow=.18*shadow_scale*(1.-sun_fraction)
    column_shadow=0.
    if sun_fraction>.001 and columns and (not frontal_stylized or surface=='floor'):
        l2=lx*lx+ly*ly
        if l2>1.e-6 and lz>1.e-6:
            for cx,cy in columns:
                # The column must intersect the ray BEFORE it exits the
                # opening; intersections behind the sunlit aperture do not
                # cast shadows back into the room.
                t=((cx-x)*lx+(cy-y)*ly)/l2
                tmin=max(0.,(z0+.5-z)/lz)
                tmax=min(exit_t,(z1-z)/lz)
                if tmax<=tmin:continue
                t=max(tmin,min(tmax,t))
                if t<=.02:continue
                dist=math.hypot(x+t*lx-cx,y+t*ly-cy)
                opacity=1.-_smooth01((dist-radius+.35)/2.0)
                projected_z=z+lz*t
                height_fade=_smooth01((projected_z-z0)/1.4)*_smooth01((z1-projected_z)/1.8)
                # Once the receiver sees the sun through the opening, the
                # column itself is the occluder; do not attenuate its shadow a
                # second time by sun_fraction, or a thin bright seam can appear
                # between the canopy shadow and the column shadow.
                column_shadow=max(column_shadow,.16*shadow_scale*opacity*height_fade)
    # Merge canopy and column masks into one cast-shadow field before adding
    # it to the ambient recess dimming. This avoids the stray light strip
    # that can appear where two softened shadow masks meet.
    can_n=max(0.,min(1.,canopy_shadow/max(1e-6,.18*shadow_scale)))
    col_n=max(0.,min(1.,column_shadow/max(1e-6,.16*shadow_scale))) if shadow_scale>0 else 0.
    cast_union_n=1.-(1.-can_n)*(1.-col_n)
    cast_shadow=.18*shadow_scale*cast_union_n
    return max(0.,min(.28,ambient+cast_shadow))


def render_scene(blocks,angle=0,step=2,cast_shadow=False,facade_texture=None,facade_block=0,facade_source=None,facade_filter='Pixels',facade_front=None,roof_color=None,roof_lines=False,roof_spacing=7,roof_opacity=30,roof_softness=0.65,roof_accessories=None,accessory_wall_color=None,transparent_background=False,wall_edits=None,wall_facades=None):
    """Software z-buffer; shared roof is a solid union envelope."""
    if not blocks:
        return Image.new("RGBA" if transparent_background else "RGB",(400,300),(0,0,0,0) if transparent_background else PREVIEW)
    mesh=apply_wall_edits(scene_mesh(blocks,step),blocks,wall_edits)
    # Recess illumination is computed after all opaque faces have won the
    # z-buffer, then composited BEFORE the artist's column sprites.
    niche_lighting=_niche_light_descriptors(blocks,wall_edits or [],angle)
    mesh.extend(accessory_mesh(blocks,roof_accessories))
    cx=(min(b.x for b in blocks)+max(b.x+b.w for b in blocks))/2
    cy=(min(b.y for b in blocks)+max(b.y+b.d for b in blocks))/2
    # IMPORTANT: shading is calculated AFTER rotation, in camera/screen space.
    # v11 calculated the colour BEFORE rotation, so two dark sides could face
    # the viewer after a 90-degree turn.
    a=math.radians(angle)
    ca,sa=math.cos(a),math.sin(a)
    # Early dominant facade-fill sample for procedural members that should
    # inherit the wall/module colour (e.g. frieze) even before textured-wall
    # post-processing runs.
    portico_facade_fill=None
    if facade_source is not None:
        try:
            portico_facade_fill=dominant_opaque_colour(facade_source)
        except Exception:
            portico_facade_fill=None
    if portico_facade_fill is None and accessory_wall_color is not None:
        portico_facade_fill=tuple(int(c) for c in accessory_wall_color)
    if portico_facade_fill is None:
        portico_facade_fill=tuple(round((2*light+dark)/3) for light,dark in zip(WALL_LIGHT,WALL_DARK))
    transformed=[]
    shadow_triangles=[]
    for tri,kind,normal in mesh:
        nx,ny,nz=normal
        rotated_normal=(nx*ca-ny*sa,nx*sa+ny*ca,nz)
        if isinstance(kind,tuple) and kind[0]=='accessory_window_wall':
            # Decal inherits exactly the lighting of its supporting wall.
            color=tuple(max(0,min(255,round(c*art_shade_factor(rotated_normal))))
                        for c in accessory_wall_color) if accessory_wall_color is not None else visible_color(rotated_normal)
        elif kind=="fascia":
            color=(175,110,85)
        elif kind=="accessory_wall":
            color=tuple(max(0,min(255,round(c*art_shade_factor(rotated_normal))))
                        for c in accessory_wall_color) if accessory_wall_color is not None else visible_color(rotated_normal)
        elif kind in ('portico_plinth','portico_abacus','portico_entablature_arch','portico_entablature_cornice'):
            # Bright stone members: podium, procedural abacus and the thin
            # lower/upper bands of the entablature.
            material=(225,225,225)
            if rotated_normal[2]>.5:
                color=(231,231,231)
            elif rotated_normal[2]<-.5:
                color=(173,173,173)
            else:
                # The cornice's vertical fascia must read as a side plane,
                # not compete in brightness with its horizontal top. Darken
                # only these vertical faces; preserve existing lighting and
                # the colours of the abacus, plinth and lower architrave.
                shade=art_shade_factor(rotated_normal)
                if kind=='portico_entablature_cornice':
                    shade*=0.90
                color=tuple(max(0,min(255,round(c*shade))) for c in material)
        elif kind=='portico_entablature_frieze':
            # The frieze should inherit the actual facade/wall colour and sit
            # visually back from the bright mouldings above and below it.
            facade_fill=portico_facade_fill
            if rotated_normal[2] > 0.5:
                color=tuple(min(255,round(c*1.02)+4) for c in facade_fill)
            elif rotated_normal[2] < -0.5:
                color=tuple(max(0,round(c*0.80)) for c in facade_fill)
            else:
                shade=art_shade_factor(rotated_normal)
                color=tuple(max(0,min(255,round(c*shade))) for c in facade_fill)
        elif (kind=='edited_wall' or (isinstance(kind,tuple) and kind[0] in ('edited_wall_face','edited_wall'))):
            # Inset/extension sides receive the same art-directed lighting as
            # untextured walls.  Horizontal tops are brighter than the walls.
            if rotated_normal[2] > 0.5:
                color=tuple(min(255,c+12) for c in WALL_LIGHT)
            elif rotated_normal[2] < -0.5:
                color=WALL_DARK
            else:
                color=visible_color(rotated_normal)
        elif kind=="chimney_cap":
            color=(115,108,104)
        elif kind=="chimney_opening":
            color=(43,44,46)
        else:
            color=visible_color(rotated_normal,roof=(kind in ("roof","underside","accessory_roof")))
        if kind in ("roof","accessory_roof") and roof_color is not None:
            factor=.91 if angle%90==45 else art_shade_factor(rotated_normal)
            color=tuple(max(0,min(255,round(c*factor))) for c in roof_color)
        rotated=[rotate(p,angle,cx,cy) for p in tri]
        transformed.append((rotated,color,kind,rotated_normal))
        if cast_shadow:
            # Game-art convention: every elevated point shifts strictly right
            # by its on-screen height (2 pixels per world z unit).
            shadow_triangles.append([(iso((x,y,0))[0]+2*z,iso((x,y,0))[1]) for x,y,z in rotated])
    coords=[iso(p) for tri,_,_,_ in transformed for p in tri]
    if cast_shadow:
        coords.extend(pt for tri in shadow_triangles for pt in tri)
    minx=math.floor(min(x for x,y in coords));maxx=math.ceil(max(x for x,y in coords))
    miny=math.floor(min(y for x,y in coords));maxy=math.ceil(max(y for x,y in coords))
    # Column sprites can extend a few pixels above/below the pure building mesh.
    # Reserve a small safety margin so lowered bases are not clipped.
    if wall_edits and any(int(e.get('columns',0) or 0)>0 and float(e.get('depth',0))<0 for e in wall_edits):
        miny-=4
        maxy+=24
    pad=12
    width=int(maxx-minx)+2*pad
    height=int(maxy-miny)+2*pad
    if width*height>6_000_000:
        raise ValueError('Scene size too large')
    image=Image.new("RGB",(width,height),PREVIEW)
    shadow_mask=None
    if cast_shadow:
        # Rasterize a single union mask, rather than painting individual
        # shadow triangles over the building. All shadow edges use the same
        # pixel-centre convention as the solid rasterizer below.
        shadow_mask=Image.new("L",(width,height),0)
        shadow_draw=ImageDraw.Draw(shadow_mask)
        for tri in shadow_triangles:
            points=[(x-minx+pad,y-miny+pad) for x,y in tri]
            shadow_draw.polygon(points,fill=255)
        # The wall rasterizer itself occludes the ground shadow, using its
        # exact pixel-centre silhouette. Do not dilate a separate footprint:
        # that creates a grey no-shadow halo outside the rendered walls.
        image.paste(CAST_SHADOW,(0,0),shadow_mask)
    pix=image.load()
    depth=[-float("inf")]*(width*height)
    niche_shade=bytearray(width*height) if any(niche_lighting) else None
    # The artist's circular base projects over the podium and the horizontal
    # sill at the bottom of its niche. Both are SUPPORTING surfaces, not
    # objects that should cut off the lower two rows of the sprite. Keep a
    # separate depth buffer for solid occluders (walls, side recess surfaces,
    # roofs, other volumes). Do not relax normal wall/roof occlusion.
    has_sprite_columns=bool(wall_edits and any(
        int(e.get('columns',0) or 0)>0 and float(e.get('depth',0))<0
        for e in wall_edits))
    if has_sprite_columns:
        from array import array
        solid_depth=array('f',[-float('inf')])*(width*height)
        support_depth=array('f',[-float('inf')])*(width*height)
    else:
        solid_depth=None
        support_depth=None
    # Shadow rays run in rotated world coordinates. Screen-right is
    # (-0.5,+0.5) on the ground; one unit of screen distance also raises
    # the ray by 0.5 world units. Test actual solid intersections rather
    # than sampling rounded columns (which caused v13.2's stripes).
    ray_dx,ray_dy,ray_dz=-0.5,0.5,0.5
    max_ray=2*max(b.h+b.rise for b in blocks)+4
    local_blocks=[]
    for b in blocks:
        # Bounds of each block in rotated coordinates.
        corners=[rotate((x,y,0),angle,cx,cy) for x in (b.x,b.x+b.w)
                 for y in (b.y,b.y+b.d)]
        local_blocks.append((b,corners))

    # The wall-shadow boundary is a true intersection of the light ray
    # with the solid, NOT a decision sampled at five arbitrary positions.
    # A block's roof is the minimum of its roof planes, therefore the ray
    # is under the roof precisely when it satisfies ALL plane inequalities.
    # Clipping one continuous interval removes the broken wall-shadow edge.
    planes_by_block={id(b):b.planes() for b in blocks}

    def wall_in_shadow(pos,normal):
        nx,ny,_=normal
        if nx*ray_dx+ny*ray_dy<=1e-7:
            return False
        rx,ry,rz=pos
        ox=rx*ca+ry*sa+cx
        oy=-rx*sa+ry*ca+cy
        dx=ray_dx*ca+ray_dy*sa
        dy=-ray_dx*sa+ray_dy*ca
        eps=1e-6
        for b,_ in local_blocks:
            # Intersect ray with the BODY footprint, not the overhang.
            # Open interval avoids false self-shadow at the wall surface.
            lo,hi=0.025,float(max_ray)
            for value,direction,start,stop in ((ox,dx,b.x,b.x+b.w),
                                               (oy,dy,b.y,b.y+b.d)):
                if abs(direction)<1e-12:
                    if not (start+eps<value<stop-eps):
                        hi=-1
                        break
                else:
                    t0=(start-value)/direction
                    t1=(stop-value)/direction
                    lo=max(lo,min(t0,t1)+eps)
                    hi=min(hi,max(t0,t1)-eps)
            if hi<=lo:
                continue
            # z > 0, and z < each sloped roof plane a*x+b*y+c.
            if rz+ray_dz*hi<=eps:
                continue
            lo=max(lo,(eps-rz)/ray_dz)
            for a,beta,c in planes_by_block[id(b)]:
                # f(t) = roof_plane(t) - ray_height(t) > 0
                f0=a*ox+beta*oy+c-rz
                slope=a*dx+beta*dy-ray_dz
                if abs(slope)<1e-12:
                    if f0<=eps:
                        hi=-1
                        break
                elif slope>0:
                    lo=max(lo,(eps-f0)/slope)
                else:
                    hi=min(hi,(eps-f0)/slope)
                if hi<=lo:
                    break
            if hi>lo+eps:
                return True
        return False

    # Direct pixel transfer at canonical iso views: no de-shearing,
    # re-projection, interpolation, or color correction of the original
    # facade artwork.  At 270° the visible +Y wall is the mirror image of
    # the default isometric wall, so use a horizontally flipped ISO master
    # instead of re-sampling the facade through the generic affine path.
    rotation=angle%360
    exact_facade = None
    exact_origin_mode = None
    if facade_source is not None:
        if rotation == 0:
            exact_facade = facade_source.convert("RGBA")
            exact_origin_mode = "wall_top"
        elif rotation == 270:
            exact_facade = facade_source.convert("RGBA").transpose(Image.FLIP_LEFT_RIGHT)
            exact_origin_mode = "bbox_top"
    exact_pixels = exact_facade.load() if exact_facade is not None else None
    # ISO strips can have transparent margins at their diagonal bottom edge.
    # The wall geometry and facade use independent pixel rounding, leaving a
    # narrow bare WALL_LIGHT strip. Use the dominant *actual facade wall*
    # color only where there is no source pixel; do not stretch windows.
    exact_wall_fill = None
    if exact_facade is not None:
        exact_wall_fill=dominant_opaque_colour(facade_source,mirror=rotation==270)
    # Smooth only the canonical ISO facade's colour samples.  Never blur the
    # final 3-D scene: that destroys roof geometry, shadows and silhouettes.
    # Fill transparent sprite margins with wall colour before low-radius
    # filtering, and retain the ORIGINAL alpha so no halo can escape a wall.
    exact_soft_pixels = None
    if exact_facade is not None and facade_filter in ('Smooth', 'Detailed'):
        fill = exact_wall_fill or WALL_LIGHT
        under = Image.new("RGBA", exact_facade.size, fill + (255,))
        under.alpha_composite(exact_facade)
        radius = 0.58 if facade_filter == 'Smooth' else 0.72
        weight = 0.43 if facade_filter == 'Smooth' else 0.54
        softened = Image.blend(under.convert("RGB"),
                              under.convert("RGB").filter(ImageFilter.GaussianBlur(radius)),weight)
        exact_soft_pixels = softened.load()
    # The original isometric master is sampled directly at every rotation.
    # Never create or sample a de-sheared intermediate bitmap.
    texture_pixels=facade_source.convert("RGBA").load() if facade_source is not None else None
    texture_block=blocks[facade_block] if (texture_pixels is not None or exact_pixels is not None or wall_facades) and 0 <= facade_block < len(blocks) else None
    # ISO (0°) and FRONT (315°) are two independent hand-drawn masters.
    # Always keep ISO at the canonical angles; use FRONT for intermediate
    # rotations where the +Y facade approaches a head-on (horizontal) view.
    # Both masters are sampled directly, never transformed into each other.
    # All non-canonical rotations use hand-drawn FRONT art; canonical
    # quarter turns retain ISO. No partial selection by angular distance.
    front_active=(facade_front is not None and rotation%90 != 0)
    if front_active:
        facade_source=facade_front
        texture_pixels=facade_front.convert('RGBA').load()
    master=facade_source.convert("RGBA") if facade_source is not None else None
    # The height of the RGBA bounding rectangle is NOT the physical wall
    # height: the isometric image includes an uneven staircase at its bottom.
    # Use exactly the same alpha-envelope measure as Facade Builder's height
    # synchronisation.  The previous (height - width/2) approximation was
    # several pixels too large, making 90/180/270-degree walls sample empty
    # rows and leaving a bare strip at the bottom.
    straight_height=1.0
    if master is not None:
        straight_height=(float(master.height) if front_active
                         else iso_straight_height(facade_source))
    if texture_block is not None and exact_pixels is not None:
        b=texture_block
        if exact_origin_mode == "wall_top":
            # Pixel-coordinate origin of the top-left of the +Y wall.
            wall_origin=iso(rotate((b.x,b.y+b.d,b.h),angle,cx,cy))
            facade_sx=round(wall_origin[0]-minx+pad)
            facade_sy=round(wall_origin[1]-miny+pad)
        else:
            # Mirrored canonical view: align the flipped wall master to the
            # bounding box of the visible wall footprint.
            wall_pts=[iso(rotate(p,angle,cx,cy)) for p in
                      ((b.x,b.y+b.d,0),(b.x+b.w,b.y+b.d,0),
                       (b.x+b.w,b.y+b.d,b.h),(b.x,b.y+b.d,b.h))]
            facade_sx=round(min(p[0] for p in wall_pts)-minx+pad)
            facade_sy=round(min(p[1] for p in wall_pts)-miny+pad)


    # Independent elevation masters for the back/left/right walls. Front
    # retains its native exact-ISO path for byte-for-byte compatibility.
    wall_masters={}
    if wall_facades:
        for side in ('back','left','right'):
            pair=wall_facades.get(side)
            if not pair:continue
            prefer_front=rotation%90!=0
            chosen=pair.get('front') if prefer_front else pair.get('iso')
            if chosen is None:chosen=pair.get('iso') or pair.get('front')
            if chosen is None:continue
            im=chosen.convert('RGBA')
            real_height=(float(im.height) if prefer_front
                         else iso_straight_height(chosen))
            wall_masters[side]=(im,im.load(),prefer_front,real_height)

    # Small architectural projections cast screen-right shadows onto the
    # parent roof. Volumes are world-aligned and the ray is camera aligned.
    # The depth buffer still determines the visible receiving surface.
    # Cast roof shadows from the VISIBLE portion of each accessory only.
    # v1.8 tested a rectangular prism extending below the parent roof; this
    # produced false "uphill" shadows from submerged walls and a full-height
    # imaginary rectangular cap above pitched dormers.
    accessory_boxes=[]
    for obj in expanded_accessories(blocks,roof_accessories):
        b=blocks[obj.parent]
        long_dim=b.w if b.axis=='X' else b.d
        span=b.d if b.axis=='X' else b.w
        aw=max(3,min(float(obj.width),long_dim*.7))
        ad=max(3,min(float(obj.depth),span*.44))
        along=max(.05,min(.95,obj.along/100))
        sl=max(.15,min(.85,obj.slope/100))
        ridge=(b.x+b.w*along) if b.axis=='X' else (b.y+b.d*along)
        mid=(b.y+b.d/2) if b.axis=='X' else (b.x+b.w/2)
        center=mid+(1 if obj.side else -1)*sl*(span/2)
        center=max((b.y if b.axis=='X' else b.x)+ad/2+1,
                   min((b.y+b.d if b.axis=='X' else b.x+b.w)-ad/2-1,center))
        if b.axis=='X':
            bx0,bx1=ridge-aw/2,ridge+aw/2
            by0,by1=center-ad/2,center+ad/2
        else:
            bx0,bx1=center-ad/2,center+ad/2
            by0,by1=ridge-aw/2,ridge+aw/2
        top=b.h+max(3,obj.height)
        rise=max(1,obj.roof_rise) if obj.kind=='Dormer' else .5
        accessory_boxes.append((b,obj.kind,bx0,bx1,by0,by1,top,rise,obj.side))
    light_dx=ray_dx*ca+ray_dy*sa
    light_dy=-ray_dx*sa+ray_dy*ca

    def roof_accessory_shadow(world_pos):
        if not accessory_boxes:return False
        ox,oy,oz=world_pos
        for b,kind,xmin,xmax,ymin,ymax,top,rise,side in accessory_boxes:
            # A roof protrusion only casts onto its side of the roof. Forbid
            # the artificial uphill lobe caused by shadow rays intersecting
            # a box on the other side of the upper footprint boundary.
            roof_axis_pos=oy if b.axis=='X' else ox
            upper_edge=(ymin if side else ymax) if b.axis=='X' else (xmin if side else xmax)
            if (side and roof_axis_pos<upper_edge-1e-4) or (not side and roof_axis_pos>upper_edge+1e-4):
                continue
            # Never let a receiving roof pixel inside the footprint cast a
            # shadow onto itself because of the buried part of the dormer.
            if xmin<=ox<=xmax and ymin<=oy<=ymax:
                continue
            lo,hi=.08,300.0
            for o,d,mn,mx in ((ox,light_dx,xmin,xmax),
                              (oy,light_dy,ymin,ymax),
                              (oz,ray_dz,b.h-3,top+rise)):
                if abs(d)<1e-12:
                    if o<=mn or o>=mx:hi=-1;break
                else:
                    a=(mn-o)/d;bb=(mx-o)/d
                    lo=max(lo,min(a,bb));hi=min(hi,max(a,bb))
            if hi<=lo+1e-5:continue
            # A bounding box is only a broad-phase accelerator. A positive
            # shadow requires a point of the ray to pass through the REAL
            # exposed solid above the parent roof and below the mini roof.
            for i in range(11):
                t=lo+(hi-lo)*(i+.5)/11
                x=ox+t*light_dx;y=oy+t*light_dy;z=oz+t*ray_dz
                parent_surface=b.height_at(x,y)
                if parent_surface is None:continue
                if z<=parent_surface+0.045:continue
                if kind=='Dormer':
                    # The mini-roof has a triangular end silhouette.
                    cross=(x-(xmin+xmax)/2)/max(1e-6,(xmax-xmin)/2) if b.axis=='X' else (y-(ymin+ymax)/2)/max(1e-6,(ymax-ymin)/2)
                    local_top=top+rise*max(0,1-abs(cross))
                else:
                    local_top=top+rise
                if z<local_top-0.035:return True
        return False

    def triangle(pts,color,kind,world_pts,normal):
        # Classify a triangle once, not for every covered pixel. All of these
        # values depend only on its material and normal, never on x/y.
        kind_tag=kind[0] if isinstance(kind,tuple) else kind
        is_dormer_wall=(kind_tag=='accessory_window_wall')
        is_edited_wall=(kind_tag=='edited_wall')
        is_moved_face=(kind_tag=='edited_wall_face')
        is_supporting_edit=(is_edited_wall and normal[2]<-0.5)
        texture_eligible=(kind=='wall' or is_moved_face)
        receiver=None
        if (niche_shade is not None and isinstance(kind,tuple)
            and kind[0] in ('edited_wall_face','edited_wall')):
            edit_index=(kind[3] if kind[0]=='edited_wall_face' else kind[1])
            if isinstance(edit_index,int) and 0<=edit_index<len(niche_lighting):
                desc=niche_lighting[edit_index]
                if desc is not None:
                    receiver=(desc,'back' if kind[0]=='edited_wall_face' else kind[2])
        # A plane's height gradient gives the downhill direction in XY.
        # Constant stripes run ALONG this downhill direction. Compute the
        # cross-slope coordinate in original world space, so subdivisions,
        # camera rotation and pitch changes never reset the pattern.
        roof_cross=None
        if kind=="roof" and roof_lines:
            rp=[(x*ca+y*sa+cx,-x*sa+y*ca+cy,z) for x,y,z in world_pts]
            dx1=rp[1][0]-rp[0][0];dy1=rp[1][1]-rp[0][1];dz1=rp[1][2]-rp[0][2]
            dx2=rp[2][0]-rp[0][0];dy2=rp[2][1]-rp[0][1];dz2=rp[2][2]-rp[0][2]
            denom=dx1*dy2-dx2*dy1
            if abs(denom)>1e-8:
                gx=(dz1*dy2-dz2*dy1)/denom
                gy=(dx1*dz2-dx2*dz1)/denom
                gl=math.hypot(gx,gy)
                if gl>1e-8:
                    roof_cross=(-gy/gl,gx/gl)

        (x0,y0,z0),(x1,y1,z1),(x2,y2,z2)=pts
        det=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)
        if abs(det)<1e-9:return
        xstart=max(0,math.floor(min(x0,x1,x2)))
        xend=min(width-1,math.ceil(max(x0,x1,x2)))
        ystart=max(0,math.floor(min(y0,y1,y2)))
        yend=min(height-1,math.ceil(max(y0,y1,y2)))
        # The inner loop is performance-critical. Precompute screen-space
        # x terms once per triangle; only the y-dependent term changes per
        # scanline. Keep the original operation order for pixel fidelity.
        dy20=y2-y0
        dx20=x2-x0
        dx10=x1-x0
        dy10=y1-y0
        px_offsets=[(xx+0.5-x0) for xx in range(xstart,xend+1)]
        u_x=[px*dy20 for px in px_offsets]
        v_x=[px*dy10 for px in px_offsets]
        for yy in range(ystart,yend+1):
            py=yy+0.5
            py_offset=py-y0
            u_y=dx20*py_offset
            v_y=dx10*py_offset
            for xidx,xx in enumerate(range(xstart,xend+1)):
                u=(u_x[xidx]-u_y)/det
                v=(v_y-v_x[xidx])/det
                if u< -1e-8 or v< -1e-8 or u+v>1+1e-8:continue
                # The dormer window is painted directly onto its gable wall.
                # Transparent art leaves the supporting wall colour intact.
                dormer_rgba=None
                if is_dormer_wall:
                    _,variant,offsets,axis,left,low,ww,wh,fixed_plane=kind
                    if rotation%90==0:
                        # At the four canonical isometric rotations the source
                        # 7x9 master is ALREADY drawn in screen-space 2:1.
                        # Mapping it through world-space (u,z) would add an
                        # extra diagonal shear and distort the window shape.
                        center_u=left+ww/2
                        center_z=low+wh/2
                        center_xyz=((center_u,fixed_plane,center_z) if axis=='x'
                                    else (fixed_plane,center_u,center_z))
                        anchor_x,anchor_y=iso(rotate(center_xyz,angle,cx,cy))
                        # Center on integer pixel positions, preserving the
                        # exact original sprite footprint and editor preview.
                        xf=xx-round(anchor_x-minx+pad-3)
                        yf=yy-round(anchor_y-miny+pad-4)
                        # A reversed slope needs the horizontal mirror of
                        # the ISO master (0/180 original, 90/270 mirrored).
                        if rotation in (90,270):xf=6-xf
                    else:
                        # Oblique camera views use the independent FRONT art.
                        # Its placement follows the real 3D gable surface.
                        wp0,wp1,wp2=world_pts
                        xxw=wp0[0]+u*(wp1[0]-wp0[0])+v*(wp2[0]-wp0[0])
                        yyw=wp0[1]+u*(wp1[1]-wp0[1])+v*(wp2[1]-wp0[1])
                        zzw=wp0[2]+u*(wp1[2]-wp0[2])+v*(wp2[2]-wp0[2])
                        worldu=xxw*ca+yyw*sa+cx if axis=='x' else -xxw*sa+yyw*ca+cy
                        # Limit decoration to its native screen footprint.
                        # Stretching a seven-pixel sprite across the whole
                        # gable face made oblique dormer windows too wide.
                        center_xyz=((left+ww/2,fixed_plane,low+wh/2) if axis=='x'
                                    else (fixed_plane,left+ww/2,low+wh/2))
                        screen_cx,_=iso(rotate(center_xyz,angle,cx,cy))
                        art_for_width=dormer_window_sprite(variant,front=True,offsets=offsets)
                        footprint=art_for_width.crop((6,6,13,15)).getbbox()
                        native_width=max(1,footprint[2]-footprint[0]) if footprint else 7
                        start_xyz=((left,fixed_plane,low) if axis=='x' else (fixed_plane,left,low))
                        end_xyz=((left+ww,fixed_plane,low) if axis=='x' else (fixed_plane,left+ww,low))
                        start_screen=iso(rotate(start_xyz,angle,cx,cy))[0]
                        end_screen=iso(rotate(end_xyz,angle,cx,cy))[0]
                        effective_w=max(1.0,min(float(native_width),abs(end_screen-start_screen)))
                        direction=1 if end_screen>=start_screen else -1
                        xf=3+(xx-(screen_cx-minx+pad))*7/effective_w*direction
                        yf=(low+wh-zzw)/wh*9-0.5
                    art=dormer_window_sprite(variant,front=(rotation%90!=0),offsets=offsets)
                    if not (-.5<=xf<6.5 and -.5<=yf<8.5):
                        dormer_rgba=(0,0,0,0)
                    elif facade_filter=='Pixels':
                        dormer_rgba=art.getpixel((min(12,max(6,round(xf)+6)),min(14,max(6,round(yf)+6))))
                    else:
                        # Interpolate premultiplied alpha: transparent padding
                        # must not form a white/black fringe around the decal.
                        def layer_sample(ix,iy):
                            if ix<0 or ix>6 or iy<0 or iy>8:return (0,0,0,0)
                            return art.getpixel((ix+6,iy+6))
                        if facade_filter=='Detailed':
                            def kernel(t):
                                t=abs(t)
                                if t<1:return 1.5*t**3-2.5*t*t+1
                                if t<2:return -.5*t**3+2.5*t*t-4*t+2
                                return 0.0
                            ix0=math.floor(xf);iy0=math.floor(yf)
                            taps=[(ix0+i,iy0+j,kernel(xf-ix0-i)*kernel(yf-iy0-j))
                                  for j in range(-1,3) for i in range(-1,3)]
                        else:
                            ix0=math.floor(xf);iy0=math.floor(yf)
                            taps=[(ix0+i,iy0+j,(1-abs(xf-ix0-i))*(1-abs(yf-iy0-j)))
                                  for j in range(2) for i in range(2)]
                        a=sum(layer_sample(ix,iy)[3]*w for ix,iy,w in taps)
                        aa=max(0,min(255,round(a)))
                        if a>0.001 and aa:
                            rgb=[max(0,min(255,round(sum(layer_sample(ix,iy)[c]*layer_sample(ix,iy)[3]*w
                                    for ix,iy,w in taps)/a))) for c in range(3)]
                            dormer_rgba=(*rgb,aa)
                        else:dormer_rgba=(0,0,0,0)
                    # Invisible art is just the normal wall colour;
                    # it must never discard the supporting wall pixel.
                z=z0+u*(z1-z0)+v*(z2-z0)
                # Let the recessed frieze slightly win any pixel-exact ties
                # against neighbouring entablature faces. This suppresses the
                # lingering bright pinstripes that can appear at 345° due to
                # raster rounding along shared stepped edges.
                if kind=='portico_entablature_frieze':
                    z+=0.035
                idx=yy*width+xx
                # Record the nearest REAL building surface, even when the
                # shallow plinth happens to be in front of it in the ordinary
                # z-buffer. The lower round base needs this for proper masking.
                if support_depth is not None:
                    is_support=(kind=='portico_plinth' or is_supporting_edit)
                    if is_support and z>support_depth[idx]:
                        support_depth[idx]=z
                if (solid_depth is not None
                    and kind!='portico_plinth'
                    and not is_supporting_edit
                    and z>solid_depth[idx]):
                    solid_depth[idx]=z
                if z>depth[idx]+1e-8:
                    depth[idx]=z
                    if niche_shade is not None:
                        if receiver is not None:
                            rp0,rp1,rp2=world_pts
                            rx=rp0[0]+u*(rp1[0]-rp0[0])+v*(rp2[0]-rp0[0])
                            ry=rp0[1]+u*(rp1[1]-rp0[1])+v*(rp2[1]-rp0[1])
                            rz=rp0[2]+u*(rp1[2]-rp0[2])+v*(rp2[2]-rp0[2])
                            ox=rx*ca+ry*sa+cx
                            oy=-rx*sa+ry*ca+cy
                            niche_shade[idx]=round(255*_niche_shadow_strength(
                                receiver[0],receiver[1],ox,oy,rz))
                        else:
                            niche_shade[idx]=0
                    if cast_shadow and kind=="wall":
                        # Recover the 3D receiver position from the same
                        # barycentric coordinates used by the z-buffer.
                        p0,p1,p2=world_pts
                        pos=(p0[0]+u*(p1[0]-p0[0])+v*(p2[0]-p0[0]),
                             p0[1]+u*(p1[1]-p0[1])+v*(p2[1]-p0[1]),
                             p0[2]+u*(p1[2]-p0[2])+v*(p2[2]-p0[2]))
                        if wall_in_shadow(pos,normal):
                            # Keep wall shadows substantially lighter than
                            # ground shadows and preserve original own shade.
                            pix[xx,yy]=tuple(max(0,c-18) for c in color)
                        else:
                            pix[xx,yy]=color
                    else:
                        pix[xx,yy]=color
                    if dormer_rgba is not None and dormer_rgba[3]>0:
                        r,g,b,a=dormer_rgba
                        # The decal's backing colour matches the dormer wall.
                        # Semi-transparent glass remains composited over it.
                        base=pix[xx,yy]
                        shade=art_shade_factor(normal)
                        decorated=(round(r*shade),round(g*shade),round(b*shade))
                        pix[xx,yy]=tuple(round((a*decorated[i]+(255-a)*base[i])/255)
                                         for i in range(3))
                    if roof_cross is not None:
                        # Interpolate the world-space receiver from its actual
                        # roof triangle. All adjoining clipped roof triangles
                        # use a common phase, preventing texture seams.
                        rp0,rp1,rp2=world_pts
                        rxx=rp0[0]+u*(rp1[0]-rp0[0])+v*(rp2[0]-rp0[0])
                        ryy=rp0[1]+u*(rp1[1]-rp0[1])+v*(rp2[1]-rp0[1])
                        wx=rxx*ca+ryy*sa+cx
                        wy=-rxx*sa+ryy*ca+cy
                        phase=wx*roof_cross[0]+wy*roof_cross[1]
                        gap=max(2.0,float(roof_spacing))
                        dist=abs((phase+0.5*gap)%gap-0.5*gap)
                        # Dark one-pixel grooves with a narrow soft shoulder.
                        # The edges remain confined to the roof z-buffer.
                        core=0.42
                        blur=max(0.02,float(roof_softness))
                        weight=max(0.0,min(1.0,(core+blur-dist)/blur))
                        amount=max(0.0,min(0.85,float(roof_opacity)/100))*weight
                        if amount>0:
                            pix[xx,yy]=tuple(max(0,round(c*(1-amount))) for c in pix[xx,yy])
                    if kind=="roof" and accessory_boxes:
                        p0,p1,p2=world_pts
                        rx=p0[0]+u*(p1[0]-p0[0])+v*(p2[0]-p0[0])
                        ry=p0[1]+u*(p1[1]-p0[1])+v*(p2[1]-p0[1])
                        rz=p0[2]+u*(p1[2]-p0[2])+v*(p2[2]-p0[2])
                        ox=rx*ca+ry*sa+cx;oy=-rx*sa+ry*ca+cy
                        if roof_accessory_shadow((ox,oy,rz)):
                            # Art direction: half-lit roofs lose another 15
                            # brightness units, reaching the full 30 shadow.
                            value=15 if rotation%90==45 or abs(art_shade_factor(normal)-.91)<.001 else 30
                            pix[xx,yy]=tuple(max(0,c-value) for c in pix[xx,yy])
                    # Integrated façade: sample the finished 2D facade on the
                    # +Y wall of the main block, using original world coords.
                    # This occurs inside the depth-tested rasterization, so roofs
                    # and nearer surfaces correctly occlude decorations.
                    if texture_block is not None and texture_eligible:
                        wx=world_pts[0][0]+u*(world_pts[1][0]-world_pts[0][0])+v*(world_pts[2][0]-world_pts[0][0])
                        wy=world_pts[0][1]+u*(world_pts[1][1]-world_pts[0][1])+v*(world_pts[2][1]-world_pts[0][1])
                        wz=world_pts[0][2]+u*(world_pts[1][2]-world_pts[0][2])+v*(world_pts[2][2]-world_pts[0][2])
                        original_x=wx*ca+wy*sa+cx
                        original_y=-wx*sa+wy*ca+cy
                        moved_face = is_moved_face
                        # Evaluate texture coordinates on the ORIGINAL wall,
                        # not the offset face.  This preserves the exact window
                        # pattern inside selected module cells after extrusion.
                        if moved_face:
                            base_normal,move_distance=kind[1],kind[2]
                            original_x-=base_normal[0]*move_distance
                            original_y-=base_normal[1]*move_distance
                        b=texture_block
                        # Other walls own separate façade masters and separate
                        # window distributions. The local horizontal axis of
                        # each wall follows the same convention as its module
                        # selection overlay (front +X, back -X, left +Y,
                        # right -Y). All surfaces still obey the shared z-buffer.
                        side=None; position_t=0.
                        if abs(original_y-b.y)<.025 and b.x-.01<=original_x<=b.x+b.w+.01:
                            side='back';position_t=(b.x+b.w-original_x)/max(.01,b.w)
                        elif abs(original_x-b.x)<.025 and b.y-.01<=original_y<=b.y+b.d+.01:
                            side='left';position_t=(original_y-b.y)/max(.01,b.d)
                        elif abs(original_x-(b.x+b.w))<.025 and b.y-.01<=original_y<=b.y+b.d+.01:
                            side='right';position_t=(b.y+b.d-original_y)/max(.01,b.d)
                        if side in wall_masters and 0<=wz<=b.h:
                            im,source_pixels,side_front,side_height=wall_masters[side]
                            tx=max(0.,min(1.,position_t))*max(0,im.width-1)
                            if side_front:
                                ty=(b.h-wz)/max(.01,b.h)*(im.height-1)
                            else:
                                ty=(b.h-wz)/max(.01,b.h)*side_height+tx*.5-.5
                            ix=max(0,min(im.width-1,round(tx)))
                            iy=max(0,min(im.height-1,round(ty)))
                            red,green,blue,alpha=source_pixels[ix,iy]
                            if alpha:
                                # Artistic illumination uses the real supporting
                                # wall face, rather than painting bright pixels
                                # through the dark/back side of the building.
                                base=pix[xx,yy]
                                shade=max(.30,min(1.15,sum(base)/max(1,sum(WALL_LIGHT))))
                                painted=tuple(max(0,min(255,round(v*shade))) for v in (red,green,blue))
                                pix[xx,yy]=tuple(round((alpha*painted[k]+(255-alpha)*base[k])/255) for k in range(3))
                            continue
                        if (abs(original_y-(b.y+b.d))<0.025 and
                            b.x-0.01<=original_x<=b.x+b.w+0.01 and
                            0<=wz<=b.h):
                            if exact_pixels is not None:
                                # The source canvas is ALREADY a 2:1 isometric
                                # wall. Copy identical integer pixels without
                                # UV interpolation, preserving all window shapes.
                                if moved_face:
                                    # Screen projection of the offset measured
                                    # relative to the canonical wall texture.
                                    screen_shift=iso(rotate((base_normal[0]*move_distance,
                                                             base_normal[1]*move_distance,0),angle,0,0))
                                    tx=xx-facade_sx-round(screen_shift[0])
                                    ty=yy-facade_sy-round(screen_shift[1])
                                else:
                                    tx=xx-facade_sx
                                    ty=yy-facade_sy
                                if 0<=tx<exact_facade.width and 0<=ty<exact_facade.height:
                                    fr,fg,fb,fa=exact_pixels[tx,ty]
                                    if fa:
                                        # At mirrored ISO 270° use the half-tone
                                        # appropriate to the camera-facing wall.
                                        factor=0.91 if rotation==270 else 1.0
                                        source_rgb = exact_soft_pixels[tx,ty] if exact_soft_pixels is not None else (fr,fg,fb)
                                        rgb=tuple(round(v*factor) for v in source_rgb)
                                        if fa==255:
                                            pix[xx,yy]=rgb
                                        else:
                                            base=pix[xx,yy]
                                            pix[xx,yy]=tuple(round((fa*v+(255-fa)*base[i])/255) for i,v in enumerate(rgb))
                                    elif exact_wall_fill is not None:
                                        pix[xx,yy]=exact_wall_fill
                                elif exact_wall_fill is not None:
                                    pix[xx,yy]=exact_wall_fill
                                continue
                            # Direct inverse affine mapping into the original
                            # isometric art: the source uses a 2:1 sheared rail.
                            # A single mapping avoids column-by-column rounding
                            # in a de-sheared copy, responsible for visible jumps.
                            tx=(original_x-b.x)/b.w*master.width-0.5
                            if front_active:
                                ty=(b.h-wz)/b.h*master.height-0.5
                            else:
                                ty=(b.h-wz)/b.h*straight_height + (tx+0.5)*0.5-0.5
                            if facade_filter=='Pixels':
                                ix=min(master.width-1,max(0,int(round(tx))))
                                iy=min(master.height-1,max(0,int(round(ty))))
                                fr,fg,fb,fa=texture_pixels[ix,iy]
                            else:
                                # Filter only after rotation. Source is never enlarged.
                                # Bicubic uses the original pixel neighborhood, not
                                # a twice-upscaled intermediate texture.
                                def px_at(ix,iy):
                                    ix=max(0,min(master.width-1,ix))
                                    iy=max(0,min(master.height-1,iy))
                                    return texture_pixels[ix,iy]
                                def cubic(t):
                                    t=abs(t)
                                    if t<1:return 1.5*t*t*t-2.5*t*t+1
                                    if t<2:return -0.5*t*t*t+2.5*t*t-4*t+2
                                    return 0.
                                if facade_filter=='Detailed':
                                    ix=math.floor(tx);iy=math.floor(ty)
                                    accum=[0.]*4
                                    for j in range(-1,3):
                                        wy=cubic(ty-(iy+j))
                                        for i in range(-1,3):
                                            ww=wy*cubic(tx-(ix+i))
                                            pixel=px_at(ix+i,iy+j)
                                            for channel in range(4):accum[channel]+=pixel[channel]*ww
                                    fr,fg,fb,fa=(max(0,min(255,round(v))) for v in accum)
                                else:
                                    ix=math.floor(tx);iy=math.floor(ty)
                                    fx=tx-ix;fy=ty-iy
                                    a,bp,c,d=px_at(ix,iy),px_at(ix+1,iy),px_at(ix,iy+1),px_at(ix+1,iy+1)
                                    fr,fg,fb,fa=(round(a[k]*(1-fx)*(1-fy)+bp[k]*fx*(1-fy)+c[k]*(1-fx)*fy+d[k]*fx*fy) for k in range(4))
                            if fa:
                                # Preserve painterly highlights but follow the
                                # wall's own light/shade and cast shadow.
                                base=pix[xx,yy]
                                shade=max(0.3,min(1.15,sum(base)/max(1,sum(WALL_LIGHT))))
                                decorated=(min(255,round(fr*shade)),min(255,round(fg*shade)),min(255,round(fb*shade)))
                                pix[xx,yy]=tuple(round((fa*decorated[i]+(255-fa)*base[i])/255) for i in range(3))
    for pts,color,kind,normal in transformed:
        screen=[]
        for p in pts:
            x,y=iso(p)
            screen.append((x-minx+pad,y-miny+pad,
                           p[0]+p[1]+p[2]*0.5+(0.0004 if color==(113,69,56) else 0)))
        triangle(screen,color,kind,pts,normal)
    # Apply recess lighting to the final textured receiver, never to the
    # column art. This avoids alpha resampling, texture blur and wall z seams.
    if niche_shade is not None:
        for idx,dark in enumerate(niche_shade):
            if not dark:continue
            yy,xx=divmod(idx,width)
            r,g,b=pix[xx,yy]
            light=255-dark
            pix[xx,yy]=((r*light+127)//255,(g*light+127)//255,(b*light+127)//255)
    # Sprite column ornamentation: split the capital, shaft and lower base.
    # Only the capital changes projection at oblique views; the round shaft
    # and lower base stay on the native isometric sprite and are never sheared.
    if wall_edits and COLUMN_SPRITES_PATH.exists():
        def blit_column_sprite(sprite,left,top,base_depth,base_z,bias=0.0,row_tilt=0.0):
            if sprite is None:return
            sw,sh=sprite.size
            for sy in range(sh):
                yy=top+sy
                if not 0<=yy<height:continue
                for sx in range(sw):
                    xx=left+sx
                    if not 0<=xx<width:continue
                    r,g,blue,alpha=sprite.getpixel((sx,sy))
                    if alpha==0:continue
                    column_z=base_z+(sh-1-sy)*.5
                    column_depth=base_depth+column_z*.5 + bias + sx*row_tilt
                    idx=yy*width+xx
                    if depth[idx]>column_depth+0.12:continue
                    background=pix[xx,yy]
                    pix[xx,yy]=tuple(round((a*alpha+v*(255-alpha))/255)
                                     for a,v in zip((r,g,blue),background))
                    depth[idx]=max(depth[idx],column_depth)
        for edit in wall_edits:
            count=max(0,min(12,int(edit.get('columns',0))))
            distance=float(edit.get('depth',0))
            bi=int(edit.get('block',-1))
            if not count or distance>=0 or not 0<=bi<len(blocks):continue
            b=blocks[bi];wall=edit.get('wall')
            t0,t1=sorted((float(edit['t0']),float(edit['t1'])))
            z0,z1=sorted((float(edit['z0']),float(edit['z1'])))
            if wall=='front':axis=0;fixed=b.y+b.d;normal=(0,1)
            elif wall=='back':axis=0;fixed=b.y;normal=(0,-1);t0,t1=1-t1,1-t0
            elif wall=='left':axis=1;fixed=b.x;normal=(-1,0)
            elif wall=='right':axis=1;fixed=b.x+b.w;normal=(1,0);t0,t1=1-t1,1-t0
            else:continue
            length=b.w if axis==0 else b.d
            a0=(b.x if axis==0 else b.y)+t0*length
            a1=(b.x if axis==0 else b.y)+t1*length
            cell=(a1-a0)/count
            podium_size=min(8.0,cell*.96,max(0.0,abs(distance)-.5))
            if podium_size<=.05:continue
            centers_along=portico_column_positions(a0,a1,count,podium_size)
            ent_bottom=portico_entablature_bottom(z0,z1)
            # Inset centre must be IDENTICAL to podium geometry centre.
            depth_in=podium_size/2+.25
            style=edit.get('column_style',1)
            iso_mid=column_part_sprite(style,'mid',diagonal=False)
            iso_low=column_part_sprite(style,'low',diagonal=False)
            if iso_mid is None or iso_low is None:continue
            # Column capitals use two different screen-space guide vectors.
            # FRONT assets should follow the row of columns (wall axis), while
            # PROFILE assets must follow the wall normal / torus direction.
            p0=iso(rotate((0,0,0),angle,0,0))
            axis_vec=((8 if axis==0 else 0),(0 if axis==0 else 8),0)
            normal_vec=(normal[0]*8,normal[1]*8,0)
            p_axis=iso(rotate(axis_vec,angle,0,0))
            p_normal=iso(rotate(normal_vec,angle,0,0))
            ang=angle%360
            capital_mode,capital_mirror,capital_raw=capital_angle_mapping(ang)
            capital_projected=(capital_mode!='iso' and not capital_raw)
            guide=(p_normal if capital_mode=='profile' else p_axis)
            cap_rise_px=(round(guide[1]-p0[1]) if capital_projected else 0)
            capital,cap_anchor_x,cap_seam_bottom=projected_column_capital(
                style,mode=capital_mode,rise_px=cap_rise_px,
                mirror=capital_mirror,raw=capital_raw)
            if capital is None:continue
            for i in range(count):
                center=[0.,0.]
                center[axis]=centers_along[i]
                center[1-axis]=fixed-normal[1-axis]*depth_in
                x,y=center
                # Podium top and the column base share the exact 3D origin.
                bx,by=iso(rotate((x,y,z0+.55),angle,cx,cy))
                base_screen_y=round(by-miny+pad)
                left=round(bx-minx+pad)-8
                # Bottom two rows in column_low are transparent, and must not
                # count as visible height when joining base to the podium.
                low_visible_bottom=iso_low.getbbox()[3]
                # The lower round base should sit directly on the podium top;
                # compared with the previous build, lower it by three pixels.
                low_top=base_screen_y-low_visible_bottom+3
                cap_screen_y=iso(rotate((x,y,ent_bottom),angle,cx,cy))[1]-miny+pad
                # Extend the shaft with a larger safety overlap so no slit can
                # remain visible between the capital and shaft, or between the
                # shaft and the lower base.
                # Reserve one screen pixel for the new procedural abacus.
                # Keep the lower circular base fixed and reduce only the
                # repeated part of the shaft, lowering its capital by 1 px.
                core_mid_h=max(18,low_top-round(cap_screen_y)-capital.height+1)
                overlap_top=4
                overlap_bottom=3
                mid_h=core_mid_h+overlap_top+overlap_bottom
                mid=tile_sprite_y(iso_mid,mid_h)
                mid_top=low_top+overlap_bottom-mid.height
                # Attach the capital to the shaft using the actual overlap, so
                # the lower visible seam of the capital sinks into the shaft.
                cap_top=mid_top+overlap_top-cap_seam_bottom-2
                # Tuck the sprite capital one screen pixel further under the
                # procedural abacus so the two do not read as stacked blocks.
                # Two specific oblique rotations still read slightly low.
                # Lift only the capital there, keeping the rest unchanged.
                # 285° still needs a slight lift, but at 345° the projected
                # capital was reading too high compared with neighbouring
                # rotations. Nudge 345° downward instead so the capital sits
                # consistently under the procedural abacus while rotating.
                if angle%360==285:
                    cap_top-=2
                elif angle%360==345:
                    # New atlas has no embedded abacus; keep 345° capital
                    # two pixels higher than the previous build.
                    cap_top-=1
                rx,ry,_=rotate((x,y,z0),angle,cx,cy)
                # Same camera-space depth source as the triangle z-buffer;
                # compare each column row at its own 3D height, not arbitrary
                # sprite height. Neighbouring walls and roofs can thus occlude.
                center_depth=rx+ry
                def overlay(sprite,draw_left,draw_top,bottom_world_z,bias=0.,overlap_plinth=False):
                    if sprite is None:return
                    w,h=sprite.size
                    pixels=sprite.load()
                    for sy in range(h):
                        yy=draw_top+sy
                        if yy<0 or yy>=height:continue
                        world_z=bottom_world_z+(h-1-sy)/2
                        dz=center_depth+.5*world_z+bias
                        for sx in range(w):
                            xx=draw_left+sx
                            if xx<0 or xx>=width:continue
                            r,g,bl,alpha=pixels[sx,sy]
                            if not alpha:continue
                            idx=yy*width+xx
                            # The foot ring overlaps its SUPPORTING surfaces
                            # (podium top and niche sill), but NOT other solids.
                            # All side walls and roofs still use z-occlusion.
                            if overlap_plinth and support_depth is not None:
                                # Ignore only the dedicated supporting surface
                                # directly under the foot ring (podium top or
                                # niche sill). All walls, roofs and previously
                                # drawn column sprites must still occlude.
                                support_block=support_depth[idx]
                                nearest_block=depth[idx]
                                blocker=(-float("inf") if support_block>-float("inf") and nearest_block<=support_block+.10
                                         else nearest_block)
                            else:
                                blocker=depth[idx]
                            if blocker>dz+.10:continue
                            background=pix[xx,yy]
                            pix[xx,yy]=tuple((v*alpha+b*(255-alpha)+127)//255
                                             for v,b in zip((r,g,bl),background))
                            depth[idx]=max(depth[idx],dz)
                # The upper module alone uses the oblique FRONT source.
                # All three pieces use one shared 8px centreline.
                # Keep the lower base fully visible above the plinth edge.
                overlay(iso_low,left,low_top,z0+.55,bias=0.38,
                        overlap_plinth=True)
                overlay(mid,left,mid_top,z0+.55+iso_low.height/2,bias=-.04)
                overlay(capital,left+cap_anchor_x,cap_top,
                        z0+.55+(iso_low.height+mid.height)/2,bias=-.12)
    if transparent_background:
        # Build the alpha channel from z-buffer coverage, NOT a colour key:
        # the building may legitimately contain the preview grey.
        alpha=Image.new("L",(width,height),0)
        ap=alpha.load()
        sp=shadow_mask.load() if shadow_mask is not None else None
        for yy in range(height):
            row=yy*width
            for xx in range(width):
                if depth[row+xx]>-float("inf"):
                    ap[xx,yy]=255
                elif sp is not None and sp[xx,yy]:
                    ap[xx,yy]=125
        image=image.convert('RGBA')
        image.putalpha(alpha)
    return image

class App:
    fields=(("X","x",-400,400),("Y","y",-400,400),
            ('Width',"w",12,250),('Depth',"d",12,250),
            ('Wall height',"h",10,250),('Roof height',"rise",1,120),
            ('Ridge length',"ridge",0,250),
            ('Outer overhang (px)',"overhang",0,8),
            ('Roof thickness',"thickness",0,2),
            ('Lower eave (vertical)',"eave_drop",0,3))
    def __init__(self,root,embedded=False):
        self.root=root
        self.embedded=embedded
        self.facade_texture=None
        self.facade_source=None
        self.facade_front=None
        self.accessory_wall_color=None
        self.facade_filter='Pixels'
        self.facade_filter_auto=False
        if not embedded:
            root.title("Modulith — Building Volume")
            root.geometry("1500x990")
            root.minsize(950,660)
            root.configure(bg=BG)
        self.blocks=[]
        self.roof_accessories=[]
        self.accessory_active=0
        self.active=0
        # Structural module selection, independent of decorative pixel sprites.
        self.module_layout={"floors":5,"counts":[5]*5,"spans":None,"front_spans":None,"band_heights":None,"band_widths":None}
        self.wall_layouts={}
        self.wall_facades={}
        self.selected_modules=set()
        self.wall_edits=[]
        self._redo_wall_edits=[]
        self.edit_depth=tk.IntVar(value=-6)
        self.cut_to_edges=tk.BooleanVar(value=False)
        self.portico_columns=tk.BooleanVar(value=False)
        self.portico_count=tk.IntVar(value=4)
        self.portico_style=tk.IntVar(value=1)
        self.module_select_mode=tk.BooleanVar(value=False)
        self.cell_select_scope=tk.StringVar(value='single')
        self.show_iso_grid=tk.BooleanVar(value=True)
        self._module_hit_regions=[]
        self.angle=0
        # CPU rasterization runs off the Tk event loop when switching angles.
        # Keep a bounded collection of complete, pixel-exact rendered views.
        self._angle_frames=OrderedDict()
        self._angle_frames_limit=8
        self._rotation_lock=threading.Lock()
        self._rotation_pending=None
        self._rotation_prefetch=deque()
        self._prefetch_timer=None
        self._rotation_finished=deque()
        self._rotation_thread=None
        self._rotation_poll_id=None
        self._rotation_target=None
        self._rotation_waiting=False
        self.after_id=None
        self._camera_last_frame=0.0
        self._camera_frame_interval=0.040
        self._display_preview_pan=None
        self._preview_image_cache_key=None
        self._preview_image_cache=None
        self._preview_scaled_key=None
        self._preview_mask_cache_key=None
        self._preview_mask_cache=None
        self._native_mask_cache_key=None
        self._native_masks=None
        self._preview_scaled=None
        self.photo=None
        self.updating=False
        self.snap=tk.BooleanVar(value=False)
        self.cast_shadow=tk.BooleanVar(value=False)
        self.roof_color=(153,169,187)
        self.roof_lines=tk.BooleanVar(value=True)
        self.roof_spacing=tk.IntVar(value=7)
        self.roof_opacity=tk.IntVar(value=30)
        self.roof_softness=tk.DoubleVar(value=0.65)
        self.setup_style()
        self.build_ui()
        self.preset("I")
        self.root.bind('<Destroy>',self._on_volume_destroy,add='+')

    def _on_volume_destroy(self,event):
        if event.widget is not self.root:
            return
        for identifier in (self._prefetch_timer,self._rotation_poll_id,self.after_id):
            if identifier is not None:
                try:self.root.after_cancel(identifier)
                except tk.TclError:pass
        self._prefetch_timer=None
        self._rotation_poll_id=None
        with self._rotation_lock:
            self._rotation_pending=None
            self._rotation_prefetch.clear()

    def setup_style(self):
        style=ttk.Style()
        if "aqua" in style.theme_names():style.theme_use("aqua")
        else:
            style.theme_use("clam")
            style.configure("TButton",padding=(10,6))
        style.configure("TFrame",background="#e8e8e8")
        style.configure("Panel.TFrame",background="#e8e8e8")
        style.configure("Panel.TLabel",background="#e8e8e8",foreground="#202124")
        style.configure("Heading.TLabel",background="#e8e8e8",foreground="#242424",font=("Helvetica",12,"bold"))
        style.configure("TButton",padding=(9,6))
        style.configure("Toolbar.TFrame",background="#e8e8e8")
        style.configure("Toolbar.TLabel",background="#e8e8e8",foreground="#272727")
        style.configure("Tray.TFrame",background="#dddddd")
        style.configure("TrayHeader.TButton",padding=(8,6))
        style.configure("TrayBody.TFrame",background="#e8e8e8")

    def build_ui(self):
        body=ttk.Frame(self.root,padding=(6,0,6,7))
        body.pack(fill="both",expand=True)
        # Independent, non-modal parameter windows.  They are created once,
        # keeping every existing Tk Variable and control alive when hidden.
        self.geometry_window=tk.Toplevel(self.root)
        self.geometry_window.transient(self.root)
        self.geometry_window.attributes('-topmost',True)
        self.geometry_window.title('Body Geometry — Modulith')
        self.geometry_window.geometry('390x690')
        self.geometry_window.minsize(320,390)
        self.geometry_window.withdraw()
        self.geometry_window.protocol('WM_DELETE_WINDOW',lambda:self._hide_parameter_window('geometry'))
        self.roof_window=tk.Toplevel(self.root)
        self.roof_window.transient(self.root)
        self.roof_window.attributes('-topmost',True)
        self.roof_window.title('Roof Editing — Modulith')
        self.roof_window.geometry('390x690')
        self.roof_window.minsize(320,390)
        self.roof_window.withdraw()
        self.roof_window.protocol('WM_DELETE_WINDOW',lambda:self._hide_parameter_window('roof'))
        fixed=ttk.Frame(self.geometry_window,style="Panel.TFrame",padding=(8,7,8,3))
        fixed.pack(side="top",fill="x")
        top_actions=ttk.Frame(fixed,style="Panel.TFrame")
        top_actions.pack(fill='x',pady=(0,5))
        ttk.Label(top_actions,text='Body Parameters',style='Heading.TLabel').pack(side='left')
        ttk.Button(top_actions,text='Close',command=lambda:self._hide_parameter_window('geometry')).pack(side='right')
        ttk.Label(fixed,text='Building Bodies',style="Heading.TLabel").pack(anchor="w",pady=(0,5))
        self.listbox=tk.Listbox(fixed,height=3,exportselection=False,activestyle="none",
                                font=("Helvetica",11),highlightthickness=0,relief="flat")
        self.listbox.pack(fill="x")
        self.listbox.bind("<<ListboxSelect>>",self.choose)
        buttons=ttk.Frame(fixed,style="Panel.TFrame")
        buttons.pack(fill="x",pady=5)
        for label,fn in (('+ Body',self.add),('Copy',self.duplicate),('Delete',self.delete)):
            ttk.Button(buttons,text=label,command=fn).pack(side="left",expand=True,fill="x")
        self.vars={}
        xy=ttk.Frame(fixed,style="Panel.TFrame");xy.pack(fill="x",pady=(1,2))
        for title,key,low,high in self.fields:
            if key not in ("x","y"):continue
            ttk.Label(xy,text=title,style="Panel.TLabel").pack(side="left",padx=(6,2))
            var=tk.IntVar(value=0);self.vars[key]=var
            spin=ttk.Spinbox(xy,from_=low,to=high,width=7,textvariable=var,command=self.changed)
            spin.pack(side="left",fill="x",expand=True,padx=(0,5))
            spin.bind("<Return>",self.changed);spin.bind("<FocusOut>",self.changed)
        self.inspector_scrolls={}
        def make_inspector(title,parent):
            # Keep original scrollable controls; only their parent changes.
            tab=ttk.Frame(parent,style="Panel.TFrame")
            tab.pack(fill="both",expand=True)
            view=tk.Frame(tab,bg="#e8e8e8")
            view.pack(fill="both",expand=True)
            scroll=tk.Scrollbar(view,orient="vertical",width=18,
                                bg="#a4afb9",troughcolor="#d1d7dd",
                                activebackground="#778b9b",relief="flat",
                                highlightthickness=0,borderwidth=1)
            scroll.pack(side="right",fill="y",padx=(3,0))
            sidebar=tk.Canvas(view,bg="#e8e8e8",highlightthickness=0,
                              bd=0,relief="flat",yscrollincrement=16)
            sidebar.pack(side="left",fill="both",expand=True)
            scroll.configure(command=sidebar.yview)
            sidebar.configure(yscrollcommand=scroll.set)
            inner=ttk.Frame(sidebar,style="Panel.TFrame",padding=(7,6,8,12))
            wid=sidebar.create_window((0,0),window=inner,anchor="nw")
            def layout_scroll(e=None,c=sidebar,w=wid):
                c.itemconfigure(w,width=max(1,c.winfo_width()-2))
                c.configure(scrollregion=c.bbox("all"))
            sidebar.bind("<Configure>",layout_scroll)
            inner.bind("<Configure>",layout_scroll)
            tab.bind("<Map>",lambda e,c=sidebar:c.after_idle(lambda:c.configure(scrollregion=c.bbox("all"))),add="+")
            self.inspector_scrolls[title]=(sidebar,scroll,inner)
            return inner
        roof_top=ttk.Frame(self.roof_window,style='Panel.TFrame',padding=(8,7,8,5))
        roof_top.pack(fill='x')
        ttk.Label(roof_top,text='Roof Parameters',style='Heading.TLabel').pack(side='left')
        ttk.Button(roof_top,text='Close',command=lambda:self._hide_parameter_window('roof')).pack(side='right')
        side=make_inspector('Geometry',self.geometry_window)
        decor_side=make_inspector('Roof Decoration',self.roof_window)
        # Roof parameters are edited in the roof window, not in the body panel.
        # Critical roof controls must be visible at the very top even on a
        # small laptop window; the remaining geometry controls scroll below.
        row=ttk.Frame(decor_side,style="Panel.TFrame")
        row.pack(fill="x",pady=(8,5))
        ttk.Label(row,text='Ridge direction',style="Panel.TLabel").pack(side="left")
        self.axis=tk.StringVar(value="X")
        axes=ttk.Combobox(row,textvariable=self.axis,values=("X","Y"),width=5,state="readonly")
        axes.pack(side="right")
        axes.bind("<<ComboboxSelected>>",self.changed)
        row=ttk.Frame(decor_side,style="Panel.TFrame")
        row.pack(fill="x",pady=(6,4))
        ttk.Label(row,text='Roof type',style="Panel.TLabel").pack(side="left")
        self.roof_type=tk.StringVar(value='Gable')
        roofs=ttk.Combobox(row,textvariable=self.roof_type,
                           values=('Gable','Hip'),
                           width=16,state="readonly")
        roofs.pack(side="right")
        roofs.bind("<<ComboboxSelected>>",self.changed)
        ttk.Separator(decor_side,orient="horizontal").pack(fill="x",pady=(5,7))
        # Other fields stay in the scrollable inspector; X/Y and the block
        # list are fixed above it and remain accessible at all times.
        for title,key,low,high in self.fields:
            if key in ("x","y"):continue
            target=decor_side if key in ("rise","ridge","overhang","thickness","eave_drop") else side
            row=ttk.Frame(target,style="Panel.TFrame");row.pack(fill="x",pady=3)
            ttk.Label(row,text=title,style="Panel.TLabel").pack(side="left")
            var=tk.IntVar(value=0);self.vars[key]=var
            spin=ttk.Spinbox(row,from_=low,to=high,width=9,textvariable=var,command=self.changed)
            spin.pack(side="right");spin.bind("<Return>",self.changed);spin.bind("<FocusOut>",self.changed)
        self.extended_gable=tk.BooleanVar(value=True)
        ttk.Checkbutton(decor_side,text='White gable up to roof overhang',
                        variable=self.extended_gable,
                        command=self.changed).pack(anchor="w",pady=4)
        self.thickness_enabled=tk.BooleanVar(value=False)
        ttk.Checkbutton(decor_side,text='Roof edge thickness (on/off)',
                        variable=self.thickness_enabled,
                        command=self.changed).pack(anchor="w",pady=4)
        ttk.Checkbutton(decor_side,text='Auto-snap (within 2 units)',variable=self.snap).pack(anchor="w",pady=4)
        ttk.Button(decor_side,text='Join roofs (with overlap)',command=self.snap_to_neighbor).pack(fill="x",pady=5)
        ttk.Separator(side,orient='horizontal').pack(fill='x',pady=(10,6))
        ttk.Label(side,text='Recess / Portico',style='Heading.TLabel').pack(anchor='w',pady=(0,4))
        ttk.Checkbutton(side,text='Cut out up to the side edges of the body',
                        variable=self.cut_to_edges).pack(anchor='w',pady=3)
        ttk.Checkbutton(side,text='Add colonnade in recess',
                        variable=self.portico_columns).pack(anchor='w',pady=3)
        portico_row=ttk.Frame(side,style='Panel.TFrame')
        portico_row.pack(fill='x',pady=3)
        ttk.Label(portico_row,text='Column count',style='Panel.TLabel').pack(side='left')
        ttk.Spinbox(portico_row,from_=1,to=12,width=6,textvariable=self.portico_count).pack(side='right')
        style_row=ttk.Frame(side,style='Panel.TFrame');style_row.pack(fill='x',pady=3)
        ttk.Label(style_row,text='Column type (1–3)',style='Panel.TLabel').pack(side='left')
        ttk.Spinbox(style_row,from_=1,to=3,width=6,textvariable=self.portico_style).pack(side='right')
        ttk.Label(side,text='Select modules, enter a negative depth and click Apply.',
                  style='Panel.TLabel',wraplength=275).pack(anchor='w',pady=(2,5))
        ttk.Label(decor_side,text='Roof colour & texture',style="Heading.TLabel").pack(anchor="w",pady=(12,5))
        roof_controls=ttk.Frame(decor_side,style="Panel.TFrame")
        roof_controls.pack(fill="x",pady=(0,4))
        self.roof_swatch=tk.Label(roof_controls,text="  ",bg=self.roof_hex(),width=4)
        self.roof_swatch.pack(side="left",padx=(0,6))
        ttk.Button(roof_controls,text='Roof palette…',command=self.pick_roof_palette).pack(side="left",expand=True,fill="x")
        ttk.Checkbutton(decor_side,text='Slope strips',variable=self.roof_lines,command=self.schedule).pack(anchor="w")
        for label,variable,low,high in (('Strip spacing (units)',self.roof_spacing,2,18),
                                         ('Darkening (%)',self.roof_opacity,5,65),
                                         ('Softness',self.roof_softness,0.1,2.0)):
            row=ttk.Frame(decor_side,style="Panel.TFrame"); row.pack(fill="x",pady=2)
            ttk.Label(row,text=label,style="Panel.TLabel").pack(side="left")
            increment=0.1 if label=='Softness' else 1
            spin=ttk.Spinbox(row,from_=low,to=high,increment=increment,width=7,textvariable=variable,command=self.schedule)
            spin.pack(side="right");spin.bind("<Return>",lambda e:self.schedule());spin.bind("<FocusOut>",lambda e:self.schedule())
        ttk.Label(decor_side,text='Roof Elements',style="Heading.TLabel").pack(anchor="w",pady=(12,5))
        self.accessory_list=tk.Listbox(decor_side,height=3,exportselection=False,font=("Helvetica",10))
        self.accessory_list.pack(fill="x",pady=3)
        self.accessory_list.bind("<<ListboxSelect>>",self.select_accessory)
        ar=ttk.Frame(decor_side,style="Panel.TFrame");ar.pack(fill="x",pady=3)
        ttk.Button(ar,text='+ Dormer',command=lambda:self.add_accessory('Dormer')).pack(side="left",expand=True,fill="x")
        ttk.Button(ar,text='+ Chimney',command=lambda:self.add_accessory('Chimney')).pack(side="left",expand=True,fill="x")
        ar=ttk.Frame(decor_side,style="Panel.TFrame");ar.pack(fill="x",pady=(0,5))
        ttk.Button(ar,text='Copy',command=self.duplicate_accessory).pack(side="left",expand=True,fill="x")
        ttk.Button(ar,text='Delete',command=self.delete_accessory).pack(side="left",expand=True,fill="x")
        self.accessory_vars={}
        for title,key,lo,hi in (('Body (No.)',"parent",1,20),
                                 ('Along ridge (%)',"along",0,100),
                                 ('Along slope (%)',"slope",0,100),
                                 ('Width',"width",3,50),
                                 ('Depth',"depth",3,40),
                                 ('Height',"height",3,60),
                                 ('Mini roof height',"roof_rise",1,25),
                                 ('Repeats along ridge',"repeat_along",1,12),
                                 ('Rows along slope',"repeat_slope",1,6),
                                 ('Along gap (+)',"gap_along",0,60),
                                 ('Slope gap (+)',"gap_slope",0,40)):
            row=ttk.Frame(decor_side,style="Panel.TFrame");row.pack(fill="x",pady=2)
            ttk.Label(row,text=title,style="Panel.TLabel").pack(side="left")
            var=tk.IntVar(value=lo);self.accessory_vars[key]=var
            sp=ttk.Spinbox(row,from_=lo,to=hi,width=8,textvariable=var,command=self.change_accessory)
            sp.pack(side="right");sp.bind("<Return>",self.change_accessory);sp.bind("<FocusOut>",self.change_accessory)
        row=ttk.Frame(decor_side,style="Panel.TFrame");row.pack(fill="x",pady=3)
        ttk.Label(row,text='Slope side',style="Panel.TLabel").pack(side="left")
        self.accessory_side=tk.StringVar(value='Right / far')
        comb=ttk.Combobox(row,textvariable=self.accessory_side,
                          values=('Left / near','Right / far'),state="readonly",width=19)
        comb.pack(side="right");comb.bind("<<ComboboxSelected>>",self.change_accessory)
        row=ttk.Frame(decor_side,style="Panel.TFrame");row.pack(fill="x",pady=3)
        ttk.Label(row,text='Dormer window variant',style="Panel.TLabel").pack(side="left")
        self.accessory_window_variant=tk.IntVar(value=1)
        cb=ttk.Combobox(row,textvariable=self.accessory_window_variant,
                        values=(1,2),state="readonly",width=5)
        cb.pack(side="right");cb.bind("<<ComboboxSelected>>",self.change_accessory)
        ttk.Button(decor_side,text='Edit dormer window…',command=self.edit_dormer_window).pack(fill="x",pady=(3,4))

        ttk.Label(side,text='Examples',style="Heading.TLabel").pack(anchor="w",pady=(9,4))
        presets=ttk.Frame(side,style="Panel.TFrame")
        presets.pack(fill="x")
        for label,code in (('Single',"I"),('L',"L"),('T',"T"),("+","+")):
            ttk.Button(presets,text=label,command=lambda s=code:self.preset(s)).pack(side="left",expand=True,fill="x")

        # Canvas-like scroll panes need their scrollregion updated after Tk
        # has laid out the active notebook page, not only on inner resize.
        for sc,bar,inner in self.inspector_scrolls.values():
            sc.after_idle(lambda c=sc:c.configure(scrollregion=c.bbox('all')))

        # A Tk Canvas does not automatically receive wheel events from its
        # embedded labels, buttons, spinboxes and comboboxes. macOS sends these
        # events to the pointed-at child, so forward them to the active canvas.
        def inspector_wheel(event):
            hovered=self.root.winfo_containing(event.x_root,event.y_root)
            if hovered is None:return
            for name,(scroll_canvas,_,inner) in self.inspector_scrolls.items():
                widget=hovered
                while widget is not None:
                    if widget is scroll_canvas or widget is inner:
                        if event.num==4:steps=-3
                        elif event.num==5:steps=3
                        else:
                            delta=getattr(event,"delta",0)
                            if not delta:return
                            steps=(-1 if delta>0 else 1)*max(1,min(6,round(abs(delta)/120)))
                        scroll_canvas.yview_scroll(steps,"units")
                        return "break"
                    widget=getattr(widget,"master",None)
        self.root.bind_all("<MouseWheel>",inspector_wheel,add="+")
        self.root.bind_all("<Button-4>",inspector_wheel,add="+")
        self.root.bind_all("<Button-5>",inspector_wheel,add="+")

        context=ttk.Frame(body,style="Panel.TFrame",padding=(4,2,4,1))
        # The floating context canvas now occupies the scene corner; its
        # old inspector container is kept hidden for label compatibility.
        context.pack_forget()
        self.context_title=ttk.Label(context,text='Roof Plan',style="Heading.TLabel")
        self.context_title.pack(anchor="w",pady=(0,5))
        # Roof/plan context view lives over the main scene, not in the inspector.
        # The old sidebar canvas is intentionally not created here.
        self._wall_preview_regions=[]
        self.context_caption=ttk.Label(context,text='Select an item',style="Panel.TLabel",wraplength=200,justify="left")
        self.context_caption.pack_forget()
        # A compact, SketchUp-like tray keeps key controls available without
        # wasting the whole left side on a permanently expanded editor.
        self._build_default_tray(body)
        # Editing remains accessible in scrollable object properties.
        right=ttk.Frame(body,style="Panel.TFrame",padding=0)
        right.pack(side="left",fill="both",expand=True)
        # Initialise image references and toolbar state before creating buttons.
        # Tk PhotoImage references must remain alive for the lifetime of the UI.
        self.tool_mode=tk.StringVar(value="select")
        self._toolbar_buttons={}
        self._toolbar_images={}
        icon_row=ttk.Frame(right,style="Toolbar.TFrame",padding=(2,3))
        icon_row.pack(fill="x",pady=(0,2))
        self._build_icon_toolbar(icon_row)
        # Compact icon toolbar owns the formerly duplicated action controls.
        # The numerical edit-depth variable remains available in its popup.
        self.preview_zoom=tk.DoubleVar(value=1.0)
        self.zoom_label=ttk.Label(right,text='Auto',style="Toolbar.TLabel")
        self.zoom_label.pack_forget()
        # Rotation has a separate row beneath the extrusion controls; it
        # must never be pushed off-screen by the large edit buttons above.
        rotation_bar=ttk.Frame(right,style="Toolbar.TFrame",padding=(2,1))
        self.rotation_bar=rotation_bar
        rotation_bar.pack(fill="x",pady=(0,6))
        ttk.Label(rotation_bar,text='Rotation',style="Toolbar.TLabel").pack(side="left",padx=(6,10))
        self.angle_var=tk.IntVar(value=0)
        self.angle_slider=ttk.Scale(rotation_bar,from_=-12,to=12,
                                   orient="horizontal",command=self.slide_rotation)
        self.angle_slider.pack(side="left",fill="x",expand=True,padx=(4,12))
        self.angle_label=ttk.Label(rotation_bar,text="0°",style="Toolbar.TLabel",width=5)
        self.angle_label.pack(side="left",padx=(2,8))
        self.angle_slider.set(0)
        self.status=ttk.Label(right,text="",style="Panel.TLabel",anchor='w',justify='left')
        self.status.pack(side='bottom',fill='x',padx=(6,4),pady=(4,0))
        self.canvas=tk.Canvas(right,bg="#505357",highlightthickness=0,cursor="arrow")
        self.canvas.pack(fill="both",expand=True)
        self.context_canvas=tk.Canvas(self.canvas,width=206,height=182,bg="#505357",
                                      highlightthickness=1,highlightbackground="#a3a7aa")
        self._floating_context_id=self.canvas.create_window(0,0,window=self.context_canvas,anchor='ne',width=206,height=182)
        self.context_canvas.bind('<Button-1>',self.plan_press)
        self.context_canvas.bind('<B1-Motion>',self.plan_motion)
        self.context_canvas.bind('<Configure>',lambda e:self.update_context_preview(),add='+')
        def position_context(event):
            self.canvas.coords(self._floating_context_id,event.width-10,12)
        self.canvas.bind('<Configure>',position_context,add='+')
        self.canvas.bind("<Configure>",lambda e:self.schedule())
        self.canvas.bind("<MouseWheel>",self.preview_wheel)
        self.canvas.bind("<Button-4>",lambda e:self.change_zoom(.12,(e.x,e.y)))
        self.canvas.bind("<Button-5>",lambda e:self.change_zoom(-.12,(e.x,e.y)))
        self.canvas.bind("<ButtonPress-1>",self.scene_press)
        self.canvas.bind("<B1-Motion>",self.scene_motion)
        self.canvas.bind("<ButtonRelease-1>",self.scene_release)
        self.canvas.bind("<ButtonPress-2>",self.pan_start)
        self.canvas.bind("<B2-Motion>",self.pan_motion)
        self.canvas.bind("<ButtonPress-3>",self.pan_start)
        self.canvas.bind("<B3-Motion>",self.pan_motion)
        self.canvas.bind("<Shift-MouseWheel>",self.trackpad_pan)
        self.canvas.bind("<Control-MouseWheel>",self.trackpad_zoom)
        self.canvas.bind("<Command-MouseWheel>",self.trackpad_zoom)
        self.canvas.bind("<Control-Button-4>",lambda e:self.change_zoom(.12))
        self.canvas.bind("<Control-Button-5>",lambda e:self.change_zoom(-.12))
        for sequence,name in self.canvas_shortcut_bind_pending:
            self.canvas.bind(sequence,lambda e,n=name:self._toolbar_shortcut(n),add='+')
        self.canvas.bind('<Button-1>',lambda e:self.canvas.focus_set(),add='+')
        self.preview_pan=[0,0]
        self._pivot_screen=None
        self._scene_origin=None
        self._drag_accessory=None
        self._plan_transform=None
        self._plan_drag=False
        self._last_zoom_pointer=None
        self._drag_preview_id=None
        self.update_context_preview()
        self._update_bottom_status()

    def _build_default_tray(self,parent):
        host=ttk.Frame(parent,style='Tray.TFrame',width=315,padding=(0,0,8,0))
        host.pack(side='left',fill='y')
        host.pack_propagate(False)
        self.tray_host=host
        ttk.Label(host,text='Default Tray',style='Heading.TLabel').pack(anchor='w',padx=8,pady=(2,4))
        outer=ttk.Frame(host,style='Tray.TFrame')
        outer.pack(fill='both',expand=True)
        canvas=tk.Canvas(outer,bg='#dddddd',highlightthickness=0,borderwidth=0)
        canvas.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(outer,orient='vertical',command=canvas.yview)
        scroll.pack(side='right',fill='y')
        canvas.configure(yscrollcommand=scroll.set)
        inner=ttk.Frame(canvas,style='Tray.TFrame',padding=(6,4,6,6))
        win=canvas.create_window((0,0),window=inner,anchor='nw')
        inner.bind('<Configure>',lambda e:(canvas.itemconfigure(win,width=max(1,canvas.winfo_width()-2)),canvas.configure(scrollregion=canvas.bbox('all'))))
        canvas.bind('<Configure>',lambda e:(canvas.itemconfigure(win,width=max(1,e.width-2)),canvas.configure(scrollregion=canvas.bbox('all'))))
        self.tray_canvas=canvas
        self.tray_inner=inner
        self._tray_sections={}
        body=self._add_tray_section(inner,'body','Body size')
        cols=self._add_tray_section(inner,'columns','Columns tool')
        roof=self._add_tray_section(inner,'roof','Roof tools')
        self._build_body_tray(body)
        self._build_columns_tray(cols)
        self._build_roof_tray(roof)
        for key in ('body','columns','roof'):
            self._toggle_tray_section(key,False)

    def _add_tray_section(self,parent,key,title):
        frame=ttk.Frame(parent,style='Tray.TFrame')
        frame.pack(fill='x',pady=(0,6))
        head=tk.Button(frame,text='▸ '+title,anchor='w',relief='raised',bd=1,
                       bg='#eff1f2',activebackground='#d7e9f1',cursor='hand2',
                       command=lambda k=key:self._toggle_tray_section(k))
        head.pack(fill='x')
        body=ttk.Frame(frame,style='TrayBody.TFrame',padding=(8,7,8,8),relief='solid',borderwidth=1)
        self._tray_sections[key]={'button':head,'body':body,'open':False,'title':title}
        return body

    def _toggle_tray_section(self,key,state=None):
        section=self._tray_sections.get(key)
        if not section:return
        open_now=(not section['open']) if state is None else bool(state)
        section['open']=open_now
        section['button'].configure(text=('▾ ' if open_now else '▸ ')+section['title'])
        if open_now:
            section['body'].pack(fill='x')
        else:
            section['body'].pack_forget()
        if hasattr(self,'tray_canvas'):
            self.tray_canvas.after_idle(lambda:self.tray_canvas.configure(scrollregion=self.tray_canvas.bbox('all')))

    def _tray_number_row(self,parent,label,var,low,high,command=None,width=7):
        row=ttk.Frame(parent,style='TrayBody.TFrame')
        row.pack(fill='x',pady=2)
        ttk.Label(row,text=label,style='Panel.TLabel').pack(side='left')
        spin=ttk.Spinbox(row,from_=low,to=high,width=width,textvariable=var,command=command or self.changed)
        spin.pack(side='right')
        spin.bind('<Return>',command or self.changed)
        spin.bind('<FocusOut>',command or self.changed)
        return spin

    def _build_body_tray(self,parent):
        ttk.Label(parent,text='Building Bodies',style='Heading.TLabel').pack(anchor='w',pady=(0,4))
        self.tray_listbox=tk.Listbox(parent,height=4,exportselection=False,activestyle='none',font=('Helvetica',10),highlightthickness=0,relief='flat')
        self.tray_listbox.pack(fill='x')
        self.tray_listbox.bind('<<ListboxSelect>>',self._tray_choose)
        self.listbox.bind('<<ListboxSelect>>',self._sync_tray_listbox,add='+')
        self._sync_tray_listbox()
        actions=ttk.Frame(parent,style='TrayBody.TFrame'); actions.pack(fill='x',pady=5)
        for label,fn in (('+ Body',self.add),('Copy',self.duplicate),('Delete',self.delete)):
            ttk.Button(actions,text=label,command=fn).pack(side='left',fill='x',expand=True,padx=1)
        ttk.Separator(parent,orient='horizontal').pack(fill='x',pady=5)
        for title,key,low,high in self.fields:
            if key in ('x','y','w','d','h'):
                self._tray_number_row(parent,title,self.vars[key],low,high,self.changed)
        ttk.Button(parent,text='Open full body parameters…',command=self._toolbar_body_size).pack(fill='x',pady=(7,2))
        ttk.Label(parent,text='Basic dimensions are shown here. Full geometry and position are also available via the top toolbar.',style='Panel.TLabel',wraplength=255,justify='left').pack(anchor='w',pady=(2,0))

    def _build_columns_tray(self,parent):
        ttk.Checkbutton(parent,text='Cut out up to the side edges of the body',variable=self.cut_to_edges,command=self.schedule).pack(anchor='w',pady=2)
        ttk.Checkbutton(parent,text='Add colonnade in recess',variable=self.portico_columns,command=self._tray_columns_changed).pack(anchor='w',pady=2)
        self._tray_number_row(parent,'Column count',self.portico_count,1,12,self._tray_columns_changed,width=6)
        self._tray_number_row(parent,'Column type (1–3)',self.portico_style,1,3,self._tray_columns_changed,width=6)
        ttk.Button(parent,text='Apply extrusion',command=self.apply_selected_wall_edit).pack(fill='x',pady=(7,2))
        ttk.Button(parent,text='Open full body parameters…',command=self._toolbar_body_size).pack(fill='x',pady=(0,2))
        ttk.Label(parent,text='Columns and portico settings apply to the selected recesses of this body.',style='Panel.TLabel',wraplength=255,justify='left').pack(anchor='w',pady=(2,0))

    def _build_roof_tray(self,parent):
        row=ttk.Frame(parent,style='TrayBody.TFrame'); row.pack(fill='x',pady=(0,2))
        ttk.Label(row,text='Ridge direction',style='Panel.TLabel').pack(side='left')
        axes=ttk.Combobox(row,textvariable=self.axis,values=('X','Y'),width=6,state='readonly')
        axes.pack(side='right'); axes.bind('<<ComboboxSelected>>',self.changed)
        row=ttk.Frame(parent,style='TrayBody.TFrame'); row.pack(fill='x',pady=2)
        ttk.Label(row,text='Roof type',style='Panel.TLabel').pack(side='left')
        roofs=ttk.Combobox(row,textvariable=self.roof_type,values=('Gable','Hip'),width=16,state='readonly')
        roofs.pack(side='right'); roofs.bind('<<ComboboxSelected>>',self.changed)
        for title,key,low,high in self.fields:
            if key in ('rise','ridge','overhang','thickness','eave_drop'):
                self._tray_number_row(parent,title,self.vars[key],low,high,self.changed)
        ttk.Checkbutton(parent,text='White gable up to roof overhang',variable=self.extended_gable,command=self.changed).pack(anchor='w',pady=2)
        ttk.Checkbutton(parent,text='Roof edge thickness',variable=self.thickness_enabled,command=self.changed).pack(anchor='w',pady=2)
        ttk.Checkbutton(parent,text='Slope strips',variable=self.roof_lines,command=self.schedule).pack(anchor='w',pady=2)
        ttk.Button(parent,text='Roof palette…',command=self.pick_roof_palette).pack(fill='x',pady=(6,2))
        ttk.Button(parent,text='Open full roof settings…',command=self._toolbar_roof_settings).pack(fill='x',pady=(0,2))

    def _tray_columns_changed(self,event=None):
        self._update_bottom_status()
        self.schedule()

    def _tray_choose(self,event=None):
        if not hasattr(self,'tray_listbox'): return
        selected=self.tray_listbox.curselection()
        if selected:
            self.listbox.selection_clear(0,'end')
            self.listbox.selection_set(selected[0])
            self.listbox.activate(selected[0])
            self.choose()

    def _sync_tray_listbox(self,event=None):
        if not hasattr(self,'tray_listbox') or not hasattr(self,'listbox'): return
        try:
            values=self.listbox.get(0,'end')
            current=self.tray_listbox.get(0,'end')
            if tuple(values)!=tuple(current):
                self.tray_listbox.delete(0,'end')
                for value in values:self.tray_listbox.insert('end',value)
            sel=self.listbox.curselection()
            self.tray_listbox.selection_clear(0,'end')
            if sel:
                self.tray_listbox.selection_set(sel[0])
                self.tray_listbox.activate(sel[0])
        except tk.TclError:
            pass

    def _update_bottom_status(self):
        if not hasattr(self,'status'): return
        if not getattr(self,'blocks',None):
            self.status.configure(text='Volume editor: no bodies')
            return
        try:
            b=self.blocks[self.active]
        except Exception:
            self.status.configure(text=f'Bodies: {len(self.blocks)}')
            return
        mode=self.tool_mode.get()
        mode_label={'select':'Selection','extrude':'Extrusion','pan':'Hand','zoom':'Magnifier'}.get(mode,mode)
        roof=f"{b.roof_type} / ridge {b.axis}"
        text=(f"Body {self.active+1}: X {b.x} · Y {b.y} · size {b.w}×{b.d} · height {b.h} · "
              f"roof {roof} · mode: {mode_label} · angle {self.angle}°")
        if self.module_select_mode.get():
            scope={'single':'cell','row':'column','column':'column'}.get(self.cell_select_scope.get(),self.cell_select_scope.get())
            text+=f" · selection: {scope}"
        if self.selected_modules:
            text+=f" · selected cells: {len(self.selected_modules)}"
        if self.portico_columns.get():
            text+=f" · columns: {self.portico_count.get()}"
        if self.cast_shadow.get():
            text+=' · shadows: on'
        if getattr(self,'geometry_window',None) is not None and self.geometry_window.state()!='withdrawn':
            text+=' · body panel open'
        if getattr(self,'roof_window',None) is not None and self.roof_window.state()!='withdrawn':
            text+=' · roof panel open'
        self.status.configure(text=text)

    def _build_icon_toolbar(self, parent):
        """Responsive icon palette, typically two rows, with contextual menus."""
        self._toolbar_host=parent
        self._toolbar_grid=ttk.Frame(parent,style='Toolbar.TFrame')
        self._toolbar_grid.pack(side='top',anchor='w',fill='x')
        items=(
            ('pan','Hand — pan scene (H)',lambda:self._toolbar_mode('pan')),
            ('orbit','Orbit view (R)',lambda:self._toolbar_popup((('Rotate 15° right',lambda:self.rotate(15)),('Rotate 15° left',lambda:self.rotate(-15))), 'orbit')),
            ('cell','Select cell, row or column (V)',self._toolbar_cell_popup),
            ('extrude','Extrude / Recess (E)',self._toolbar_extrude_popup),
            ('shift_extrude','Keep rear face — coming soon',None),
            ('split_horizontal','Split horizontally — coming soon',None),
            ('split_vertical','Split vertically — coming soon',None),
            ('merge','Merge cells — coming soon',None),
            ('undo','Undo projection / recess (⌘Z)',self.undo_wall_edit),
            ('redo','Redo projection (⌘⇧Z)',self.redo_wall_edit),
            ('add_item','Add item…',self._toolbar_add_popup),
            ('remove_item','Remove item…',self._toolbar_delete_popup),
            ('zoom_tool','Magnifier — click to zoom (Z)',lambda:self._toolbar_mode('zoom')),
            ('cast_shadow','Cast Shadows',self._toolbar_toggle_shadow),
            ('confirm','Apply selected extrusion',self.apply_selected_wall_edit),
            ('body_size','Body Dimensions',self._toolbar_body_size),
            ('roof_settings','Roof Settings',self._toolbar_roof_settings),
            ('columns_tool','Columns in recess',self._toolbar_columns_popup),
            ('palette','Facade Colours',self._toolbar_palette),
        )
        self._toolbar_items=[]
        for name,tip,command in items:
            path=Path(__file__).resolve().parent/'library'/'toolbar'/(name+'.png')
            if not path.exists():continue
            with Image.open(path) as source:
                icon=thumbnail(source,31)
            photo=ImageTk.PhotoImage(icon,master=parent)
            self._toolbar_images[name]=photo
            btn=tk.Button(self._toolbar_grid,image=photo,width=36,height=36,relief='flat',bd=1,
                          bg='#ebeff0',activebackground='#c7dfe7',
                          cursor='hand2' if command else 'arrow',
                          command=command,state='normal' if command else 'disabled')
            self._toolbar_buttons[name]=btn
            self._toolbar_items.append((name,btn))
            btn.bind('<Enter>',lambda e,t=tip:self._toolbar_hint.configure(text=t))
            btn.bind('<Leave>',lambda e:self._toolbar_hint.configure(text=''))
            attach_tooltip(btn,tip)
            # Right-click opens a menu for multi-action tools; left-click
            # continues to perform single-click actions normally.
            if name in ('orbit','extrude','body_size','roof_settings','columns_tool'):
                btn.bind('<Button-3>',lambda e,fn=command:fn())
        self._toolbar_hint=ttk.Label(parent,text='',style='Toolbar.TLabel')
        self._toolbar_hint.pack(side='top',fill='x',anchor='w',padx=5)
        self._toolbar_columns_visible=0
        self._toolbar_reflow(780)
        parent.bind('<Configure>',lambda e:self._toolbar_reflow(e.width),add='+')
        self.module_select_mode.trace_add('write',lambda *_:self._sync_toolbar())
        self.tool_mode.trace_add('write',lambda *_:self._sync_toolbar())
        self.cast_shadow.trace_add('write',lambda *_:self._sync_toolbar())
        self.portico_columns.trace_add('write',lambda *_:self._sync_toolbar())
        self.show_iso_grid.trace_add('write',lambda *_:self.schedule())
        self._sync_toolbar()
        for sequence,name in (('<KeyPress-v>','select'),('<KeyPress-V>','select'),
                              ('<KeyPress-e>','extrude'),('<KeyPress-E>','extrude'),
                              ('<KeyPress-r>','orbit'),('<KeyPress-R>','orbit'),
                              ('<KeyPress-h>','pan'),('<KeyPress-H>','pan'),
                              ('<KeyPress-z>','zoom_tool'),('<KeyPress-Z>','zoom_tool'),
                              ('<Command-z>','undo'),('<Control-z>','undo'),
                              ('<Command-Shift-Z>','redo'),('<Control-Shift-Z>','redo')):
            self.canvas_shortcut_bind_pending=getattr(self,'canvas_shortcut_bind_pending',[])
            self.canvas_shortcut_bind_pending.append((sequence,name))

    def _toolbar_reflow(self,width):
        # Each 40px slot includes its horizontal padding. Never let an icon
        # leave the visible canvas; columns adapt to the available width.
        count=max(1,min(12,len(self._toolbar_items),int(max(1,width-8)//42)))
        if count==self._toolbar_columns_visible:return
        self._toolbar_columns_visible=count
        for _,btn in self._toolbar_items:btn.grid_forget()
        for i,(_,btn) in enumerate(self._toolbar_items):
            btn.grid(row=i//count,column=i%count,padx=1,pady=1,sticky='w')

    def _toolbar_cell_popup(self):
        self._toolbar_mode('select')
        menu=tk.Menu(self.root,tearoff=False)
        for value,label in (('single','Select one cell'),('row','Select entire horizontal row'),('column','Select entire vertical column')):
            menu.add_radiobutton(label=label,variable=self.cell_select_scope,value=value,command=self._sync_toolbar)
        menu.add_separator()
        self._toolbar_show_menu(menu,'cell')

    def _toolbar_open_facade(self):
        callback=getattr(self,'on_open_facade',None)
        if callable(callback):callback()

    def _toolbar_extrude_popup(self):
        self._toolbar_mode('extrude')
        menu=tk.Menu(self.root,tearoff=False)
        menu.add_command(label='Apply selected projection / recess',command=self.apply_selected_wall_edit)
        menu.add_separator()
        menu.add_command(label='Depth +1',command=lambda:self.edit_depth.set(self.edit_depth.get()+1))
        menu.add_command(label='Depth −1',command=lambda:self.edit_depth.set(self.edit_depth.get()-1))
        menu.add_separator()
        menu.add_command(label='Open extrusion settings',command=self._toolbar_body_size)
        self._toolbar_show_menu(menu,'extrude')



    def _toolbar_columns_popup(self):
        self._toolbar_popup(((('Disable columns' if self.portico_columns.get() else 'Enable columns'),self._toolbar_columns),
                             ('Open colonnade settings',self._toolbar_body_size)), 'columns_tool')

    def _toolbar_show_menu(self,menu,name):
        btn=(getattr(self,'external_toolbar_buttons',{}).get(name)
             or self._toolbar_buttons.get(name))
        if btn is not None:
            try:menu.tk_popup(btn.winfo_rootx(),btn.winfo_rooty()+btn.winfo_height())
            finally:menu.grab_release()

    def _toolbar_mode(self,name):
        if name=='select':
            self.module_select_mode.set(True)
            self.tool_mode.set('select')
            self._toggle_module_mode()
        elif name in ('pan','zoom'):
            self.module_select_mode.set(False)
            self.tool_mode.set(name)
            self._toggle_module_mode()
        elif name=='extrude':
            self.module_select_mode.set(True)
            self.tool_mode.set('extrude')
            self._toggle_module_mode()
        self._sync_toolbar()
        self._update_bottom_status()

    def _toolbar_shortcut(self,name):
        if name=='orbit':self.rotate(15)
        elif name=='undo':self.undo_wall_edit()
        elif name=='redo':self.redo_wall_edit()
        elif name=='zoom_tool':self._toolbar_mode('zoom')
        else:self._toolbar_mode(name)
        return 'break'

    def _sync_toolbar(self):
        buttons=getattr(self,'_toolbar_buttons',{})
        active=self.tool_mode.get()
        for name,button in buttons.items():
            if name in ('cell','extrude','pan','zoom_tool'):
                selected=((name in ('select','cell') and active=='select' and self.module_select_mode.get())
                          or (name=='extrude' and active=='extrude' and self.module_select_mode.get())
                          or (name=='pan' and active=='pan')
                          or (name=='zoom_tool' and active=='zoom'))
                button.configure(relief='sunken' if selected else 'flat',
                                 bg='#b8dde8' if selected else '#ebeff0')
            elif name=='cell':
                button.configure(relief='sunken' if self.module_select_mode.get() else 'raised',bg='#b8dde8' if self.module_select_mode.get() else '#ebeff0')
            elif name=='cast_shadow':
                button.configure(relief='sunken' if self.cast_shadow.get() else 'flat',
                                 bg='#b8dde8' if self.cast_shadow.get() else '#ebeff0')
            elif name=='columns_tool':
                button.configure(relief='sunken' if self.portico_columns.get() else 'flat',
                                 bg='#b8dde8' if self.portico_columns.get() else '#ebeff0')

    def _toolbar_toggle_shadow(self):
        self.cast_shadow.set(not self.cast_shadow.get())
        self._sync_toolbar()
        self._update_bottom_status()
        self.schedule()

    def _hide_parameter_window(self,which):
        window=self.geometry_window if which=='geometry' else self.roof_window
        window.withdraw()
        self._sync_parameter_window_buttons()
        self._update_bottom_status()

    def _show_parameter_window(self,which):
        window=self.geometry_window if which=='geometry' else self.roof_window
        if window.state()=='withdrawn':
            # Place alongside the main program, keeping the workspace usable.
            self.root.update_idletasks()
            screen_w=window.winfo_screenwidth()
            x=max(0,min(screen_w-390,self.root.winfo_rootx()+85))
            y=max(25,self.root.winfo_rooty()+95)
            window.geometry(f'+{x}+{y}')
            window.deiconify()
        window.attributes('-topmost',True)
        window.lift()
        window.focus_set()
        self._sync_parameter_window_buttons()
        self._update_bottom_status()

    def _sync_parameter_window_buttons(self):
        for which,key in (('geometry','body_size'),('roof','roof_settings')):
            window=self.geometry_window if which=='geometry' else self.roof_window
            active=window.state()!='withdrawn'
            for btn in (self._toolbar_buttons.get(key),
                        getattr(self,'external_toolbar_buttons',{}).get(key)):
                if btn is not None:
                    btn.configure(relief='sunken' if active else 'raised',
                                  bg='#a5d2e7' if active else '#edf0f1',
                                  highlightthickness=2 if active else 0,
                                  highlightbackground='#397b9b')

    def _toolbar_body_size(self):
        self._show_parameter_window('geometry')
        sidebar=self.inspector_scrolls.get('Geometry')
        if sidebar: sidebar[0].yview_moveto(0.0)

    def _toolbar_open_module(self):
        callback=getattr(self,'on_open_module',None)
        if callable(callback):callback()

    def _toolbar_module_view(self,mode):
        callback=getattr(self,'on_module_view',None)
        if callable(callback):callback(mode)

    def _toolbar_palette(self):
        callback=getattr(self,'on_open_palette',None)
        if callable(callback):callback()
        else:self.pick_roof_palette()

    def _toolbar_popup(self, actions, widget_name):
        menu=tk.Menu(self.root,tearoff=False)
        for title,action in actions:
            menu.add_command(label=title,command=action)
        btn=self._toolbar_buttons.get(widget_name)
        if btn is not None:
            self._toolbar_show_menu(menu,widget_name)

    def _toolbar_add_popup(self):
        self._toolbar_popup((('Add body',self.add),
                             ('Add dormer',lambda:self.add_accessory('Dormer')),
                             ('Add chimney',lambda:self.add_accessory('Chimney'))), 'add_item')

    def _toolbar_delete_popup(self):
        self._toolbar_popup((('Delete selected body',self.delete),
                             ('Delete selected roof item',self.delete_accessory),
                             ('Undo last projection / recess',self.undo_wall_edit)), 'remove_item')

    def _toolbar_roof_settings(self):
        self._show_parameter_window('roof')

    def _toolbar_columns(self):
        # Columns are currently tied to an inset niche, not freestanding objects.
        self._show_parameter_window('geometry')
        self.portico_columns.set(not self.portico_columns.get())
        self._sync_toolbar()
        # Existing column count/style controls remain in the Geometry inspector.
        # Avoid modal dialogs interrupting the editing workflow.
        self._toolbar_hint.configure(text=('Colonnade enabled for next recess' if self.portico_columns.get()
                                           else 'Colonnade disabled'))

    def slide_rotation(self,value):
        angle=(int(round(float(value)))%24)*15
        if angle!=self.angle:
            self.angle=angle
            self.angle_label.configure(text=f"{angle}°")
            if hasattr(self,"bridge_angle_label"):
                self.bridge_angle_label.configure(text=f"{angle}°")
            if hasattr(self,"bridge_angle_slider") and self.bridge_angle_slider is not getattr(self,"_active_rotation_source",None):
                if abs(self.bridge_angle_slider.get()-float(value))>0.1:
                    self.bridge_angle_slider.set(float(value))
            if callable(getattr(self,"rotation_callback",None)):self.rotation_callback()
            self.schedule()

    def _roof_plan_footprint(self,obj):
        """Match the same clamped roof footprint used by accessory_mesh."""
        if not self.blocks or not 0<=obj.parent<len(self.blocks):return None
        b=self.blocks[obj.parent]
        length=b.w if b.axis=='X' else b.d
        span=b.d if b.axis=='X' else b.w
        width=max(3,min(float(obj.width),length*.7))
        depth=max(3,min(float(obj.depth),span*.44))
        along=max(.05,min(.95,obj.along/100))
        slope=max(.15,min(.85,obj.slope/100))
        ridge=(b.x+b.w*along) if b.axis=='X' else (b.y+b.d*along)
        mid=(b.y+b.d/2) if b.axis=='X' else (b.x+b.w/2)
        sign=1 if obj.side else -1
        center=mid+sign*slope*(span/2)
        low=b.y if b.axis=='X' else b.x
        center=max(low+depth/2+1,min(low+span-depth/2-1,center))
        if b.axis=='X':return (ridge-width/2,center-depth/2,ridge+width/2,center+depth/2)
        return (center-depth/2,ridge-width/2,center+depth/2,ridge+width/2)

    def _roof_plan_point(self,obj):
        fp=self._roof_plan_footprint(obj)
        return ((fp[0]+fp[2])/2,(fp[1]+fp[3])/2) if fp else None

    def update_context_preview(self):
        if not hasattr(self,'context_canvas'):return
        c=self.context_canvas
        # A camera pan/zoom never changes the roof plan or its selection.
        # Avoid rebuilding all Tk canvas items and resized facade sprites
        # unless the underlying plan/selection, wall art, or canvas size changed.
        context_key=(max(200,c.winfo_width()),max(180,c.winfo_height()),
                     self.active,self.accessory_active,self.module_select_mode.get(),
                     tuple(sorted(self.selected_modules)),
                     tuple(repr(asdict(b)) for b in self.blocks),
                     tuple(repr(asdict(a)) for a in self.roof_accessories),
                     tuple((wall,id(pair.get('front'))) for wall,pair in sorted(self.wall_facades.items())),
                     id(self.facade_front),repr(self.module_layout),repr(self.wall_layouts))
        if context_key==getattr(self,'_context_preview_key',None):return
        self._context_preview_key=context_key
        c.delete('all')
        self._wall_preview_regions=[]
        if not self.blocks:return
        if self.module_select_mode.get() and self.selected_modules:
            self._draw_wall_context()
            return
        index=(self.roof_accessories[self.accessory_active].parent
               if self.roof_accessories and self.accessory_active<len(self.roof_accessories)
               else self.active)
        index=max(0,min(len(self.blocks)-1,index));b=self.blocks[index]
        pw=max(200,c.winfo_width());ph=max(180,c.winfo_height())
        for x in range(0,pw,16):c.create_line(x,0,x,ph,fill='#676b70')
        for y in range(0,ph,16):c.create_line(0,y,pw,y,fill='#676b70')
        sc=min((pw-55)/max(1,b.w),(ph-55)/max(1,b.d))
        ox=pw/2-b.w*sc/2;oy=ph/2-b.d*sc/2
        self._plan_transform=(ox,oy,sc,index)
        c.create_rectangle(ox,oy,ox+b.w*sc,oy+b.d*sc,fill='#55585c',outline='#c1c5c9',width=2)
        if b.axis=='X':
            y=oy+b.d*sc/2
            c.create_line(ox,y,ox+b.w*sc,y,fill='#9ba8b8',dash=(4,3),width=2)
        else:
            x=ox+b.w*sc/2
            c.create_line(x,oy,x,oy+b.d*sc,fill='#9ba8b8',dash=(4,3),width=2)
        for i,a in enumerate(self.roof_accessories):
            if a.parent!=index:continue
            for instance in expanded_accessories(self.blocks,[a]):
                pp=self._roof_plan_point(instance)
                if pp:
                    x=ox+(pp[0]-b.x)*sc;y=oy+(pp[1]-b.y)*sc
                    fp=self._roof_plan_footprint(instance)
                    rw=max(3,(fp[2]-fp[0])*sc/2)
                    rd=max(3,(fp[3]-fp[1])*sc/2)
                    colour='#377cc9' if i==self.accessory_active else '#899da9'
                    c.create_rectangle(x-rw,y-rd,x+rw,y+rd,outline=colour,width=2)
                    c.create_line(x-5,y,x+5,y,fill=colour,width=2)
                    c.create_line(x,y-5,x,y+5,fill=colour,width=2)
        if self.roof_accessories:
            a=self.roof_accessories[self.accessory_active]
            c.create_text(12,12,text=f'Along {a.along}% · slope {a.slope}%',
                          anchor='nw',fill='#e2e6ea',font=('Helvetica',10,'bold'))
            self.context_title.configure(text='Roof plan · '+a.kind)
            self.context_caption.configure(text=f'{a.kind} · {a.repeat_along} × {a.repeat_slope}\nDrag the handle in the roof plan or the scene')
        else:
            self.context_title.configure(text='Roof Plan')
            self.context_caption.configure(text='Select an item or add a dormer')

    def _draw_wall_context(self):
        """Show the actual assembled FRONT elevation with selectable modules.

        The context image is the same transparent FRONT raster passed from
        Facade Builder to the 3D renderer, not schematic window placeholders.
        Its hit regions follow the original per-floor module positions.
        """
        c=self.context_canvas
        bi,wall,_,_=sorted(self.selected_modules)[0]
        if not 0<=bi<len(self.blocks):return
        layout=self.layout_for_wall(wall)
        rows=layout['floors']
        counts=layout['counts']
        pw=max(160,c.winfo_width());ph=max(120,c.winfo_height())
        c.create_rectangle(0,0,pw,ph,fill='#505357',outline='')
        pair=self.wall_facades.get(wall,{})
        facade=(pair.get('front') if pair else None) or (self.facade_front if wall=='front' else None)
        # Preview the actual independently assembled wall artwork.
        has_art=facade is not None and facade.width>0 and facade.height>0
        iw=facade.width if has_art else max(1,round(self.blocks[bi].w*1.4142))
        ih=facade.height if has_art else max(1,round(self.blocks[bi].h*2))
        pad_x,pad_y=11,8
        scale=min((pw-2*pad_x)/iw,(ph-2*pad_y)/ih)
        scale=max(0.01,scale)
        draw_w=max(1,round(iw*scale));draw_h=max(1,round(ih*scale))
        ox=(pw-draw_w)/2;oy=(ph-draw_h)/2
        c.create_rectangle(ox-1,oy-1,ox+draw_w+1,oy+draw_h+1,
                           fill='#b9b0a5' if not has_art else '#55585b',
                           outline='#87929c',width=1)
        if has_art:
            # Resize only for the preview; never modify the facade master.
            preview=facade.convert('RGBA').resize((draw_w,draw_h),Image.Resampling.NEAREST)
            self._wall_context_photo=ImageTk.PhotoImage(preview,master=c)
            c.create_image(round(ox),round(oy),image=self._wall_context_photo,
                           anchor='nw')
        else:
            self._wall_context_photo=None
            c.create_text(pw/2,ph/2,fill='#404850',
                          text='No facade assigned',font=('Helvetica',10))
        heights=layout.get('band_heights')
        if not heights or len(heights)<rows:
            heights=[ih/rows]*rows
        total_h=sum(heights[:rows]) or 1
        # The assembled raster stores floors top-down; the editor indexes
        # floors bottom-up, so walk upward from the image's bottom edge.
        consumed=0.0
        front_spans=layout.get('front_spans')
        band_widths=layout.get('band_widths')
        for floor in range(rows):
            height=heights[floor]
            y0=oy+(ih-consumed-height)*draw_h/ih
            y1=oy+(ih-consumed)*draw_h/ih
            consumed+=height
            count=counts[min(floor,len(counts)-1)]
            for col in range(count):
                if has_art and front_spans and floor<len(front_spans) and col<len(front_spans[floor]):
                    x_left,x_right=front_spans[floor][col]
                    band_w=band_widths[floor] if band_widths and floor<len(band_widths) else iw
                    x_left+=(iw-band_w)/2
                    x_right+=(iw-band_w)/2
                    t0,t1=x_left/iw,x_right/iw
                else:
                    spans=layout.get('spans')
                    if spans and floor<len(spans) and col<len(spans[floor]):
                        t0,t1=spans[floor][col]
                    else:t0,t1=col/count,(col+1)/count
                x0=ox+t0*draw_w;x1=ox+t1*draw_w
                key=(bi,wall,floor,col)
                active=key in self.selected_modules
                if active:
                    c.create_rectangle(x0,y0,x1,y1,fill='#509bc4',stipple='gray50',
                                       outline='#b6e8ff',width=2)
                else:
                    c.create_rectangle(x0,y0,x1,y1,fill='',outline='#9cb0bf',
                                       dash=(2,3),width=1)
                self._wall_preview_regions.append(((x0,y0,x1,y1),key))
        name={'front':'Front','back':'Back','left':'Left','right':'Right'}.get(wall,wall)
        self.context_title.configure(text=f'{name} wall · body {bi+1}')
        self.context_caption.configure(text=f'Selected: {len(self.selected_modules)}')

    def _wall_context_press(self,event):
        hits=[key for (x0,y0,x1,y1),key in self._wall_preview_regions
              if x0<=event.x<=x1 and y0<=event.y<=y1]
        if not hits:return
        key=hits[-1]
        if event.state & 0x0001:
            if key in self.selected_modules:self.selected_modules.remove(key)
            else:self.selected_modules.add(key)
        else:
            self.selected_modules={key}
        self.schedule()
        self.update_context_preview()

    def plan_press(self,event):
        if self.module_select_mode.get() and self.selected_modules:
            return self._wall_context_press(event)
        self._plan_drag=False
        if not self._plan_transform or not self.roof_accessories:return
        ox,oy,sc,parent=self._plan_transform
        choices=[]
        for i,a in enumerate(self.roof_accessories):
            if a.parent==parent:
                pt=self._roof_plan_point(a)
                if pt:
                    x=ox+(pt[0]-self.blocks[parent].x)*sc
                    y=oy+(pt[1]-self.blocks[parent].y)*sc
                    choices.append(((x-event.x)**2+(y-event.y)**2,i))
        if choices and min(choices)[0]<900:
            self.accessory_active=min(choices)[1]
            self.refresh_accessory_list()
            self._plan_drag=True

    def plan_motion(self,event):
        if self.module_select_mode.get() and self.selected_modules:return
        if not self._plan_drag or not self._plan_transform:return
        ox,oy,sc,parent=self._plan_transform
        b=self.blocks[parent];a=self.roof_accessories[self.accessory_active]
        x=b.x+(event.x-ox)/sc;y=b.y+(event.y-oy)/sc
        along=(x-b.x)/b.w if b.axis=='X' else (y-b.y)/b.d
        half=(y-b.y)/b.d if b.axis=='X' else (x-b.x)/b.w
        a.side=1 if half>=.5 else 0
        a.slope=max(0,min(100,round(abs(half-.5)*200)))
        a.along=max(0,min(100,round(along*100)))
        self.load_accessory();self.schedule();self.update_context_preview()

    def scene_press(self,event):
        # Button tags handle icon clicks separately; don't move the scene.
        mode=self.tool_mode.get()
        self._drag_accessory=None
        if self.tool_mode.get()=='zoom':
            self.change_zoom(-.16 if event.state&0x0001 else .16,(event.x,event.y))
            return 'break'
        if self.tool_mode.get()=='pan':
            self.pan_start(event)
            return 'break'
        if self.module_select_mode.get():
            return self.select_module_at(event)
        if self._pivot_screen and self.roof_accessories:
            px,py=self._pivot_screen
            if abs(event.x-px)<25 and abs(event.y-py)<25:
                self._drag_accessory=(event.x,event.y,self.roof_accessories[self.accessory_active].along,
                                      self.roof_accessories[self.accessory_active].slope)
                return
        self.pan_start(event)

    def scene_motion(self,event):
        if self.tool_mode.get()=='zoom':return
        if self.tool_mode.get()=='pan':
            self.pan_motion(event)
            return
        if self.module_select_mode.get():return
        if not self._drag_accessory:
            self.pan_motion(event);return
        if not self._drag_accessory or not self.roof_accessories:return
        sx,sy,initial_along,initial_slope=self._drag_accessory
        a=self.roof_accessories[self.accessory_active]
        if not 0<=a.parent<len(self.blocks):return
        b=self.blocks[a.parent]
        dx=(event.x-sx)/max(1,self._render_zoom);dy=(event.y-sy)/max(1,self._render_zoom)
        # Undo screen isometric projection after camera rotation.  Z stays
        # approximately fixed during a short drag; the roof is re-evaluated
        # by the renderer on every update.
        rx=(dx+2*dy)/2;ry=(2*dy-dx)/2
        theta=math.radians(self.angle)
        wx=rx*math.cos(theta)+ry*math.sin(theta)
        wy=-rx*math.sin(theta)+ry*math.cos(theta)
        delta_long=wx if b.axis=='X' else wy
        delta_cross=wy if b.axis=='X' else wx
        a.along=max(0,min(100,round(initial_along+delta_long/max(1,b.w if b.axis=='X' else b.d)*100)))
        sign=1 if a.side else -1
        a.slope=max(0,min(100,round(initial_slope+sign*delta_cross/max(1,(b.d if b.axis=='X' else b.w)/2)*100)))
        self.load_accessory();self.schedule();self.update_context_preview()

    def scene_release(self,event):
        self._drag_accessory=None

    def roof_hex(self):
        return "#%02x%02x%02x" % self.roof_color

    def pick_roof_palette(self):
        path=ROOF_PALETTE_PATH
        if not path.is_file():
            selected=filedialog.askopenfilename(title='Roof palette',filetypes=[('Images',"*.png *.jpg *.jpeg")])
            if not selected:return
            path=Path(selected)
        try:
            picture=Image.open(path).convert("RGB")
        except Exception as exc:
            messagebox.showerror('Roof Palette',str(exc));return
        popup=tk.Toplevel(self.root);popup.title('Choose roof colour')
        popup.transient(self.root)
        maxw,maxh=760,490
        factor=min(1.0,maxw/picture.width,maxh/picture.height)
        shown=picture.resize((max(1,round(picture.width*factor)),max(1,round(picture.height*factor))),Image.Resampling.BILINEAR)
        photo=ImageTk.PhotoImage(shown)
        canvas=tk.Canvas(popup,width=shown.width,height=shown.height,highlightthickness=0)
        canvas.pack(padx=10,pady=10)
        canvas.image=photo
        canvas.create_image(0,0,image=photo,anchor="nw")
        ttk.Label(popup,text='Choose a shade. Colour applies to all roof slopes.').pack(pady=(0,10))
        def choose(event):
            x=min(picture.width-1,max(0,int(event.x/factor)))
            y=min(picture.height-1,max(0,int(event.y/factor)))
            self.roof_color=picture.getpixel((x,y))
            self.roof_swatch.configure(bg=self.roof_hex())
            popup.destroy();self.schedule()
        canvas.bind("<Button-1>",choose)

    def roof_render_options(self):
        try:
            return dict(roof_color=self.roof_color,roof_lines=bool(self.roof_lines.get()),
                        roof_spacing=max(2,int(self.roof_spacing.get())),
                        roof_opacity=max(0,min(85,int(self.roof_opacity.get()))),
                        roof_softness=max(0.05,float(self.roof_softness.get())))
        except (ValueError,tk.TclError):
            return dict(roof_color=self.roof_color,roof_lines=bool(self.roof_lines.get()))

    def refresh_list(self):
        self.listbox.delete(0,"end")
        for i,b in enumerate(self.blocks):
            self.listbox.insert("end",f"{i+1}. {b.name}  ({b.axis})")
        if self.blocks:
            self.active=max(0,min(self.active,len(self.blocks)-1))
            self.listbox.selection_set(self.active)
            self.listbox.activate(self.active)
            self.load_fields()
        self._sync_tray_listbox()
        self._update_bottom_status()

    def load_fields(self):
        if not self.blocks:return
        self.updating=True
        b=self.blocks[self.active]
        for key,var in self.vars.items():var.set(getattr(b,key))
        self.axis.set(b.axis)
        self.roof_type.set(b.roof_type)
        self.thickness_enabled.set(b.thickness_enabled)
        self.extended_gable.set(b.extended_gable)
        self.updating=False

    def choose(self,event=None):
        selected=self.listbox.curselection()
        if selected:
            self.active=selected[0]
            self.load_fields()
            self._update_bottom_status()

    def changed(self,event=None):
        if self.updating or not self.blocks:return
        b=self.blocks[self.active]
        try:
            values={key:var.get() for key,var in self.vars.items()}
        except (ValueError,tk.TclError):
            return
        oldx,oldy=b.x,b.y
        for key,value in values.items():
            setattr(b,key,max(12,value) if key in ("w","d") else max(1,value) if key in ("h","rise") else value)
        b.axis=self.axis.get()
        b.roof_type=self.roof_type.get()
        b.thickness_enabled=self.thickness_enabled.get()
        b.extended_gable=self.extended_gable.get()
        b.overhang=min(8,max(0,b.overhang))
        b.thickness=min(2,max(0,b.thickness))
        b.eave_drop=min(3,max(0,b.eave_drop))
        max_ridge=b.w if b.axis=="X" else b.d
        b.ridge=min(max(0,b.ridge),max_ridge)
        if self.snap.get() and (oldx!=b.x or oldy!=b.y):
            self.apply_snap(b,2)
        self._update_bottom_status()
        self.schedule()

    def apply_snap(self,b,tolerance=6):
        others=[o for o in self.blocks if o is not b]
        if not others:return
        for coord,size in (("x","w"),("y","d")):
            current=getattr(b,coord)
            length=getattr(b,size)
            possibilities=[]
            for o in others:
                ostart=getattr(o,coord);oend=ostart+getattr(o,size)
                for target in (ostart,oend,ostart-length,oend-length):
                    possibilities.append((abs(target-current),target))
            if possibilities:
                dist,target=min(possibilities)
                if dist<=tolerance:setattr(b,coord,int(target))
        self.load_fields()

    def snap_to_neighbor(self):
        """Join roof footprints with an intentional overlap, not edge contact.

        Merely touching walls does not create a valley between roof solids.
        The button creates an overlap while preserving the other coordinate.
        """
        if len(self.blocks)<2:return
        b=self.blocks[self.active]
        others=[o for o in self.blocks if o is not b]
        def overlap(a0,a1,b0,b1):
            return min(a1,b1)-max(a0,b0)
        if any(overlap(b.x,b.x+b.w,o.x,o.x+o.w)>0 and
               overlap(b.y,b.y+b.d,o.y,o.y+o.d)>0 for o in others):
            self.schedule()
            return
        choices=[]
        for o in others:
            for coord,size,other_coord,other_size in (("x","w","y","d"),("y","d","x","w")):
                # A joint is useful only if the footprints overlap on the
                # perpendicular axis, or can be centered on that axis.
                current=getattr(b,coord)
                length=getattr(b,size)
                left=getattr(o,coord)
                right=left+getattr(o,size)
                inset=max(2,min(length,getattr(o,size))//3)
                for target in (left-length+inset,right-inset):
                    choices.append((abs(current-target),coord,target,o,other_coord,other_size))
        if choices:
            _,coord,target,o,other_coord,other_size=min(choices,key=lambda t:t[0])
            setattr(b,coord,int(target))
            perpendicular_start=getattr(b,other_coord)
            perpendicular_end=perpendicular_start+getattr(b,other_size)
            neighbor_start=getattr(o,other_coord)
            neighbor_end=neighbor_start+getattr(o,other_size)
            if overlap(perpendicular_start,perpendicular_end,neighbor_start,neighbor_end)<=0:
                setattr(b,other_coord,int(neighbor_start+(getattr(o,other_size)-getattr(b,other_size))/2))
            self.load_fields()
            self.schedule()

    def add(self):
        n=len(self.blocks)
        self.blocks.append(Block(name=f"Body {n+1}",x=8+n*4,y=8+n*4,
                                 w=28,d=20,h=36,rise=10,axis="Y",
                                 roof_type='Hip',ridge=12))
        self.active=n
        self.refresh_list()
        self._sync_tray_listbox()
        self._update_bottom_status()
        self.schedule()

    def duplicate(self):
        if not self.blocks:return
        original=asdict(self.blocks[self.active])
        original["name"]=original["name"]+' copy'
        original["x"]+=8;original["y"]+=8
        self.blocks.append(Block(**original))
        self.active=len(self.blocks)-1
        self.refresh_list();self._sync_tray_listbox()
        self._update_bottom_status()
        self.schedule()

    def delete(self):
        if len(self.blocks)<=1:
            messagebox.showinfo('Bodies','At least one body must remain.')
            return
        removed=self.active
        self.blocks.pop(self.active)
        self.roof_accessories=[a for a in self.roof_accessories if a.parent!=removed]
        for a in self.roof_accessories:
            if a.parent>removed:a.parent-=1
        self.refresh_accessory_list()
        self.active=max(0,self.active-1)
        self.refresh_list();self._sync_tray_listbox()
        self._update_bottom_status()
        self.schedule()

    def preset(self,shape):
        main=Block('Main body',0,0,48,24,36,12,"X",
                   'Hip',ridge=24,overhang=1,thickness=1)
        if shape=="I":
            self.blocks=[main]
        elif shape=="L":
            side=Block('Side wing',0,12,24,44,36,12,"Y",
                       'Hip',ridge=20,overhang=1,thickness=1)
            self.blocks=[main,side]
        elif shape=="T":
            side=Block('Cross wing',14,12,20,44,36,12,"Y",
                       'Hip',ridge=20,overhang=1,thickness=1)
            self.blocks=[main,side]
        else:
            side=Block('Cross wing',14,-10,20,44,36,12,"Y",
                       'Hip',ridge=20,overhang=1,thickness=1)
            self.blocks=[main,side]
        self.roof_accessories=[]
        self.refresh_accessory_list()
        self.active=len(self.blocks)-1
        self.refresh_list();self.schedule()

    def add_accessory(self,kind):
        if not self.blocks:return
        self.roof_accessories.append(RoofAccessory(kind=kind,parent=self.active,
                              width=8 if kind=='Dormer' else 5,
                              depth=20 if kind=='Dormer' else 5,
                              height=6 if kind=='Dormer' else 15,
                              roof_rise=2 if kind=='Dormer' else 4,
                              slope=90 if kind=='Dormer' else 60,
                              gap_along=16 if kind=='Dormer' else 2,
                              repeat_along=1))
        self.accessory_active=len(self.roof_accessories)-1
        self.refresh_accessory_list()
        self.update_context_preview()
        self.schedule()

    def refresh_accessory_list(self):
        if not hasattr(self,"accessory_list"):return
        self.accessory_list.delete(0,"end")
        for a in self.roof_accessories:
            self.accessory_list.insert("end",f"{a.kind} · body {a.parent+1}")
        if self.roof_accessories:
            self.accessory_active=min(self.accessory_active,len(self.roof_accessories)-1)
            self.accessory_list.selection_set(self.accessory_active)
            self.load_accessory()

    def select_accessory(self,event=None):
        selected=self.accessory_list.curselection()
        if selected:
            self.accessory_active=selected[0]
            self.load_accessory()
            self.update_context_preview()

    def load_accessory(self):
        if not self.roof_accessories:return
        a=self.roof_accessories[self.accessory_active]
        self.accessory_updating=True
        for k,v in self.accessory_vars.items():v.set(getattr(a,k)+1 if k=="parent" else getattr(a,k))
        self.accessory_side.set('Right / far' if a.side else 'Left / near')
        self.accessory_window_variant.set(getattr(a,'window_variant',1))
        self.accessory_updating=False
        self.update_context_preview()

    def change_accessory(self,event=None):
        if getattr(self,"accessory_updating",False) or not self.roof_accessories:return
        a=self.roof_accessories[self.accessory_active]
        try:values={k:v.get() for k,v in self.accessory_vars.items()}
        except (ValueError,tk.TclError):return
        for k,v in values.items():
            if k=="parent":a.parent=max(0,min(len(self.blocks)-1,v-1))
            elif k in ("along","slope"):setattr(a,k,max(0,min(100,v)))
            elif k.startswith("gap_"):setattr(a,k,max(0,v))
            else:setattr(a,k,max(1,v))
        a.side=1 if self.accessory_side.get()=='Right / far' else 0
        try:a.window_variant=max(1,min(2,int(self.accessory_window_variant.get())))
        except (ValueError,tk.TclError):pass
        self.update_context_preview()
        self.schedule()

    def duplicate_accessory(self):
        if not self.roof_accessories:return
        source=self.roof_accessories[self.accessory_active]
        copy=RoofAccessory(**asdict(source))
        copy.along=min(100,copy.along+15)
        self.roof_accessories.append(copy)
        self.accessory_active=len(self.roof_accessories)-1
        self.refresh_accessory_list();self.update_context_preview();self.schedule()

    def delete_accessory(self):
        if not self.roof_accessories:return
        self.roof_accessories.pop(self.accessory_active)
        self.accessory_active=max(0,self.accessory_active-1)
        self.refresh_accessory_list();self.update_context_preview();self.schedule()

    def rotate(self,delta):
        # Rotate the entire scene, never mutate any Block coordinates.
        self.angle=(self.angle+delta)%360
        self.angle_label.configure(text=f"{self.angle}°")
        if hasattr(self,"bridge_angle_slider"):
            self.bridge_angle_slider.set(((self.angle//15+12)%24)-12)
            self.bridge_angle_label.configure(text=f"{self.angle}°")
        if hasattr(self,'angle_slider'):self.angle_slider.set(((self.angle//15+12)%24)-12)
        if callable(getattr(self,"rotation_callback",None)):self.rotation_callback()
        self.schedule()

    def reset_rotation(self):
        self.angle=0
        self.angle_label.configure(text="0°")
        if hasattr(self,"bridge_angle_slider"):
            self.bridge_angle_slider.set(((self.angle//15+12)%24)-12)
            self.bridge_angle_label.configure(text=f"{self.angle}°")
        if hasattr(self,'angle_slider'):self.angle_slider.set(0)
        if callable(getattr(self,"rotation_callback",None)):self.rotation_callback()
        self.schedule()

    def schedule(self):
        """Debounce a scene change, with only one pending draw."""
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
        self.after_id=self.root.after(20,self.refresh)

    def schedule_camera(self):
        """Coalesce rapid camera events without endlessly postponing the draw."""
        if self.after_id is not None:
            return
        elapsed=time.perf_counter()-self._camera_last_frame
        delay=max(1,int(max(0.0,self._camera_frame_interval-elapsed)*1000))
        self.after_id=self.root.after(delay,self._camera_refresh)

    def _camera_refresh(self):
        self.after_id=None
        self.refresh()

    def _move_cached_frame(self):
        """Immediately shift the displayed bitmap while a full recomposition
        catches up. This keeps dragging responsive even on macOS Tk.
        """
        render_id=getattr(self,'_canvas_render_id',None)
        origin=getattr(self,'_display_preview_pan',None)
        if render_id is None or origin is None or not self.canvas.type(render_id):
            return
        dx=round(self.preview_pan[0]-origin[0])
        dy=round(self.preview_pan[1]-origin[1])
        self.canvas.coords(render_id,dx,dy)

    def change_zoom(self,step,pointer=None):
        current=float(self.preview_zoom.get())
        new=1.0 if step==0 else max(0.35,min(15.0,current*math.exp(step)))
        if abs(new-current)<1e-5:return
        if pointer:
            cx=self.canvas.winfo_width()/2;cy=self.canvas.winfo_height()/2
            self.preview_pan=[(self.preview_pan[0]+cx-pointer[0])*new/current+pointer[0]-cx,
                              (self.preview_pan[1]+cy-pointer[1])*new/current+pointer[1]-cy]
        self.preview_zoom.set(new)
        self.schedule_camera()

    def preview_wheel(self,event):
        # On macOS the trackpad two-finger gesture arrives through MouseWheel
        # (normally many small deltas). Shift+scroll pans horizontally.
        d=event.delta/120 if abs(event.delta)>=120 else event.delta
        # Many macOS trackpads emit fractional-ish fine scroll deltas;
        # allow continuous small zoom steps around the pointer.
        step=math.copysign(min(.14,abs(d)*.025),d) if d else 0
        if step:self.change_zoom(step,(event.x,event.y))
        return 'break'

    def trackpad_zoom(self,event):
        return self.preview_wheel(event)

    def trackpad_pan(self,event):
        self.preview_pan[0]+=event.delta/4
        self._move_cached_frame()
        self.schedule_camera()
        return 'break'

    def pan_start(self,event):
        self.pan_pointer=(event.x,event.y,self.preview_pan[0],self.preview_pan[1])

    def pan_motion(self,event):
        if not hasattr(self,'pan_pointer'):return
        x,y,ox,oy=self.pan_pointer
        self.preview_pan=[ox+event.x-x,oy+event.y-y]
        self._move_cached_frame()
        self.schedule_camera()

    def edit_dormer_window(self):
        if not self.roof_accessories:return
        obj=self.roof_accessories[self.accessory_active]
        if obj.kind!='Dormer':
            messagebox.showinfo('Dormer Windows','Select a dormer, not a chimney.')
            return
        win=tk.Toplevel(self.root);win.title('Dormer Window Editor');win.resizable(False,False)
        ttk.Label(win,text='Variants 1 and 2 are independent sets of glazing, frames and casings.').pack(padx=12,pady=(12,5))
        bar=ttk.Frame(win);bar.pack(fill='x',padx=12,pady=5)
        persp=tk.StringVar(value='iso')
        variant=tk.IntVar(value=obj.window_variant)
        layer=tk.StringVar(value='glass')
        ttk.Label(bar,text='View:').pack(side='left')
        perspective=ttk.Combobox(bar,textvariable=persp,values=('iso','front'),state='readonly',width=7)
        perspective.pack(side='left',padx=5)
        ttk.Label(bar,text='Set:').pack(side='left')
        choices=ttk.Combobox(bar,textvariable=variant,values=(1,2),state='readonly',width=4)
        choices.pack(side='left',padx=5)
        ttk.Label(bar,text='Detail:').pack(side='left')
        parts=ttk.Combobox(bar,textvariable=layer,values=('glass','frame','casing'),state='readonly',width=9)
        parts.pack(side='left',padx=5)
        preview=tk.Canvas(win,width=288,height=276,bg='#777a7d',highlightthickness=0)
        preview.pack(padx=12,pady=6)
        offsets_text=tk.StringVar()
        ttk.Label(win,textvariable=offsets_text).pack(pady=3)
        scale=12
        def current_shift():
            return obj.window_offsets.get(persp.get(),{}).get(layer.get(),[0,0])
        def draw(*unused):
            obj.window_variant=variant.get()
            composed=dormer_window_sprite(variant.get(),persp.get()=='front',obj.window_offsets)
            composed=composed.resize((composed.width*scale,composed.height*scale),Image.Resampling.NEAREST)
            background=Image.new('RGBA',composed.size,(210,203,191,255))
            background.alpha_composite(composed)
            preview.photo=ImageTk.PhotoImage(background.convert('RGB'))
            preview.delete('all')
            preview.create_image(144,138,image=preview.photo,anchor='center')
            dx,dy=current_shift()
            offsets_text.set(f'{layer.get()}  ·  X {dx:+d}   Y {dy:+d}   |   drag to move')
            self.accessory_window_variant.set(variant.get())
            self.schedule()
        def shift(dx,dy):
            p=obj.window_offsets.setdefault(persp.get(),{})
            x,y=current_shift()
            p[layer.get()]=[max(-6,min(6,x+dx)),max(-6,min(6,y+dy))]
            draw()
        buttons=ttk.Frame(win);buttons.pack(pady=5)
        for name,dx,dy in (('←',-1,0),('→',1,0),('↑',0,-1),('↓',0,1)):
            ttk.Button(buttons,text=name,width=4,command=lambda dx=dx,dy=dy:shift(dx,dy)).pack(side='left',padx=2)
        ttk.Button(buttons,text='Reset offset',command=lambda:reset()).pack(side='left',padx=5)
        def reset():
            obj.window_offsets.setdefault(persp.get(),{})[layer.get()]=[0,0]
            draw()
        preview.bind('<ButtonPress-1>',lambda e:setattr(win,'_drag',(e.x,e.y)))
        def drag(event):
            xy=getattr(win,'_drag',(event.x,event.y))
            dx=round((event.x-xy[0])/scale);dy=round((event.y-xy[1])/scale)
            if dx or dy:
                shift(dx,dy);win._drag=(xy[0]+dx*scale,xy[1]+dy*scale)
        preview.bind('<B1-Motion>',drag)
        for combo in (perspective,choices,parts):combo.bind('<<ComboboxSelected>>',draw)
        ttk.Button(win,text='Done',command=win.destroy).pack(pady=(5,12))
        draw()

    def _cached_angle_frame(self,signature):
        frame=self._angle_frames.get(signature)
        if frame is not None:
            self._angle_frames.move_to_end(signature)
        return frame

    def _remember_angle_frame(self,signature,frame):
        self._angle_frames[signature]=frame
        self._angle_frames.move_to_end(signature)
        while len(self._angle_frames)>self._angle_frames_limit:
            self._angle_frames.popitem(last=False)

    def _schedule_neighbour_prefetch(self):
        """Idle-time warmup: compute likely next 15-degree views in advance.

        This does not accelerate a cold angle. It removes the delay when a
        neighbour is already in the bounded frame cache. Keep the work idle-
        priority, and let foreground requests replace waiting prefetch jobs.
        """
        if self._prefetch_timer is not None:
            self.root.after_cancel(self._prefetch_timer)
        self._prefetch_timer=self.root.after(650,self._prefetch_neighbours)

    def _prefetch_neighbours(self):
        self._prefetch_timer=None
        signature=getattr(self,'_cache_key',None)
        if not signature or self._rotation_waiting or self._rotation_target is not None:
            return
        if signature[0]!=self.angle:
            return
        with self._rotation_lock:
            if self._rotation_pending is not None or self._rotation_prefetch:
                return
        opts=self.roof_render_options()
        kwargs=dict(blocks=[Block(**asdict(b)) for b in self.blocks],
                    angle=self.angle,cast_shadow=bool(self.cast_shadow.get()),
                    facade_texture=self.facade_texture,facade_source=self.facade_source,
                    facade_filter=self.facade_filter,facade_front=self.facade_front,
                    roof_accessories=[RoofAccessory(**asdict(a)) for a in self.roof_accessories],
                    accessory_wall_color=self.accessory_wall_color,
                    wall_edits=copy.deepcopy(self.wall_edits),
                    wall_facades={w:dict(pair) for w,pair in self.wall_facades.items()},
                    **opts)
        requested=[]
        for delta in (15,-15):
            angle=(self.angle+delta)%360
            candidate=(angle,)+signature[1:]
            if candidate not in self._angle_frames:
                options=dict(kwargs,angle=angle)
                requested.append((candidate,options))
        if not requested:
            return
        with self._rotation_lock:
            if self._rotation_pending is not None:
                return
            self._rotation_prefetch.extend(requested)
            if self._rotation_thread is None or not self._rotation_thread.is_alive():
                self._rotation_thread=threading.Thread(target=self._rotation_worker_loop,
                                                       daemon=True,name='SC3K-angle-render')
                self._rotation_thread.start()
        if self._rotation_poll_id is None:
            self._rotation_poll_id=self.root.after(25,self._poll_angle_render)

    def _queue_angle_render(self,signature,opts):
        """Snapshot render data on Tk's thread, never call Tk in worker.

        There is only one worker and one pending request: multiple 15-degree
        clicks replace obsolete pending work instead of forming a long queue.
        """
        if self._rotation_target==signature:
            return
        self._rotation_target=signature
        kwargs=dict(blocks=[Block(**asdict(b)) for b in self.blocks],
                    angle=self.angle,cast_shadow=bool(self.cast_shadow.get()),
                    facade_texture=self.facade_texture,facade_source=self.facade_source,
                    facade_filter=self.facade_filter,facade_front=self.facade_front,
                    roof_accessories=[RoofAccessory(**asdict(a)) for a in self.roof_accessories],
                    accessory_wall_color=self.accessory_wall_color,
                    wall_edits=copy.deepcopy(self.wall_edits),
                    wall_facades={w:dict(pair) for w,pair in self.wall_facades.items()},
                    **opts)
        with self._rotation_lock:
            self._rotation_prefetch.clear()
            self._rotation_pending=(signature,kwargs)
            if self._rotation_thread is None or not self._rotation_thread.is_alive():
                self._rotation_thread=threading.Thread(target=self._rotation_worker_loop,
                                                       daemon=True,name='SC3K-angle-render')
                self._rotation_thread.start()
        if self._rotation_poll_id is None:
            self._rotation_poll_id=self.root.after(25,self._poll_angle_render)

    def _rotation_worker_loop(self):
        while True:
            with self._rotation_lock:
                task=self._rotation_pending
                self._rotation_pending=None
                if task is None and self._rotation_prefetch:
                    task=self._rotation_prefetch.popleft()
            if task is None:
                return
            signature,kwargs=task
            try:
                frame=render_scene(**kwargs)
                error=None
            except Exception as exc:
                frame=None
                error=str(exc)
            with self._rotation_lock:
                self._rotation_finished.append((signature,frame,error))

    def _poll_angle_render(self):
        self._rotation_poll_id=None
        with self._rotation_lock:
            completed=list(self._rotation_finished)
            self._rotation_finished.clear()
            still_running=(self._rotation_thread is not None and
                           self._rotation_thread.is_alive())
            has_pending=self._rotation_pending is not None or bool(self._rotation_prefetch)
            # A worker may finish just as the next click queues a new angle.
            # Never leave a pending frame stranded after its worker exits.
            if has_pending and not still_running:
                self._rotation_thread=threading.Thread(target=self._rotation_worker_loop,
                                                       daemon=True,name='SC3K-angle-render')
                self._rotation_thread.start()
                still_running=True
        for signature,frame,error in completed:
            if frame is not None:
                self._remember_angle_frame(signature,frame)
            elif signature==self._rotation_target:
                self.status.configure(text=f'Angle render error: {error}')
                self._rotation_target=None
        if self._rotation_target in self._angle_frames:
            self._rotation_waiting=False
            self._rotation_target=None
            self.schedule_camera()
        elif still_running or has_pending:
            self._rotation_poll_id=self.root.after(25,self._poll_angle_render)

    def refresh(self):
        self.after_id=None
        # Camera-only input must never trigger an expensive 3D raster pass.
        # Cache the native-resolution render; zoom/pan only recompose it.
        opts=self.roof_render_options()
        signature=(self.angle,self.cast_shadow.get(),self.facade_filter,
                   id(self.facade_source),id(self.facade_front),id(self.facade_texture),
                   tuple((wall,id(pair.get("iso")),id(pair.get("front"))) for wall,pair in sorted(self.wall_facades.items())),
                   tuple(sorted((k,str(v)) for k,v in opts.items())),
                   str(self.accessory_wall_color),
                   tuple(repr(asdict(b)) for b in self.blocks),
                   tuple(repr(asdict(a)) for a in self.roof_accessories),
                   tuple(repr(edit) for edit in self.wall_edits))
        try:
            if signature!=getattr(self,'_cache_key',None):
                cached=self._cached_angle_frame(signature)
                if cached is not None:
                    self._native_scene=cached
                    self._cache_key=signature
                    self._rotation_target=None
                    self._rotation_waiting=False
                elif (hasattr(self,'_native_scene') and
                      getattr(self,'_cache_key',None) is not None and
                      signature[0]!=self._cache_key[0]):
                    # A changed angle is expensive; leave the already drawn
                    # frame in place until the worker produces the exact view.
                    self._queue_angle_render(signature,opts)
                    self._rotation_waiting=True
                else:
                    # First launch and non-camera model edits retain the
                    # established synchronous, fully deterministic path.
                    self._native_scene=render_scene(self.blocks,self.angle,cast_shadow=self.cast_shadow.get(),facade_texture=self.facade_texture,facade_source=self.facade_source,facade_filter=self.facade_filter,facade_front=self.facade_front,**opts,roof_accessories=self.roof_accessories,accessory_wall_color=self.accessory_wall_color,wall_edits=self.wall_edits,wall_facades=self.wall_facades)
                    self._cache_key=signature
                    self._rotation_waiting=False
                    self._remember_angle_frame(signature,self._native_scene)
            image=self._native_scene
        except (ValueError,tk.TclError) as exc:
            self.status.configure(text=f"Error: {exc}")
            return
        cw=max(100,self.canvas.winfo_width());ch=max(100,self.canvas.winfo_height())
        factor=min((cw-24)/image.width,(ch-24)/image.height)
        zoom=max(.35,float(self.preview_zoom.get())*max(1.0,factor))
        scaled=(max(1,round(image.width*zoom)),max(1,round(image.height*zoom)))
        # Virtual image dimensions are used for all pointer/cell coordinates.
        # The expensive full-size resize is only a fallback when NumPy is absent
        # or the image is small enough that the legacy path is more efficient.
        from grid_lattice import paint_scene_grid
        from preview_masks import native_masks, scaled_masks
        from viewport_sampler import np as viewport_numpy, visible_box, sample
        scaled_key=(id(image),scaled)
        self._preview_scaled_key=scaled_key
        self._render_zoom=zoom
        self._render_image_size=scaled
        left=round((cw-scaled[0])/2+self.preview_pan[0])
        top=round((ch-scaled[1])/2+self.preview_pan[1])
        shadows=bool(self.cast_shadow.get())
        base_key=(scaled_key,cw,ch,left,top,shadows,bool(self.show_iso_grid.get()))
        if self._preview_image_cache_key==base_key:
            outer=self._preview_image_cache
        else:
            board=Image.new('RGB',(cw,ch),'#505357')
            if self.show_iso_grid.get():
                paint_scene_grid(board,left,top,zoom)
            native_key=(id(self._native_scene),shadows)
            if self._native_mask_cache_key!=native_key:
                self._native_masks=native_masks(self._native_scene,PREVIEW,CAST_SHADOW,shadows)
                self._native_mask_cache_key=native_key
            # Only create a viewport-sized bitmap when the virtual enlarged
            # image is appreciably bigger than the canvas.
            clipped=visible_box(scaled,(cw,ch),left,top)
            fast=(viewport_numpy is not None and clipped is not None
                  and scaled[0]*scaled[1]>cw*ch*1.5)
            if fast:
                sx0,sy0,sx1,sy1=clipped
                source,nonbg,shadow_mask=sample(self._native_scene,self._native_masks,scaled,clipped)
                dx=max(0,left);dy=max(0,top)
            else:
                if scaled_key!=getattr(self,'_preview_scaled_data_key',None):
                    self._preview_scaled=(self._native_scene.resize(scaled,Image.Resampling.NEAREST)
                                          if scaled!=self._native_scene.size else self._native_scene)
                    self._preview_scaled_data_key=scaled_key
                source=self._preview_scaled.convert('RGB')
                mask_key=(scaled_key,shadows)
                if self._preview_mask_cache_key!=mask_key:
                    nonbg,shadow_mask=scaled_masks(self._native_masks,scaled)
                    self._preview_mask_cache=(nonbg,shadow_mask)
                    self._preview_mask_cache_key=mask_key
                else:
                    nonbg,shadow_mask=self._preview_mask_cache
                dx=left;dy=top
            board.paste(source,(dx,dy),nonbg)
            if shadow_mask is not None:
                x0=max(0,dx);y0=max(0,dy)
                x1=min(cw,dx+source.width);y1=min(ch,dy+source.height)
                if x1>x0 and y1>y0:
                    rect=(x0,y0,x1,y1)
                    mask_part=shadow_mask.crop((x0-dx,y0-dy,x1-dx,y1-dy))
                    base=board.crop(rect)
                    shaded=base.point(lambda v:round(v*.73))
                    base.paste(shaded,(0,0),mask_part)
                    board.paste(base,(x0,y0))
            outer=board
            self._preview_image_cache=outer
            self._preview_image_cache_key=base_key
        # A focus/selection/inspector change often reuses an identical preview.
        # Keep the Tk PhotoImage and the canvas bitmap item alive in that case;
        # creating a new PhotoImage copies the entire framebuffer into Tcl.
        # Only overlays are redrawn, and the image itself remains unchanged.
        if getattr(self,'_display_photo_key',None)!=base_key or self.photo is None:
            self.photo=ImageTk.PhotoImage(outer)
            self._display_photo_key=base_key
            new_photo=True
        else:
            new_photo=False
        render_id=getattr(self,'_canvas_render_id',None)
        for _id in self.canvas.find_all():
            if _id not in (self._floating_context_id,render_id):
                self.canvas.delete(_id)
        if render_id is None or not self.canvas.type(render_id):
            render_id=self.canvas.create_image(0,0,image=self.photo,anchor='nw',tags='render')
            self._canvas_render_id=render_id
        elif new_photo:
            self.canvas.itemconfigure(render_id,image=self.photo)
        # The replacement bitmap is composed at the latest camera position;
        # undo the temporary dragging offset on the old bitmap.
        self.canvas.coords(render_id,0,0)
        self._display_preview_pan=tuple(self.preview_pan)
        self._camera_last_frame=time.perf_counter()
        self.canvas.tag_lower(render_id)
        self.canvas.tag_raise(self._floating_context_id)
        if self.module_select_mode.get():
            self._draw_module_overlay(left,top,zoom)
        else:
            self._module_hit_regions=[]
            self._draw_scene_pivot(cw,ch,zoom)
        # Navigation uses the trackpad/mouse; no obstructive scene buttons.
        self.update_context_preview()
        self._update_bottom_status()
        if self._rotation_waiting:
            self.status.configure(text=f'View {self.angle}° — rendering…')
        elif self._cache_key==signature:
            self._schedule_neighbour_prefetch()




    def _draw_scene_pivot(self,cw,ch,zoom):
        self._pivot_screen=None
        if not self.roof_accessories or not self.blocks:return
        obj=self.roof_accessories[self.accessory_active]
        if not 0<=obj.parent<len(self.blocks):return
        b=self.blocks[obj.parent];pt=self._roof_plan_point(obj)
        if pt is None:return
        wx,wy=pt
        # Pivot origin is at a corner of the selected roof accessory, rather
        # than at its centre (the familiar 3-axis editor convention).
        wz=b.h+max(3,obj.height)
        wx-=obj.width/2
        wy-=obj.depth/2
        cx=(min(q.x for q in self.blocks)+max(q.x+q.w for q in self.blocks))/2
        cy=(min(q.y for q in self.blocks)+max(q.y+q.d for q in self.blocks))/2
        mesh=scene_mesh(self.blocks,2)
        mesh.extend(accessory_mesh(self.blocks,self.roof_accessories))
        rot=[]
        for face,kind,norm in mesh:
            rot.extend(iso(rotate(p,self.angle,cx,cy)) for p in face)
        if self.cast_shadow.get():
            rot.extend((pt[0]+2*p[2],pt[1]) for face,kind,norm in mesh for p in [rotate(q,self.angle,cx,cy) for q in face] for pt in [iso((p[0],p[1],0))])
        if not rot:return
        minx=math.floor(min(p[0] for p in rot));miny=math.floor(min(p[1] for p in rot))
        px,py=iso(rotate((wx,wy,wz),self.angle,cx,cy))
        # Raster origin matches render_scene's 12-pixel margin.
        imgw,imgh=self._render_image_size
        sx=cw/2+self.preview_pan[0]+(px-minx+12)*zoom-imgw/2
        sy=ch/2+self.preview_pan[1]+(py-miny+12)*zoom-imgh/2
        self._pivot_screen=(sx,sy)
        # True 3-axis isometric gizmo: world axes rotate with the building.
        # Draw 1-pixel Manhattan steps so diagonal handles stay pixel crisp.
        origin=(wx,wy,wz)
        directions=((1,0,0,'#da5952','X'),(0,1,0,'#62b878','Y'),(0,0,1,'#568fd9','Z'))
        def pixel_line(x0,y0,x1,y1,color):
            x0,y0,x1,y1=map(round,(x0,y0,x1,y1))
            dx=abs(x1-x0);dy=abs(y1-y0)
            step_x=1 if x0<x1 else -1;step_y=1 if y0<y1 else -1
            err=dx-dy
            while True:
                self.canvas.create_rectangle(x0,y0,x0+1,y0+1,fill=color,outline=color,tags='pivot')
                if x0==x1 and y0==y1:break
                twice=2*err
                if twice>-dy:err-=dy;x0+=step_x
                if twice<dx:err+=dx;y0+=step_y
        for ux,uy,uz,color,label in directions:
            nextpt=iso(rotate((wx+ux*12,wy+uy*12,wz+uz*12),self.angle,cx,cy))
            vx=nextpt[0]-px;vy=nextpt[1]-py
            length=math.hypot(vx,vy) or 1
            ex=sx+vx/length*29;ey=sy+vy/length*29
            pixel_line(sx,sy,ex,ey,color)
            ix=round(ex);iy=round(ey)
            self.canvas.create_polygon(ix,iy-4,ix+4,iy,ix,iy+4,ix-4,iy,
                                       fill=color,outline='#202b34',width=1,tags='pivot')
            self.canvas.create_text(ix+8,iy-7,text=label,fill=color,
                                    font=('Menlo',9,'bold'),tags='pivot')
        # Small pixel cube at the origin, matching the 3D editor visual idiom.
        xx=round(sx);yy=round(sy)
        self.canvas.create_polygon(xx,yy-5,xx+5,yy-2,xx,yy+1,xx-5,yy-2,
                                   fill='#dfe9f3',outline='#273b4a',tags='pivot')
        self.canvas.create_polygon(xx-5,yy-2,xx,yy+1,xx,yy+6,xx-5,yy+3,
                                   fill='#9ab3c8',outline='#273b4a',tags='pivot')
        self.canvas.create_polygon(xx,yy+1,xx+5,yy-2,xx+5,yy+3,xx,yy+6,
                                   fill='#bfd2e1',outline='#273b4a',tags='pivot')



    def layout_for_wall(self,wall):
        return self.wall_layouts.get(wall,self.module_layout)

    def set_wall_layouts(self,layouts):
        if layouts!=self.wall_layouts:
            self.wall_layouts=layouts
            self.selected_modules.clear()
            self._cache_key=None
            self.schedule()

    def set_module_layout(self,floors,counts,spans=None,front_spans=None,
                          band_heights=None,band_widths=None):
        """Receive the exact wall modules and raster band measurements."""
        floors=max(1,min(40,int(floors)))
        row_counts=[max(1,min(40,int(v))) for v in counts[:floors]]
        row_counts.extend([row_counts[-1] if row_counts else 5]*(floors-len(row_counts)))
        layout={"floors":floors,"counts":row_counts,"spans":spans,
                "front_spans":front_spans,"band_heights":band_heights,
                "band_widths":band_widths}
        if layout!=self.module_layout:
            self.module_layout=layout
            self.selected_modules.clear()
        self.schedule()

    def _toggle_module_mode(self):
        cursor=('fleur' if self.tool_mode.get()=='pan' else
                'plus' if self.tool_mode.get()=='zoom' else
                'crosshair' if self.module_select_mode.get() else 'arrow')
        self.canvas.configure(cursor=cursor)
        self._sync_toolbar()
        self.schedule()

    def apply_selected_wall_edit(self):
        """Extrude one contiguous rectangle of selected facade modules."""
        if not self.selected_modules:
            messagebox.showinfo('Volume Editing','Select one or more facade cells.')
            return
        targets=sorted(self.selected_modules)
        bi,wall=targets[0][:2]
        if any(key[:2]!=(bi,wall) for key in targets):
            messagebox.showwarning('Volume Editing',
                                   'Select modules on one wall of the same body.')
            return
        rows=[key[2] for key in targets];cols=[key[3] for key in targets]
        lo_r,hi_r=min(rows),max(rows);lo_c,hi_c=min(cols),max(cols)
        if len(targets)!=(hi_r-lo_r+1)*(hi_c-lo_c+1) or any(
            (bi,wall,r,c) not in self.selected_modules
            for r in range(lo_r,hi_r+1) for c in range(lo_c,hi_c+1)):
            messagebox.showwarning('Volume Editing',
                                   'Select a solid rectangle of modules for one operation.')
            return
        layout=getattr(self,'wall_layouts',{}).get(wall,self.module_layout)
        counts=layout['counts']
        if any(hi_c>=counts[min(r,len(counts)-1)] for r in range(lo_r,hi_r+1)):
            messagebox.showwarning('Volume Editing','These floors have different module counts.')
            return
        spans=layout.get('spans')
        def bound(floor,col):
            if spans and floor<len(spans) and col<len(spans[floor]):
                return spans[floor][col]
            count=counts[min(floor,len(counts)-1)]
            return col/count,(col+1)/count
        # Module layouts may differ between floors: use outermost bounds.
        t0=min(bound(r,lo_c)[0] for r in range(lo_r,hi_r+1))
        t1=max(bound(r,hi_c)[1] for r in range(lo_r,hi_r+1))
        # Module groups are often centred on the wall with small margins.
        # Opt-in edge cutting makes a selection reaching the first/last
        # column flush to the REAL solid body's boundaries, not to the art.
        cut_edges=bool(self.cut_to_edges.get())
        if cut_edges:
            if lo_c==0:t0=0.0
            if all(hi_c==counts[min(r,len(counts)-1)]-1
                   for r in range(lo_r,hi_r+1)):
                t1=1.0
        floors=layout['floors'];b=self.blocks[bi]
        depth=int(self.edit_depth.get())
        if depth==0:return
        edit={'block':bi,'wall':wall,'t0':t0,'t1':t1,
              'z0':b.h*lo_r/floors,'z1':b.h*(hi_r+1)/floors,
              'depth':depth,'modules':[list(k) for k in targets],
              'open_sides':cut_edges,
              'columns':(max(1,min(12,int(self.portico_count.get())))
                         if depth<0 and self.portico_columns.get() else 0),
              'column_style':max(1,min(3,int(self.portico_style.get())))}
        self.wall_edits.append(edit)
        self._redo_wall_edits=[]
        # Remove the blue selection overlay, which otherwise hides the cut.
        self.selected_modules.clear()
        self._cache_key=None
        self.update_context_preview()
        self.schedule()

    def undo_wall_edit(self):
        if self.wall_edits:
            self._redo_wall_edits.append(self.wall_edits.pop())
            self._cache_key=None
            self.schedule()

    def redo_wall_edit(self):
        if self._redo_wall_edits:
            self.wall_edits.append(self._redo_wall_edits.pop())
            self._cache_key=None
            self.schedule()

    def clear_module_selection(self):
        self.selected_modules.clear()
        self.update_context_preview()
        self.schedule()

    @staticmethod
    def _inside_polygon(x,y,vertices):
        # Even-odd point-in-polygon, valid for any camera rotation.
        inside=False
        for j in range(len(vertices)):
            x0,y0=vertices[j];x1,y1=vertices[(j+1)%len(vertices)]
            if (y0>y)!=(y1>y) and x<(x1-x0)*(y-y0)/(y1-y0)+x0:
                inside=not inside
        return inside

    def _draw_module_overlay(self,left,top,zoom):
        self._module_hit_regions=[]
        if not self.blocks:return
        # The same world-to-screen projection and viewport offset are used
        # for scene geometry, module highlighting and mouse hit testing.
        blocks=self.blocks
        cx=(min(b.x for b in blocks)+max(b.x+b.w for b in blocks))/2
        cy=(min(b.y for b in blocks)+max(b.y+b.d for b in blocks))/2
        mesh=scene_mesh(blocks,2)
        mesh.extend(accessory_mesh(blocks,self.roof_accessories))
        pts=[iso(rotate(p,self.angle,cx,cy)) for face,_,_ in mesh for p in face]
        if self.cast_shadow.get():
            for face,_,_ in mesh:
                for p in face:
                    a,b,z=rotate(p,self.angle,cx,cy)
                    gx,gy=iso((a,b,0))
                    pts.append((gx+2*z,gy))
        if not pts:return
        minx=math.floor(min(p[0] for p in pts))
        miny=math.floor(min(p[1] for p in pts))
        for bi,block in enumerate(blocks):
            wall_specs=(("front",(0,1,0),lambda t,z:(block.x+t*block.w,block.y+block.d,z)),
                        ("back",(0,-1,0),lambda t,z:(block.x+(1-t)*block.w,block.y,z)),
                        ("right",(1,0,0),lambda t,z:(block.x+block.w,block.y+(1-t)*block.d,z)),
                        ("left",(-1,0,0),lambda t,z:(block.x,block.y+t*block.d,z)))
            theta=math.radians(self.angle)
            for wall,normal,at in wall_specs:
                layout=self.layout_for_wall(wall)
                rows=layout['floors']
                cells=layout['counts']
                nx=normal[0]*math.cos(theta)-normal[1]*math.sin(theta)
                ny=normal[0]*math.sin(theta)+normal[1]*math.cos(theta)
                if nx+ny<=0.015:continue  # backface not selectable
                for floor in range(rows):
                    count=cells[min(floor,len(cells)-1)]
                    for col in range(count):
                        spans=layout.get('spans')
                        if spans and floor<len(spans) and col<len(spans[floor]):
                            t0,t1=spans[floor][col]
                        else:
                            t0,t1=col/count,(col+1)/count
                        z0,z1=block.h*floor/rows,block.h*(floor+1)/rows
                        vertices=[]
                        rotated=[]
                        for t,z in ((t0,z0),(t1,z0),(t1,z1),(t0,z1)):
                            world=at(t,z)
                            world_rot=rotate(world,self.angle,cx,cy)
                            px,py=iso(world_rot)
                            rotated.append(world_rot)
                            vertices.append((left+(px-minx+12)*zoom,top+(py-miny+12)*zoom))
                        key=(bi,wall,floor,col)
                        active=key in self.selected_modules
                        flat=[v for pair in vertices for v in pair]
                        if active:
                            self.canvas.create_polygon(*flat,fill='#5fa9d6',stipple='gray50',
                                                       outline='#aae1ff',width=2,tags='module-overlay')
                        else:
                            self.canvas.create_polygon(*flat,fill='',outline='#b4c4ce',
                                                       width=1,dash=(2,3),tags='module-overlay')
                        depth=sum(p[0]+p[1]+p[2]*.5 for p in rotated)/4
                        self._module_hit_regions.append((depth,vertices,key))
        if self.selected_modules:
            self.canvas.create_text(18,18,anchor='nw',fill='#d7f1ff',
                                    font=('Helvetica',11,'bold'),
                                    text=f'Selected modules: {len(self.selected_modules)}',tags='module-overlay')

    def select_module_at(self,event):
        hits=[(depth,key) for depth,poly,key in self._module_hit_regions
              if self._inside_polygon(event.x,event.y,poly)]
        if not hits:
            if not (event.state & 0x0001):self.selected_modules.clear()
        else:
            key=max(hits,key=lambda item:item[0])[1]
            if event.state & 0x0001:
                if key in self.selected_modules:self.selected_modules.remove(key)
                else:self.selected_modules.add(key)
            else:
                scope=self.cell_select_scope.get()
                bi,wall,row,col=key
                if scope=='row':
                    self.selected_modules={hit_key for _,_,hit_key in self._module_hit_regions
                                           if hit_key[0]==bi and hit_key[1]==wall and hit_key[2]==row}
                elif scope=='column':
                    self.selected_modules={hit_key for _,_,hit_key in self._module_hit_regions
                                           if hit_key[0]==bi and hit_key[1]==wall and hit_key[3]==col}
                else:self.selected_modules={key}
        self.update_context_preview()
        self.schedule()
        return 'break'

    def export_png(self):
        path=filedialog.asksaveasfilename(defaultextension=".png",filetypes=[("PNG","*.png")])
        if path:
            try:render_scene(self.blocks,self.angle,cast_shadow=self.cast_shadow.get(),facade_texture=self.facade_texture,facade_source=self.facade_source,facade_filter=self.facade_filter,facade_front=self.facade_front,**self.roof_render_options(),roof_accessories=self.roof_accessories,accessory_wall_color=self.accessory_wall_color,transparent_background=True,wall_edits=self.wall_edits,wall_facades=self.wall_facades).save(path)
            except Exception as exc:messagebox.showerror('Error',str(exc))

    def export_json(self):
        path=filedialog.asksaveasfilename(defaultextension=".json",filetypes=[("JSON","*.json")])
        if path:
            with open(path,"w",encoding="utf-8") as f:
                json.dump({"format":"SC3K-volume","version":13.5,"angle":self.angle,"cast_shadow":self.cast_shadow.get(),
                           "roof_color":self.roof_hex(),"roof_lines":self.roof_lines.get(),
                           "roof_spacing":self.roof_spacing.get(),"roof_opacity":self.roof_opacity.get(),
                           "roof_softness":self.roof_softness.get(),
                           "blocks":[dict(asdict(b),roof_type={"Gable":"Двускатная","Hip":"Четырёхскатная"}.get(b.roof_type,b.roof_type)) for b in self.blocks],
                           "roof_accessories":[dict(asdict(a),kind={"Dormer":"Люкарна","Chimney":"Дымоход"}.get(a.kind,a.kind)) for a in self.roof_accessories],
                           "wall_edits":self.wall_edits},f,ensure_ascii=False,indent=2)

    def import_json(self):
        path=filedialog.askopenfilename(filetypes=[("JSON","*.json")])
        if not path:return
        try:
            with open(path,encoding="utf-8") as f:data=json.load(f)
            from facade_builder import _read_legacy_labels
            data=_read_legacy_labels(data)
            loaded=[Block(**b) for b in data["blocks"]]
            loaded_accessories=[RoofAccessory(**a) for a in data.get("roof_accessories",[])]
            if not loaded:raise ValueError('No bodies')
            self.blocks=loaded
            self.roof_accessories=[a for a in loaded_accessories if 0<=a.parent<len(loaded)]
            self.wall_edits=[e for e in data.get("wall_edits",[]) if 0<=int(e.get("block",-1))<len(loaded)]
            self.accessory_active=0
            self.refresh_accessory_list()
            self.cast_shadow.set(bool(data.get("cast_shadow",False)))
            rc=data.get("roof_color")
            if isinstance(rc,str) and len(rc)==7 and rc.startswith("#"):
                try:self.roof_color=tuple(bytes.fromhex(rc[1:]))
                except ValueError:pass
            self.roof_lines.set(bool(data.get("roof_lines",True)))
            self.roof_spacing.set(int(data.get("roof_spacing",7)))
            self.roof_opacity.set(int(data.get("roof_opacity",30)))
            self.roof_softness.set(float(data.get("roof_softness",0.65)))
            self.roof_swatch.configure(bg=self.roof_hex())
            # Older saves with 90-degree rotation remain compatible.
            self.angle=(round(float(data.get("angle",0))/15)*15)%360
            self.angle_label.configure(text=f"{self.angle}°")
            self.active=0;self.refresh_list();self.schedule()
        except Exception as exc:messagebox.showerror('Open Error',str(exc))

if __name__=="__main__":
    root=tk.Tk()
    App(root)
    root.mainloop()
