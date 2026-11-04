"""Regression for sprite/podium occlusion, using the project's native renderer.

Run with `python3 test_column_base_regression.py` from this folder.
"""
import math
from volume_editor import (Block, apply_wall_edits, column_part_sprite,
                           iso, render_scene, rotate, scene_mesh,
                           portico_column_positions)


def render_and_check(style, angle):
    b=Block(x=0,y=0,w=96,d=28,h=72,rise=12)
    edit={'block':0,'wall':'front','t0':.19,'t1':.8,'z0':8,'z1':57,
          'depth':-11,'columns':3,'column_style':style}
    img=render_scene([b],angle=angle,wall_edits=[edit])
    mesh=apply_wall_edits(scene_mesh([b],2),[b],[edit])
    cx,cy=b.x+b.w/2,b.y+b.d/2
    screen=[iso(rotate(point,angle,cx,cy)) for tri,kind,nrm in mesh
            for point in tri]
    minx=math.floor(min(v[0] for v in screen))
    miny=math.floor(min(v[1] for v in screen))-4
    pad=12
    cell=b.w*(edit['t1']-edit['t0'])/edit['columns']
    size=min(8.0,cell*.96,abs(edit['depth'])-.5)
    _positions=portico_column_positions(b.x+b.w*edit['t0'], b.x+b.w*edit['t1'], edit['columns'], size)
    x=_positions[len(_positions)//2]
    y=b.y+b.d-(size/2+.25)
    bx,by=iso(rotate((x,y,edit['z0']+.55),angle,cx,cy))
    left=round(bx-minx+pad)-8
    base_y=round(by-miny+pad)
    source=column_part_sprite(style,'low',diagonal=False)
    top=base_y-source.getbbox()[3]+3
    checked=0
    # The entire original circular bottom of the base must be preserved.
    for sy in (14,15):
        for sx in range(source.width):
            r,g,bb,a=source.getpixel((sx,sy))
            if not a:continue
            assert a==255, 'Test requires fully opaque ring pixels'
            output=img.getpixel((left+sx,top+sy))
            assert output==(r,g,bb), (
                f'Column style {style}, camera {angle}: bottom row {sy}, '
                f'pixel {sx} was replaced by {output}, expected {(r,g,bb)}')
            checked+=1
    assert checked==12, checked
    return checked


if __name__=='__main__':
    total=0
    for style in (1,2,3):
        for angle in (0,270,285,315,345):
            count=render_and_check(style,angle)
            print(f'OK style {style}, {angle}°: {count} pixels in the base ring')
            total+=count
    print(f'PASS: {total} bottom-ring pixels tested across 15 configurations')
