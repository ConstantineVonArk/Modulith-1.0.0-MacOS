"""Regression for game-style sunlight, soft niche dimming and cast shadows.

Run: python3 test_niche_lighting_regression.py
No Tk GUI needed. In particular, a dark-facing facade must NOT have
sharp column shadows, and a lateral open edge must admit a diagonal light cut.
"""
import math
from PIL import ImageChops
import volume_editor as ve


def test_niche_lighting():
    b=ve.Block(w=100,d=28,h=86,rise=14)
    edit=dict(block=0,wall='front',t0=.17,t1=.82,z0=15,z1=64,
              depth=-12,columns=3,column_style=1)
    for angle in (0,90,270,285,315,345):
        desc=ve._niche_light_descriptors([b],[edit],angle)[0]
        desc_without=ve._niche_light_descriptors([b],[dict(edit,columns=0)],angle)[0]
        assert len(desc[11])==3
        lo,hi=desc[3:5]
        vals=[ve._niche_shadow_strength(desc,'back',lo+(hi-lo)*i/20,
                                        b.y+b.d-12,32) for i in range(21)]
        assert max(vals)-min(vals)>.015, (angle,vals)
        diffs=[ve._niche_shadow_strength(desc,'back',lo+(hi-lo)*i/100,
                                         b.y+b.d-12,32)
               -ve._niche_shadow_strength(desc_without,'back',lo+(hi-lo)*i/100,
                                          b.y+b.d-12,32) for i in range(101)]
        if desc[-1]<=.06:
            assert max(abs(d) for d in diffs)<1e-9,(angle,max(diffs))
        else:
            assert max(diffs)>.04,(angle,max(diffs))
        image=ve.render_scene([b],angle=angle,wall_edits=[edit])
        transparent=ve.render_scene([b],angle=angle,wall_edits=[edit],
                                    transparent_background=True)
        assert image.size==transparent.size and transparent.mode=='RGBA'
        print(f'PASS {angle}°: game lighting, correct cast shadows and transparency')

    # Geometric open-side lighting: a real lateral opening gives a diagonal
    # sun wedge; the same intact side wall blocks that light. The equivalent
    # test at the other end checks both ray directions.
    wide=ve.Block(w=80,d=20,h=68,rise=10)
    full=dict(block=0,wall='front',t0=0,t1=1,z0=10,z1=55,depth=-12,
              columns=0)
    for angle,near_x,far_x in ((330,2,70),(120,78,10)):
        opened=ve._niche_light_descriptors([wide],[dict(full,open_sides=True)],angle)[0]
        closed=ve._niche_light_descriptors([wide],[dict(full,open_sides=False)],angle)[0]
        lit, _=ve._niche_sun_aperture(opened,near_x,8,45)
        blocked, _=ve._niche_sun_aperture(closed,near_x,8,45)
        far, _=ve._niche_sun_aperture(opened,far_x,8,45)
        assert lit>.8 and blocked<.05 and far<.05,(angle,lit,blocked,far)
        print(f'PASS {angle}°: lateral sun wedge, clipped at real roof/edge')

    # When the sun is behind the facade, there must be no direct column or
    # canopy shadow, even with both open sides.
    for wall in ('front','back','left','right'):
        for angle in range(0,360,15):
            ed=dict(full,wall=wall,open_sides=True,columns=3)
            desc=ve._niche_light_descriptors([wide],[ed],angle)[0]
            no_columns=ve._niche_light_descriptors([wide],[dict(ed,columns=0)],angle)[0]
            # Sun direction has to agree with the renderer's art-directed
            # light/dark classification of rotated wall normals.
            nx,ny=desc[2]
            ca,sa=math.cos(math.radians(angle)),math.sin(math.radians(angle))
            rotated_n=(nx*ca-ny*sa,nx*sa+ny*ca)
            assert abs(desc[-1]+.5*(rotated_n[0]-rotated_n[1]))<1e-9
            # Since v3.29, near-frontal views deliberately admit a subtle
            # artistic light cue (-.12 < outward_sun <= .06). Only genuinely
            # back-facing orientations must have zero direct sun exposure.
            if desc[-1]>-.12:continue
            u=(desc[3]+desc[4])/2
            pf=desc[1]-desc[2][1-(0 if wall in ('front','back') else 1)]*12
            x,y=(u,pf) if wall in ('front','back') else (pf,u)
            for z in (12,30,48):
                shade=ve._niche_shadow_strength(desc,'back',x,y,z)
                without=ve._niche_shadow_strength(no_columns,'back',x,y,z)
                assert abs(shade-without)<1e-9,(wall,angle,z,shade,without)
                exposure,_=ve._niche_sun_aperture(desc,x,y,z)
                assert exposure==0.,(wall,angle)
    print('PASS all four wall directions × 24 angles: no invented backlit shadows')

    # Joined recesses remain one opening, not fake floor/ceiling shadows.
    low=dict(edit,z0=15,z1=36,columns=0)
    high=dict(edit,z0=36,z1=64,columns=0)
    joined=ve._niche_light_descriptors([b],[low,high],0)
    assert joined[0][5:7]==(15,64) and joined[1][5:7]==(15,64)
    assert ve._niche_light_descriptors([b],[dict(edit,depth=3)],0)[0] is None
    assert ve.render_scene([b],wall_edits=None).mode=='RGB'
    print('PASS joined cuts and plain-wall control')

if __name__=='__main__':
    test_niche_lighting()
