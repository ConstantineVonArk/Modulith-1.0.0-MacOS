#!/usr/bin/env python3
"""Regression for edge-open recesses (SC3K Architecture Builder 3.25).

Run: python3 test_edge_open_recess_regression.py
Does not require Tk window, and does not modify project assets.
"""
from collections import Counter
from types import SimpleNamespace
from PIL import ImageChops
import volume_editor as ve


def side_fragments(block, wall, open_sides):
    edit=dict(block=0,wall=wall,t0=0,t1=1,z0=0,z1=block.h,
              depth=-6,columns=0,open_sides=open_sides)
    mesh=ve.apply_wall_edits(ve.scene_mesh([block]),[block],[edit])
    axis=0 if wall in ('front','back') else 1
    fixed_axis=1-axis
    fixed={'front':block.y+block.d, 'back':block.y,
           'left':block.x,'right':block.x+block.w}[wall]
    normal={'front':1,'back':-1,'left':-1,'right':1}[wall]
    inner=fixed-6*normal
    outer_min,outer_max=sorted((fixed,inner))
    stats=Counter()
    for pts,kind,normal in mesh:
        if kind!='wall':continue
        for label,coord in [('left',block.x if axis==0 else block.y),
                            ('right',block.x+block.w if axis==0 else block.y+block.d)]:
            if all(abs(p[axis]-coord)<1e-6 for p in pts):
                mean_other=sum(p[fixed_axis] for p in pts)/3
                mean_z=sum(p[2] for p in pts)/3
                if outer_min+.01<mean_other<outer_max-.01 and .01<mean_z<block.h-.01:
                    stats[label]+=1
    side_returns=[1 for pts,kind,normal in mesh
                  if isinstance(kind,tuple) and kind[0]=='edited_wall' and kind[2]=='side']
    back_faces=[1 for pts,kind,normal in mesh
                if isinstance(kind,tuple) and kind[0]=='edited_wall_face']
    return stats,len(side_returns),len(back_faces)


block=ve.Block(x=1,y=2,w=42,d=19,h=25,rise=12)
for wall in ('front','back','left','right'):
    old,old_returns,old_back=side_fragments(block,wall,False)
    new,new_returns,new_back=side_fragments(block,wall,True)
    assert old['left'] and old['right'] and old_returns==4,(wall,old,old_returns)
    assert not new and new_returns==0 and new_back==2,(wall,new,new_returns,new_back)
    print(f'PASS {wall}: side strips removed, back wall preserved')

# Mode affects only selected outer edges. An interior cut still has both returns.
interior=dict(block=0,wall='front',t0=.17,t1=.82,z0=4,z1=20,
              depth=-6,open_sides=True)
mesh=ve.apply_wall_edits(ve.scene_mesh([block]),[block],[interior])
assert sum(1 for _,kind,_ in mesh if isinstance(kind,tuple)
           and kind[0]=='edited_wall' and kind[2]=='side')==4
print('PASS interior niche retains two returns')

# The selection-to-geometry bridge must snap the end modules to real solid edges.
class Var:
    def __init__(self,value): self.value=value
    def get(self):return self.value

def selection_test(selected_cols,enabled):
    obj=SimpleNamespace(
        selected_modules={(0,'front',0,c) for c in selected_cols},
        module_layout={'floors':1,'counts':[3],
                       'spans': [[(.09,.30),(.30,.58),(.58,.91)]]},
        blocks=[block],edit_depth=Var(-6),cut_to_edges=Var(enabled),
        portico_columns=Var(False),portico_count=Var(3),portico_style=Var(1),
        wall_edits=[],_cache_key=None,
        update_context_preview=lambda:None,schedule=lambda:None)
    ve.App.apply_selected_wall_edit(obj)
    return obj.wall_edits[0]

assert (selection_test([0,1,2],True)['t0'],
        selection_test([0,1,2],True)['t1'])==(0.,1.)
assert selection_test([0,1],True)['t0']==0.
assert selection_test([0,1],True)['t1']==.58
assert selection_test([0,1,2],False)['t0']==.09
assert selection_test([0,1,2],False)['t1']==.91
print('PASS selected edge modules snap only in opt-in mode')

# Smoke-test a fronton/portico wing scene at two perspectives, including columns.
main=ve.Block(name='Main',x=0,y=0,w=80,d=12,h=35,rise=12,axis='X')
wing=ve.Block(name='Wing',x=25,y=12,w=32,d=15,h=29,rise=9,axis='Y')
edit=dict(block=1,wall='front',t0=0,t1=1,z0=0,z1=wing.h,
          depth=-8,open_sides=True,columns=3,column_style=1)
for angle in (0,270,315,345):
    img=ve.render_scene([main,wing],angle=angle,wall_edits=[edit])
    assert img.width>0 and img.height>0
    print(f'PASS scene {angle}°')
print('PASS SC3K 3.25 edge-open recess regression')
