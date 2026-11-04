#!/usr/bin/env python3
"""SC3K Facade Generator v4 — separate module and anchored facade stages."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, colorchooser, messagebox
from PIL import Image, ImageTk, ImageColor
import json, random, colorsys, re, copy, os
from toolbar_icons import thumbnail, attach_tooltip

ROOT=Path(__file__).resolve().parent
LIBRARY=ROOT/'library'; OUT=Path(os.environ.get('SC3K_USER_OUTPUT',str(ROOT/'output'))); OUT.mkdir(parents=True,exist_ok=True)
SHEETS={
 'default wall 12x25.png':('wall',(12,25)),
 'rustication_2x5.png':('rustication',(2,5)),
 'cornice_2x5.png':('cornice',(2,5)),
 'foundation_2x5.png':('foundation',(2,5)),
}
LABELS={'glass':'Glass','frame':'Window frame','casing':'Casing','sill':'Sill','bracket':'Bracket','sandrik':'Pediment','cornice':'Cornice'}
ARCH_PALETTE=[('Ivory','#D8D0C2'),('Warm limestone','#C9BBA5'),('Sand','#C7B18D'),('Light ochre','#BDA477'),('Dusty rose','#B98F87'),('Terracotta','#A96850'),('Muted sage','#9CA58C'),('Grey green','#7F938A'),('Dusty blue','#8FA6B4'),('Slate blue','#667F91'),('Grey beige','#AAA39A'),('Warm grey','#8F8981'),('Cream','#E4DCCB'),('Grey lilac','#A59AA7')]


LEGACY_LABELS = {'Двускатная':'Gable','Четырёхскатная':'Hip',
    'Люкарна':'Dormer','Дымоход':'Chimney',
    'Пиксели':'Pixels','Мягкое':'Smooth','Детальное':'Detailed',
    'Сохранить светотень':'Preserve shading','Сдвиг оттенка':'Hue shift',
    'Обычное':'Standard','Арочное':'Arched','Равномерно':'Even spacing'}

def _read_legacy_labels(obj):
    if isinstance(obj,dict): return {k:_read_legacy_labels(v) for k,v in obj.items()}
    if isinstance(obj,list): return [_read_legacy_labels(v) for v in obj]
    if isinstance(obj,str): return LEGACY_LABELS.get(obj,obj)
    return obj

ORDER=('glass','frame','casing','sill','bracket','sandrik','cornice')
WINDOW_SIZES=('L','M','S','XS','XXS')
WINDOW_ASSETS={'frame':'frames','casing':'casing','sandrik':'padiment','sill':'sills'}

def split_sheet(path,cell):
 im=Image.open(path).convert('RGBA'); cw,ch=cell; result=[]
 for y in range(im.height//ch):
  for x in range(im.width//cw):
   crop=im.crop((x*cw,y*ch,(x+1)*cw,(y+1)*ch))
   if crop.getbbox(): result.append(crop)
 return result

def paired_sheet(path, cell, size=None):
 """A pair is (ISO, FRONT); preserve blank cells to avoid shifting pair IDs."""
 sheet=Image.open(path).convert('RGBA')
 cw,ch=cell
 if cw<=0 or ch<=0 or sheet.width%cw or sheet.height%ch:
  raise ValueError(f'{path.name}: sheet {sheet.size} is not divisible by cell {cell}')
 cells=[sheet.crop((x,y,x+cw,y+ch)) for y in range(0,sheet.height,ch) for x in range(0,sheet.width,cw)]
 if len(cells)%2:
  raise ValueError(f'{path.name}: expected ISO/FRONT pairs, got {len(cells)} cells')
 return [{'name':f'{path.stem} #{i//2+1}', 'image':cells[i],
          'front_image':cells[i+1], 'size':size, 'pair_index':i//2}
         for i in range(0,len(cells),2)]

def place_clipped(target, sprite, x, y):
 # Alpha-composite a sprite even when its pixel offset is negative or outside the module.
 left=max(0,x); top=max(0,y); right=min(target.width,x+sprite.width); bottom=min(target.height,y+sprite.height)
 if right<=left or bottom<=top: return
 crop=sprite.crop((left-x,top-y,right-x,bottom-y))
 target.alpha_composite(crop,(left,top))

def recolor_wall(source,color):
 im=source.convert('RGBA'); target=ImageColor.getrgb(color); px=im.load()
 for y in range(im.height):
  for x in range(im.width):
   r,g,b,a=px[x,y]
   if not a: continue
   lum=(.299*r+.587*g+.114*b)/255; f=.72+lum*.38
   px[x,y]=(max(0,min(255,int(target[0]*f))),max(0,min(255,int(target[1]*f))),max(0,min(255,int(target[2]*f))),a)
 return im

def tint_sprite(source, color, mode='shade', strength=100):
 # Non-destructive recolor: alpha is untouched, pixel edges remain crisp.
 im=source.convert('RGBA'); target=ImageColor.getrgb(color); px=im.load(); amount=max(0,min(100,int(strength)))/100
 tr,tg,tb=[v/255 for v in target]
 th,ts,tv=colorsys.rgb_to_hsv(tr,tg,tb)
 for y in range(im.height):
  for x in range(im.width):
   r,g,b,a=px[x,y]
   if a==0: continue
   rr,gg,bb=r/255,g/255,b/255
   if mode=='hue':
    h,ss,v=colorsys.rgb_to_hsv(rr,gg,bb)
    # Preserve the source's tonal structure while shifting its hue toward chosen color.
    nh=(h+th)%1 if ss>0.08 else th
    ns=max(ss,ts*0.72)
    nr,ng,nb=colorsys.hsv_to_rgb(nh,ns,v)
   else:
    lum=(0.299*r+0.587*g+0.114*b)/255
    # A gently curved luminance map retains hand-painted highlights and shadows.
    factor=0.40+lum*0.78
    nr,ng,nb=min(1,tr*factor),min(1,tg*factor),min(1,tb*factor)
   px[x,y]=(round(r*(1-amount)+nr*255*amount),round(g*(1-amount)+ng*255*amount),round(b*(1-amount)+nb*255*amount),a)
 return im

class App:
 def __init__(self,root):
  self.root=root; root.title('Modulith 1.0.0'); root.geometry('1500x990'); root.minsize(1030,720)
  # The app bundle uses the .icns. Tk may also use this PNG for the window/Dock icon.
  self._app_icon=None
  try:
   self._app_icon=ImageTk.PhotoImage(Image.open(ROOT/'app_icon.png').convert('RGBA').resize((128,128),Image.Resampling.LANCZOS),master=root)
   root.iconphoto(True,self._app_icon)
  except (tk.TclError,OSError):
   pass
  self.assets={k:[] for k in ('wall',)+ORDER+('rustication','foundation')}; self.wall_color='#D8D0C2'; self.window_size=tk.StringVar(value='M'); self.window_shape=tk.StringVar(value='Standard')
  self.component_colors={c:None for c in ORDER}; self.component_modes={c:'shade' for c in ORDER}; self.component_strength={c:100 for c in ORDER}
  self.enabled={c:False for c in ORDER}; self.choice={c:None for c in ORDER}; self.offset={c:[0,0] for c in ORDER}
  self.front_offset={c:[0,0] for c in ORDER}; self.module_view=tk.StringVar(value='ISO')
  self.cols=tk.IntVar(value=5); self.floors=tk.IntVar(value=5)
  # Independent art and module counts per physical wall. Opposite walls
  # share the real building span, but not their windows or decorative states.
  self.wall_names={'front':'Front (main)','back':'Back','left':'Left','right':'Right'}
  self.active_wall='front'
  self.wall_configs={}
  self.pair_widths={'front':48,'side':32}
  self.wall_selector=tk.StringVar(value=self.wall_names['front'])
  self.facade_width=tk.IntVar(value=48)
  self.floor_counts=[tk.IntVar(value=v) for v in (4,6,8,6)]
  self.distribution=tk.StringVar(value='Even spacing')
  self.side_margin=tk.IntVar(value=4); self.group_size=tk.IntVar(value=2); self.group_gap=tk.IntVar(value=6)
  # Anchors are pixel offsets between corresponding module origins.
  self.step_x=tk.IntVar(value=12); self.step_y=tk.IntVar(value=0)
  self.row_x=tk.IntVar(value=0); self.row_y=tk.IntVar(value=25)
  self.module=None; self.facade=None; self.facade_front=None; self.layers={}; self.photo=None; self.drag=None
  self.extra_wall_height=tk.IntVar(value=0)
  self.type_names=['Ground floor','Second floor','Middle floor','Top floor']
  self.active_type=0; self.independent_edit=tk.BooleanVar(value=False); self.type_states={}; self.type_modules={}
  self.rust_first=tk.BooleanVar(value=False); self.rust_second=tk.BooleanVar(value=False); self.rust_middle=tk.BooleanVar(value=False); self.rust_upper=tk.BooleanVar(value=False); self.rust_count=tk.IntVar(value=5)
  self.first_foundation=tk.BooleanVar(value=False); self.foundation_choice=None; self.foundation_color='#C9BBA5'
  self.foundation_color_enabled=tk.BooleanVar(value=True)
  self.foundation_x=tk.IntVar(value=0); self.foundation_y=tk.IntVar(value=0)
  self._module_popup_windows={}; self._module_sections={}; self._elevation_hits=[]; self._module_selected_type_widgets=[]
  self._elevation_photo_refs={};self._elevation_render_busy=False
  self._build(); self.load_assets(); self._capture_type_state(); self.compose_module()
  from volume_editor import App as VolumeApp
  self.volume_app=VolumeApp(self.tab_volume,embedded=True)
  self.volume_app.on_open_module=lambda:self._show_workspace('iso')
  self.volume_app.on_module_view=self._volume_toolbar_module_view
  self.volume_app.on_open_palette=lambda:self.open_palette('wall')
  self.volume_app.on_open_facade=lambda:self._show_workspace('facade')
  self.volume_sync_enabled=tk.BooleanVar(value=True)
  self.volume_apply_enabled=tk.BooleanVar(value=True)
  self.volume_filter=tk.StringVar(value='Pixels')
  self.volume_auto_filter=tk.BooleanVar(value=True)
  self.volume_app.rotation_callback=self._refresh_auto_filter
  self._build_volume_bridge()
  self._install_workspace_navigation()
  self._install_global_tools()
  self.tabs.bind('<<NotebookTabChanged>>',self._on_tab_changed)
  self.facade_width.trace_add('write', self._facade_width_changed)
  # Assemble an editable default facade on first launch, even before any user action.
  self._live_apply_id=None
  self.root.after_idle(self._flush_live_module)
 def _build(self):
  # Native Mac window title is sufficient; use the space for the scene.
  # Technical details stay in controls, rather than crowding the title bar.
  style=ttk.Style(self.root)
  style.layout('SC3K.HiddenTabs.TNotebook.Tab',[])
  self.tabs=ttk.Notebook(self.root,style='SC3K.HiddenTabs.TNotebook'); self.tabs.pack(fill='both',expand=True,padx=6,pady=(0,5))
  self.tab_module=ttk.Frame(self.tabs); self.tab_facade=ttk.Frame(self.tabs); self.tab_volume=ttk.Frame(self.tabs)
  self.tabs.add(self.tab_module,text='1 · Facade Module'); self.tabs.add(self.tab_facade,text='2 · Facade Assembly'); self.tabs.add(self.tab_volume,text='3 · Building Volume')
  self.build_module_tab(); self.build_facade_tab()
 def _volume_toolbar_module_view(self,mode):
  self._show_workspace('front' if mode=='FRONT' else 'iso')
  self.module_view.set(mode)
  self.change_module_view()

 def _install_workspace_navigation(self):
  """A single workspace shell; existing editors keep their actual widgets."""
  self.workspace_bar=ttk.Frame(self.root,padding=(10,3))
  self.workspace_bar.pack(before=self.tabs,fill='x')
  self.workspace_buttons={};self.workspace_icons={}
  specs=[('volume','volume_editor.png','Building Volume',lambda:self._show_workspace('volume')),
         ('front','front_module.png','Front Module',lambda:self._show_workspace('front')),
         ('iso','default_module.png','Isometric Module',lambda:self._show_workspace('iso')),
         ('facade','module_editor.png','Facade Assembly',lambda:self._show_workspace('facade'))]
  for name,filename,title,action in specs:
   path=LIBRARY/'toolbar'/filename
   if not path.exists():continue
   with Image.open(path) as src:
    photo=ImageTk.PhotoImage(thumbnail(src,32),master=self.root)
   self.workspace_icons[name]=photo
   button=tk.Button(self.workspace_bar,image=photo,width=42,height=40,bg='#edf0f1',bd=2,
                    relief='raised',activebackground='#b6dbe9',command=action,cursor='hand2')
   button.pack(side='left',padx=3)
   self.workspace_buttons[name]=button
   button.bind('<Enter>',lambda e,t=title:self.workspace_label.configure(text=t))
   button.bind('<Leave>',lambda e:self.workspace_label.configure(text=''))
   attach_tooltip(button,title)
  self.workspace_label=ttk.Label(self.workspace_bar,text='')
  self.workspace_label.pack(side='left',padx=12)
  self.tabs.bind('<<NotebookTabChanged>>',lambda e:self._sync_workspace_buttons(),add='+')
  self._show_workspace('volume')

 def _show_workspace(self,name):
  if name=='volume':target=self.tab_volume
  elif name=='facade':target=self.tab_facade
  else:
   target=self.tab_module
   self.module_view.set('FRONT' if name=='front' else 'ISO')
   self.change_module_view()
  self.tabs.select(target)
  self._sync_workspace_buttons()

 def _sync_workspace_buttons(self):
  if not hasattr(self,'workspace_buttons'):return
  active=self.tabs.select()
  name='volume' if active==str(self.tab_volume) else ('facade' if active==str(self.tab_facade) else ('front' if self.module_view.get()=='FRONT' else 'iso'))
  for key,button in self.workspace_buttons.items():
   on=key==name
   button.configure(relief='sunken' if on else 'raised',bg='#a6d3e6' if on else '#edf0f1',
                    highlightthickness=2 if on else 0,highlightbackground='#397b9b')

 def _install_global_tools(self):
  """Always-visible toolbar underneath workspace navigation; icon actions call
  the original Volume Editor commands, retaining the tested implementation."""
  vol=self.volume_app
  bar=ttk.Frame(self.root,padding=(12,0,12,5))
  bar.pack(before=self.tabs,fill='x')
  self.global_toolbar=bar
  self.global_tool_buttons={}
  self.global_tool_icons={}
  self._global_tool_order=[]
  for key,original in vol._toolbar_items:
   if key in ('select',):continue
   command=(self._global_palette_menu if key=='palette' else (lambda b=original:b.invoke()))
   self._add_global_tool(key,key+'.png',command, enabled=str(original.cget('state'))!='disabled')
  self._add_global_tool('save_all','save_all.png',self._global_save_menu)
  self._add_global_tool('smoothing','smoothing.png',self._global_smoothing_menu)
  self._add_global_tool('rustication','rustication.png',lambda:self._open_module_popup('rust'))
  self._add_global_tool('module_decor','module_decor.png',lambda:self._open_module_popup('decor'))
  self._add_global_tool('elevations','elevations.png',self._open_elevations)
  # Keep the existing buttons internally for callbacks and state changes,
  # but remove their toolbar and hint from the scene to free vertical space.
  vol._toolbar_host.pack_forget()
  vol.external_toolbar_buttons=self.global_tool_buttons
  self._reflow_global_tools()
  bar.bind('<Configure>',lambda e:self._reflow_global_tools(e.width),add='+')
  original_sync=vol._sync_toolbar
  def sync_and_update():
   original_sync()
   self._sync_global_tool_states()
  vol._sync_toolbar=sync_and_update
  for variable in (vol.tool_mode,vol.module_select_mode,vol.cast_shadow,vol.portico_columns):
   variable.trace_add('write',lambda *_:self.root.after_idle(self._sync_global_tool_states))
  self._sync_global_tool_states()

 def _add_global_tool(self,key,filename,callback,enabled=True):
  path=LIBRARY/'toolbar'/filename
  if not path.exists():return
  with Image.open(path) as source:
   im=thumbnail(source,31)
  photo=ImageTk.PhotoImage(im,master=self.root)
  self.global_tool_icons[key]=photo
  btn=tk.Button(self.global_toolbar,image=photo,width=36,height=36,bd=2,
                relief='raised',bg='#edf0f1',activebackground='#b6dbe9',
                state='normal' if enabled else 'disabled',command=callback)
  self.global_tool_buttons[key]=btn
  self._global_tool_order.append((key,btn))
  btn.bind('<Enter>',lambda e,k=key:self.workspace_label.configure(text=self._global_tips.get(k,k)))
  btn.bind('<Leave>',lambda e:self.workspace_label.configure(text=''))
  attach_tooltip(btn,self._global_tips.get(key,key))

 _global_tips={'save_all':'Open / save JSON, export PNG',
               'smoothing':'Smoothing: pixels / smooth / detailed',
               'cast_shadow':'Toggle cast shadows',
               'cell':'Select cell, horizontal row or column (V)',
               'extrude':'Extrude wall or create a recess (E)',
               'pan':'Hand — pan scene (H)',
               'orbit':'Rotate view left/right by 15° (R)',
               'shift_extrude':'Keep rear face — not yet available',
               'split_horizontal':'Split cell horizontally — not yet available',
               'split_vertical':'Split cell vertically — not yet available',
               'merge':'Merge cells — not yet available',
               'undo':'Undo extrusion (⌘Z)',
               'redo':'Redo extrusion (⌘⇧Z)',
               'add_item':'Add body, dormer or chimney',
               'remove_item':'Remove body, roof accessory or projection',
               'zoom_tool':'Magnifier — zoom in or out (Z)',
               'confirm':'Apply selected extrusion / recess',
               'body_size':'Open body dimensions and geometry',
               'roof_settings':'Open roof and accessory settings',
               'columns_tool':'Enable niche columns / colonnade settings',
               'rustication':'Floor rustication settings',
               'module_decor':'Facade module windows and decoration settings',
               'elevations':'Four-wall elevations: wall and floor selection',
               'palette':'Change wall or selected detail colour'}

 def _reflow_global_tools(self,width=None):
  if not hasattr(self,'_global_tool_order'):return
  width=width if width is not None else max(640,self.root.winfo_width()-24)
  n=max(1,min(len(self._global_tool_order),int(max(1,width-12)//43)))
  if getattr(self,'_global_columns',None)==n:return
  self._global_columns=n
  for _,btn in self._global_tool_order:btn.grid_forget()
  for i,(_,btn) in enumerate(self._global_tool_order):
   btn.grid(row=i//n,column=i%n,padx=1,pady=1,sticky='w')

 def _sync_global_tool_states(self):
  if not hasattr(self,'global_tool_buttons'):return
  vol=self.volume_app
  for key,btn in self.global_tool_buttons.items():
   source=vol._toolbar_buttons.get(key)
   if source is not None:
    active=str(source.cget('relief'))=='sunken'
    if key in ('cell','extrude','pan','zoom_tool','columns_tool','cast_shadow'):
     btn.configure(relief='sunken' if active else 'raised',
                   bg='#a5d2e7' if active else '#edf0f1',
                   highlightbackground='#397b9b',highlightthickness=2 if active else 0)
  for key,which in (('rustication','rust'),('module_decor','decor'),('elevations','elevations')):
   btn=self.global_tool_buttons.get(key)
   if btn is None:continue
   window=self._module_popup_windows.get(which)
   opened=bool(window and window.winfo_exists() and window.state()!='withdrawn')
   btn.configure(relief='sunken' if opened else 'raised',bg='#a5d2e7' if opened else '#edf0f1',
                 highlightbackground='#397b9b',highlightthickness=2 if opened else 0)

 def _popup_global(self,key,menu):
  b=self.global_tool_buttons.get(key)
  if b:
   try:menu.tk_popup(b.winfo_rootx(),b.winfo_rooty()+b.winfo_height())
   finally:menu.grab_release()

 def _global_save_menu(self):
  menu=tk.Menu(self.root,tearoff=False)
  menu.add_command(label='Open facade project JSON…',command=self.load_project)
  menu.add_command(label='Save facade project JSON…',command=self.save_project)
  menu.add_command(label='Export facade PNG…',command=self.export_facade)
  menu.add_separator()
  menu.add_command(label='Open volume project JSON…',command=self.volume_app.import_json)
  menu.add_command(label='Save volume project JSON…',command=self.volume_app.export_json)
  menu.add_command(label='Export building PNG…',command=self.volume_app.export_png)
  menu.add_separator()
  menu.add_command(label='Save module PNG + JSON…',command=self.save_module)
  self._popup_global('save_all',menu)

 def _global_smoothing_menu(self):
  menu=tk.Menu(self.root,tearoff=False)
  for mode in ('Pixels','Smooth','Detailed'):
   menu.add_radiobutton(label=mode,variable=self.volume_filter,value=mode,
                        command=self._manual_filter_selected)
  menu.add_separator()
  menu.add_checkbutton(label='Automatic smoothing selection',variable=self.volume_auto_filter,
                       command=self._refresh_auto_filter)
  self._popup_global('smoothing',menu)

 def build_module_tab(self):
  # Scrollable left control panel: keeps lower buttons reachable on short screens.
  panel=ttk.Frame(self.tab_module,width=310); panel.pack(side='left',fill='y'); panel.pack_propagate(False)
  left_canvas=tk.Canvas(panel,highlightthickness=0,width=300)
  left_scroll=ttk.Scrollbar(panel,orient='vertical',command=left_canvas.yview)
  left_canvas.configure(yscrollcommand=left_scroll.set)
  left_scroll.pack(side='right',fill='y')
  left_canvas.pack(side='left',fill='both',expand=True)
  left=ttk.Frame(left_canvas,padding=8)
  left_window=left_canvas.create_window((0,0),window=left,anchor='nw')
  def _module_panel_configure(_event=None):
   left_canvas.configure(scrollregion=left_canvas.bbox('all'))
  def _module_canvas_configure(event):
   left_canvas.itemconfigure(left_window,width=event.width)
  left.bind('<Configure>',_module_panel_configure)
  left_canvas.bind('<Configure>',_module_canvas_configure)
  def _module_wheel(event):
   if getattr(event,'delta',0): left_canvas.yview_scroll(int(-event.delta/120) or (-1 if event.delta>0 else 1),'units')
   elif getattr(event,'num',None)==4: left_canvas.yview_scroll(-1,'units')
   elif getattr(event,'num',None)==5: left_canvas.yview_scroll(1,'units')
  left_canvas.bind_all('<MouseWheel>',_module_wheel,add='+')
  left_canvas.bind_all('<Button-4>',_module_wheel,add='+')
  left_canvas.bind_all('<Button-5>',_module_wheel,add='+')
  right=ttk.Frame(self.tab_module,padding=8); right.pack(side='right',fill='both',expand=True)
  self.module_left=left
  self.wall_name_label=ttk.Label(left,text=self.wall_names['front'])
  # Existing helper variables remain for drag interaction and old JSON.
  self.selected=tk.StringVar(value=LABELS['glass'])
  self.xvar=tk.IntVar(value=0); self.yvar=tk.IntVar(value=0)
  self.selected_label=ttk.Label(left,text='Selected detail: Glass')
  self.mode_var=tk.StringVar(value='Preserve shading')
  self.wall_palette=tk.StringVar(value=ARCH_PALETTE[0][0])
  self.swatch=tk.Label(left,text=self.wall_color,bg=self.wall_color)
  self.check_vars={c:tk.BooleanVar(value=False) for c in ORDER}
  self.selector=ttk.Combobox(left,state='readonly',textvariable=self.selected,values=[LABELS[c] for c in ORDER])
  self.selector.bind('<<ComboboxSelected>>',self.sync_offset)
  self.asset_info=tk.StringVar(value='')
  ttk.Label(left,text='FACADE MODULES',font=('TkDefaultFont',11,'bold')).pack(anchor='w',pady=(0,8))
  ttk.Label(left,text='Selected wall:',font=('TkDefaultFont',9)).pack(anchor='w')
  ttk.Label(left,textvariable=self.wall_selector,font=('TkDefaultFont',10,'bold')).pack(anchor='w',pady=(1,6))
  self._make_module_section(left,'elevation','Wall Elevations',self._build_elevation_tray)
  self._make_module_section(left,'decor','Module Windows & Decor',self._build_decor_controls)
  self._make_module_section(left,'rust','Floor Rustication',self._build_rust_controls)
  self._make_module_section(left,'color','Detail Recolouring',self._build_color_controls)
  # Modules update automatically after every edit; no Apply step is necessary.
  ttk.Label(left,textvariable=self.asset_info,wraplength=260).pack(anchor='w',pady=3)
  controls=ttk.Frame(right);controls.pack(fill='x',pady=(0,5))
  ttk.Label(controls,text='Wall:',font=('TkDefaultFont',10,'bold')).pack(side='left',padx=(0,5))
  self.module_preview_wall=ttk.Combobox(controls,state='readonly',textvariable=self.wall_selector,
                                      values=list(self.wall_names.values()),width=24)
  self.module_preview_wall.pack(side='left',padx=(0,16))
  self.module_preview_wall.bind('<<ComboboxSelected>>',self.switch_wall)
  # Hidden legacy API for old automation/tests; no duplicate widget on screen.
  self.module_preview_view=self.module_view
  # ISO/FRONT is selected exclusively with the four workspace icons.
  ttk.Label(controls,text='Floor:',font=('TkDefaultFont',10,'bold')).pack(side='left',padx=(0,5))
  self.preview_floor_choice=ttk.Combobox(controls,state='readonly',values=self.type_names,width=16)
  self.preview_floor_choice.current(self.active_type)
  self.preview_floor_choice.pack(side='left',padx=(0,8))
  self.preview_floor_choice.bind('<<ComboboxSelected>>',lambda e:self._module_change_type(self.preview_floor_choice.current()))
  self._module_selected_type_widgets.append(self.preview_floor_choice)
  ttk.Button(controls,text='Four-wall elevations…',command=self._open_elevations).pack(side='right')
  ttk.Label(right,text='Floor types · select or drag a detail with the mouse',font=('TkDefaultFont',10,'bold')).pack(anchor='w')
  preview_grid=ttk.Frame(right); preview_grid.pack(fill='both',expand=True,pady=(5,4))
  preview_grid.grid_columnconfigure(0,weight=1,uniform='module')
  preview_grid.grid_columnconfigure(1,weight=1,uniform='module')
  preview_grid.grid_rowconfigure(0,weight=1,uniform='module')
  preview_grid.grid_rowconfigure(1,weight=1,uniform='module')
  self.type_canvases=[]; self.type_photos=[None]*4
  for idx,name in enumerate(self.type_names):
   card=ttk.Frame(preview_grid,relief='solid',borderwidth=2); card.grid(row=idx//2,column=idx%2,sticky='nsew',padx=3,pady=3)
   title=ttk.Label(card,text=name,font=('TkDefaultFont',10,'bold')); title.pack(anchor='w',padx=4,pady=2)
   cv=tk.Canvas(card,bg='#505357',highlightthickness=0); cv.pack(fill='both',expand=True)
   cv.bind('<Configure>',lambda e,i=idx:self.show_type_preview(i))
   cv.bind('<Button-1>',lambda e,i=idx:self.preview_click(i,e))
   cv.bind('<B1-Motion>',self.move_drag); cv.bind('<ButtonRelease-1>',lambda e:setattr(self,'drag',None))
   self.type_canvases.append(cv)
  self.module_canvas=self.type_canvases[0]
  self.module_status=tk.StringVar(value=''); ttk.Label(right,textvariable=self.module_status).pack(anchor='w')
 def _preview_view_selected(self,event=None):
  self.change_module_view()
  self._sync_workspace_buttons()

 def _build_elevation_tray(self,parent):
  ttk.Label(parent,text='Click a facade or floor to select its wall and module type.',
            wraplength=265,justify='left').pack(anchor='w',pady=(0,5))
  canvas=tk.Canvas(parent,bg='#505357',highlightthickness=0,height=214)
  canvas.pack(fill='x',pady=(0,5))
  self.elevations_tray_canvas=canvas
  canvas.bind('<Configure>',lambda e:self._draw_elevations(canvas),add='+')
  canvas.bind('<Button-1>',lambda e:self._elevation_click(e,canvas))
  ttk.Button(parent,text='Open enlarged elevation…',command=self._open_elevations).pack(fill='x',pady=(2,0))

 def _make_module_section(self,parent,key,title,builder):
  container=ttk.Frame(parent)
  container.pack(fill='x',pady=(0,6))
  header=tk.Button(container,text='▸ '+title,anchor='w',bg='#eef0f2',activebackground='#d8ecf7',bd=1,
                   relief='raised',command=lambda:self._toggle_module_section(key))
  header.pack(fill='x')
  content=ttk.Frame(container,padding=(7,8,7,10))
  self._module_sections[key]={'header':header,'content':content,'title':title,'open':False}
  builder(content)
  return content

 def _toggle_module_section(self,key,opened=None):
  section=self._module_sections[key]
  on=not section['open'] if opened is None else bool(opened)
  section['open']=on
  section['header'].configure(text=('▾ ' if on else '▸ ')+section['title'])
  if on:section['content'].pack(fill='x')
  else:section['content'].pack_forget()

 def _module_change_type(self,index):
  self.type_selector.current(index)
  self.select_type()
  for widget in self._module_selected_type_widgets:
   try:widget.current(index)
   except Exception:pass

 def _build_decor_controls(self,parent):
  ttk.Label(parent,text='Editable floor type').pack(anchor='w',pady=(0,2))
  box=ttk.Combobox(parent,state='readonly',values=self.type_names,width=26)
  box.current(self.active_type);box.pack(fill='x',pady=(0,6))
  box.bind('<<ComboboxSelected>>',lambda e,w=box:self._module_change_type(w.current()))
  self._module_selected_type_widgets.append(box)
  if not hasattr(self,'type_selector'):self.type_selector=box
  ttk.Checkbutton(parent,text='Edit floor types independently',variable=self.independent_edit,
                  command=self.toggle_independent).pack(anchor='w',pady=(2,7))
  ttk.Label(parent,text='Window size').pack(anchor='w',pady=(2,2))
  wc=ttk.Combobox(parent,state='readonly',textvariable=self.window_size,
                  values=['L','M','S','XS','XXS'],width=13)
  wc.pack(fill='x');wc.bind('<<ComboboxSelected>>',self.change_window_size)
  ttk.Label(parent,text='Window shape').pack(anchor='w',pady=(7,2))
  sh=ttk.Combobox(parent,state='readonly',textvariable=self.window_shape,
                  values=['Standard','Arched'],width=21)
  sh.pack(fill='x');sh.bind('<<ComboboxSelected>>',self.change_window_shape)
  ttk.Label(parent,text='Extra wall height (px)').pack(anchor='w',pady=(7,2))
  hh=ttk.Spinbox(parent,from_=-20,to=80,textvariable=self.extra_wall_height,width=7,command=self.compose_module)
  hh.pack(anchor='w');hh.bind('<Return>',lambda e:self.compose_module());hh.bind('<FocusOut>',lambda e:self.compose_module())
  ttk.Separator(parent).pack(fill='x',pady=8)
  ttk.Label(parent,text='Decorative components',font=('TkDefaultFont',10,'bold')).pack(anchor='w',pady=4)
  for c in ORDER:
   row=ttk.Frame(parent);row.pack(fill='x',pady=2)
   ttk.Checkbutton(row,text=LABELS[c],variable=self.check_vars[c],command=lambda c=c:self.toggle(c)).pack(side='left')
   ttk.Button(row,text='↻ another',width=9,command=lambda c=c:self.reroll(c)).pack(side='right')
  ttk.Button(parent,text='Wall / detail colour…',command=self._global_palette_menu).pack(fill='x',pady=(9,2))
  ttk.Label(parent,text='Click a detail in the preview to select it; drag to move it.',wraplength=265).pack(anchor='w',pady=(6,2))

 def _build_rust_controls(self,parent):
  for label,var in (('On the ground floor',self.rust_first),('On the second floor',self.rust_second),
                    ('On middle floors',self.rust_middle),('On the top floor',self.rust_upper)):
   ttk.Checkbutton(parent,text=label,variable=var,command=self._rust_changed).pack(anchor='w',pady=3)
  row=ttk.Frame(parent);row.pack(fill='x',pady=(6,4))
  ttk.Label(row,text='Number of strips').pack(side='left')
  spin=ttk.Spinbox(row,from_=1,to=20,textvariable=self.rust_count,width=6,command=self._rust_changed)
  spin.pack(side='right');spin.bind('<Return>',self._rust_changed);spin.bind('<FocusOut>',self._rust_changed)
  ttk.Label(parent,text='Rustication overlays walls beneath windows and decoration without obscuring them.',wraplength=265).pack(anchor='w',pady=(4,2))

 def _build_color_controls(self,parent):
  ttk.Label(parent,text='Click a detail in the preview to recolour it.',wraplength=265).pack(anchor='w',pady=(0,6))
  self.component_selection_text=tk.StringVar(value='Selected detail: Glass') if not hasattr(self,'component_selection_text') else self.component_selection_text
  ttk.Label(parent,textvariable=self.component_selection_text).pack(anchor='w',pady=(1,5))
  row=ttk.Frame(parent);row.pack(fill='x',pady=3)
  ttk.Button(row,text='Choose detail colour…',command=lambda:self.open_palette('component')).pack(side='left',fill='x',expand=True)
  if not hasattr(self,'component_swatch'):
   self.component_swatch=tk.Label(row,text='Original',bg='#d8d0c2',relief='groove',width=8)
   self.component_swatch.pack(side='right',padx=(5,0),ipady=3)
  cb=ttk.Combobox(parent,state='readonly',textvariable=self.mode_var,
                  values=['Preserve shading','Hue shift'],width=24)
  cb.pack(fill='x',pady=(6,3));cb.bind('<<ComboboxSelected>>',self.change_component_mode)
  ttk.Button(parent,text='Reset selected detail colour',command=self.reset_component_color).pack(fill='x',pady=(2,3))

 def _rust_changed(self,event=None):
  self.compose_module()
  if hasattr(self,'wall_configs') and getattr(self,'module_applied',False):
   self.render_facade()

 def _global_palette_menu(self):
  menu=tk.Menu(self.root,tearoff=False)
  menu.add_command(label='Recolour wall…',command=lambda:self._palette_choice('wall'))
  menu.add_command(label='Recolour detail…',command=lambda:self._palette_choice('component'))
  self._popup_global('palette',menu)

 def _palette_choice(self,target):
  self._show_workspace('iso' if self.module_view.get()!='FRONT' else 'front')
  if target=='component':
   self._toggle_module_section('color',True)
  self.open_palette(target)

 def _open_module_popup(self,which):
  self._show_workspace('front' if self.module_view.get()=='FRONT' else 'iso')
  self._toggle_module_section(which,True)
  window=self._module_popup_windows.get(which)
  if window is None or not window.winfo_exists():
   window=tk.Toplevel(self.root)
   window.transient(self.root)
   window.attributes('-topmost',True)
   title='Module Windows & Decor' if which=='decor' else 'Floor Rustication'
   window.title(title+' — Modulith'); window.geometry('345x665' if which=='decor' else '345x370')
   window.minsize(290,280)
   window.protocol('WM_DELETE_WINDOW',lambda w=window,k=which:self._hide_module_popup(k))
   outer=ttk.Frame(window,padding=8);outer.pack(fill='both',expand=True)
   top=ttk.Frame(outer);top.pack(fill='x')
   ttk.Label(top,text=title,font=('TkDefaultFont',12,'bold')).pack(side='left')
   ttk.Button(top,text='Close',command=lambda k=which:self._hide_module_popup(k)).pack(side='right')
   canvas=tk.Canvas(outer,bg='#e8e8e8',highlightthickness=0)
   scrollbar=ttk.Scrollbar(outer,orient='vertical',command=canvas.yview)
   scrollbar.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
   canvas.configure(yscrollcommand=scrollbar.set)
   inner=ttk.Frame(canvas,padding=6)
   item=canvas.create_window((0,0),window=inner,anchor='nw')
   inner.bind('<Configure>',lambda e,c=canvas:c.configure(scrollregion=c.bbox('all')))
   canvas.bind('<Configure>',lambda e,c=canvas,i=item:c.itemconfigure(i,width=e.width))
   (self._build_decor_controls if which=='decor' else self._build_rust_controls)(inner)
   self._module_popup_windows[which]=window
  window.deiconify();window.attributes('-topmost',True);window.lift();window.focus_set()
  self._sync_global_tool_states()

 def _hide_module_popup(self,which):
  window=self._module_popup_windows.get(which)
  if window and window.winfo_exists():window.withdraw()
  self._sync_global_tool_states()

 def _open_elevations(self):
  self._show_workspace('front' if self.module_view.get()=='FRONT' else 'iso')
  window=self._module_popup_windows.get('elevations')
  if window is None or not window.winfo_exists():
   window=tk.Toplevel(self.root);window.title('Facade Elevations — Modulith')
   window.geometry('1150x660');window.minsize(660,420);window.transient(self.root);window.attributes('-topmost',True)
   window.protocol('WM_DELETE_WINDOW',lambda:self._hide_module_popup('elevations'))
   ttk.Label(window,text='Front elevations: click a wall or floor to edit its module.',
             padding=(12,10),font=('TkDefaultFont',11)).pack(fill='x')
   self.elevations_canvas=tk.Canvas(window,bg='#505357',highlightthickness=0)
   self.elevations_canvas.pack(fill='both',expand=True,padx=10,pady=(0,10))
   self.elevations_canvas.bind('<Configure>',lambda e:self._draw_elevations(self.elevations_canvas),add='+')
   self.elevations_canvas.bind('<Button-1>',lambda e:self._elevation_click(e,self.elevations_canvas))
   self._module_popup_windows['elevations']=window
  window.deiconify();window.attributes('-topmost',True);window.lift();window.focus_set()
  self._draw_elevations(self.elevations_canvas)
  self._sync_global_tool_states()

 def _elevation_sources(self):
  """Collect full FRONT raster facades without changing the user's active wall.

  Render a wall's image only if it has not already been built. For an unedited
  side, inherit its initial art from the front wall, just as switch_wall does.
  """
  if self._elevation_render_busy:return {}
  self._elevation_render_busy=True
  saved_wall=self.active_wall
  saved_selector=self.wall_selector.get()
  self._remember_wall()
  results={}
  old_flag=getattr(self,'_preparing_wall_assemblies',False)
  self._preparing_wall_assemblies=True
  try:
   for wall in self.wall_names:
    cfg=self.wall_configs.get(wall)
    if cfg is None:
     template=self.wall_configs.get('front') or self.wall_configs.get(saved_wall)
     if template is None:continue
     cfg=copy.deepcopy(template)
     cfg['facade']=None;cfg['facade_front']=None
     cfg['spans']=None;cfg['band_heights']=[];cfg['band_widths']=[]
     cfg['width']=self.pair_widths['front' if wall in ('front','back') else 'side']
     self.wall_configs[wall]=cfg
    if cfg.get('facade_front') is not None:
     results[wall]=(cfg['facade_front'],list(cfg.get('band_heights') or []))
    elif cfg.get('applied'):
     self._restore_wall(wall)
     img=self._build_front_facade()
     results[wall]=(img,list(self.front_band_heights))
     cfg['facade_front']=img.copy()
     cfg['band_heights']=list(self.front_band_heights)
    else:
     # Build the genuine FRONT sprite composition before the first Apply.
     # All mutations are temporary and the original editor state is restored.
     self._restore_wall(wall)
     original=self._capture_type_state()
     old_types=self.type_modules
     had_applied=hasattr(self,'applied_module')
     old_applied=getattr(self,'applied_module',None)
     try:
      synthetic={}
      for i in range(4):
       if self.independent_edit.get() and i in self.type_states:
        self._restore_type_state(self.type_states[i])
       self._compose_only(rustication_enabled=self._rust_for_type(i))
       synthetic[i]=self.module.copy()
      self.type_modules=synthetic
      self.applied_module=synthetic.get(2,synthetic[0])
      output=self._build_front_facade()
      results[wall]=(output,list(self.front_band_heights))
     finally:
      self.type_modules=old_types
      if had_applied:self.applied_module=old_applied
      else:delattr(self,'applied_module')
      self._restore_type_state(original)

  finally:
   self._restore_wall(saved_wall)
   self.wall_selector.set(saved_selector)
   self._preparing_wall_assemblies=old_flag
   self._elevation_render_busy=False
  return results

 def _draw_elevations(self,canvas=None):
  """Architectural strip of four actual FRONT facades, in ONE world scale.

  No individual cards and no four independent fit-to-cell transforms.  The
  editable wall width ratio follows the current body geometry (w/d).  All
  floor levels share the same baseline; the selected wall/floor is a light
  translucent highlight applied directly to the true facade pixels.
  """
  c=canvas if canvas is not None else getattr(self,'elevations_canvas',None)
  if c is None or not c.winfo_exists():return
  c.delete('all')
  cw=max(1,c.winfo_width());ch=max(1,c.winfo_height())
  compact=c is getattr(self,'elevations_tray_canvas',None)
  images=self._elevation_sources()
  order=('front','right','back','left')
  available=[(wall,images[wall]) for wall in order if wall in images and images[wall][0].width>0]
  c.configure(bg='#505357')
  if not available:
   c.create_text(cw/2,ch/2,text='No facades to display',fill='#e8eaeb')
   c._elevation_hits=[];c._elevation_refs=[]
   return
  # The body supplies actual geometry; the underlying FRONT imagery comes
  # from the corresponding independently configured wall.
  body=None
  vol=getattr(self,'volume_app',None)
  if vol is not None and getattr(vol,'blocks',None):
   body=vol.blocks[min(max(0,getattr(vol,'active',0)),len(vol.blocks)-1)]
  front_dim=max(1,float(body.w)) if body else max(1,float(self.pair_widths.get('front',48)))
  side_dim=max(1,float(body.d)) if body else max(1,float(self.pair_widths.get('side',32)))
  # Physical 2:1 module coordinate scale is FIXED. Window count must never
  # change the width of the architectural wall or the size of its pixels.
  # In particular, an overfull window band is clipped to the body envelope,
  # not squeezed to fit it (which used to distort all four elevations).
  density=2**0.5
  target_width={wall:max(1,int(round(density*(front_dim if wall in ('front','back') else side_dim)))) for wall in order}
  # Use actual raster heights, and align all facades by the same ground line.
  # House geometry is a shared height across four elevations, so a difference
  # in art height must not create a different vertical scale per wall.
  max_h=max(img.height for _,(img,_) in available)
  total_width=sum(target_width[wall] for wall,_ in available)
  left_pad=9 if compact else 25
  right_pad=left_pad
  top_pad=25 if compact else 47
  bottom_pad=14 if compact else 32
  scale=min((cw-left_pad-right_pad)/max(1,total_width),
            (ch-top_pad-bottom_pad)/max(1,max_h))
  scale=max(0.01,scale)
  screen_w=total_width*scale
  start_x=(cw-screen_w)/2
  baseline=top_pad+max_h*scale+(ch-top_pad-bottom_pad-max_h*scale)/2
  refs=[];hits=[];x=start_x
  for wall,(img,heights) in available:
   tw=target_width[wall]
   draw_w=max(1,int(round(tw*scale)))
   draw_h=max(1,int(round(img.height*scale)))
   y=baseline-draw_h
   # Normalize only to real wall dimensions; all four walls share scale.
   # Real facade art can have transparent staircase-shaped margins because
   # each floor contains a different number of window modules. A physical
   # wall does NOT shrink at these rows: underlay a rectangular wall plane
   # first, with the correct per-floor wall colour, then composite the art.
   cfg=self.wall_configs.get(wall) or {}
   states=cfg.get('types') or {}
   if img.mode!='RGBA':img=img.convert('RGBA')
   wall_plane=Image.new('RGBA',img.size,(0,0,0,0))
   from PIL import ImageDraw
   painter=ImageDraw.Draw(wall_plane)
   if heights and sum(heights)>0:
    yy=0
    n=len(heights)
    for floor in range(n-1,-1,-1):
     band_height=max(0,int(heights[floor]))
     kind=0 if floor==0 else 1 if floor==1 else 3 if floor==n-1 else 2
     state=states.get(kind) or states.get(2) or {}
     color=state.get('wall_color',self.wall_color)
     painter.rectangle((0,yy,img.width-1,min(img.height-1,yy+band_height-1)),fill=color)
     yy+=band_height
    if yy<img.height:painter.rectangle((0,yy,img.width-1,img.height-1),fill=self.wall_color)
   else:
    color=(states.get(2) or states.get(0) or {}).get('wall_color',self.wall_color)
    painter.rectangle((0,0,img.width-1,img.height-1),fill=color)
   wall_plane.alpha_composite(img)
   if img.width!=tw:
    # Keep window/sprite pixel sizes unchanged. Centre-crop overflow or
    # centre-pad a narrower source rather than stretching facade details.
    if img.width>tw:
     x0=(img.width-tw)//2
     normalized=wall_plane.crop((x0,0,x0+tw,img.height))
    else:
     color=(states.get(2) or states.get(0) or {}).get('wall_color',self.wall_color)
     normalized=Image.new('RGBA',(tw,img.height),color)
     normalized.alpha_composite(wall_plane,((tw-img.width)//2,0))
   else:normalized=wall_plane
   shown=normalized.resize((draw_w,draw_h),Image.Resampling.NEAREST)
   current=wall==self.active_wall
   if current:
    overlay=Image.new('RGBA',shown.size,(55,180,113,0))
    overlay.putalpha(shown.getchannel('A').point(lambda alpha:round(alpha*.21)))
    shown=Image.alpha_composite(shown,overlay)
   photo=ImageTk.PhotoImage(shown,master=c)
   refs.append(photo)
   c.create_image(round(x),round(y),image=photo,anchor='nw')
   # Hairline joints make the flat strip legible without separating cards.
   if wall!=available[0][0]:
    c.create_line(round(x),y,round(x),baseline,fill='#32383b',width=1)
   label={'front':'Front','right':'Right','back':'Back','left':'Left'}[wall]
   text_color='#8ce4c3' if current else '#e5e8e9'
   c.create_text(x+draw_w/2,max(8,y-(16 if compact else 24)),text=label,
                 fill=text_color,font=('Helvetica',8 if compact else 11,'bold'))
   if current:
    c.create_rectangle(round(x),round(y),round(x+draw_w),round(baseline),outline='#52d4a7',width=2)
   hits.append((x,y,x+draw_w,baseline,wall,None))
   # A band hit sits above the whole-wall hit so clicking a floor selects it.
   if heights and sum(heights)>0:
    total=sum(heights);used=0
    for floor in range(len(heights)-1,-1,-1):
     band=heights[floor]
     yy0=y+draw_h*used/total;yy1=y+draw_h*(used+band)/total
     kind=0 if floor==0 else 1 if floor==1 else 3 if floor==len(heights)-1 else 2
     hits.append((x,yy0,x+draw_w,yy1,wall,kind))
     if current and kind==self.active_type:
      c.create_rectangle(round(x),round(yy0),round(x+draw_w),round(yy1),outline='#65e8bd',width=2)
     used+=band
   x+=draw_w
  c.create_line(round(start_x),round(baseline)+1,round(x),round(baseline)+1,fill='#b4b9b7',width=1)
  c._elevation_hits=hits
  c._elevation_refs=refs
  c._elevation_layout={'scale':scale,'widths':target_width,'baseline':baseline,'total':total_width}

 def _elevation_click(self,event,canvas=None):
  c=canvas if canvas is not None else getattr(self,'elevations_canvas',None)
  if c is None:return
  hits=getattr(c,'_elevation_hits',[])
  for x0,y0,x1,y1,wall,kind in reversed(hits):
   if x0<=event.x<=x1 and y0<=event.y<=y1:
    self.wall_selector.set(self.wall_names[wall]);self.switch_wall()
    if kind is not None:self._module_change_type(kind)
    self._refresh_elevation_views()
    return

 def _refresh_elevation_views(self):
  for c in (getattr(self,'elevations_canvas',None),getattr(self,'elevations_tray_canvas',None)):
   if c is not None and c.winfo_exists() and c.winfo_ismapped():
    self._draw_elevations(c)

 def build_facade_tab(self):
  # Scrollable assembly controls as well, so export/save buttons stay accessible.
  panel=ttk.Frame(self.tab_facade,width=320); panel.pack(side='left',fill='y'); panel.pack_propagate(False)
  left_canvas=tk.Canvas(panel,highlightthickness=0,width=310)
  left_scroll=ttk.Scrollbar(panel,orient='vertical',command=left_canvas.yview)
  left_canvas.configure(yscrollcommand=left_scroll.set)
  left_scroll.pack(side='right',fill='y')
  left_canvas.pack(side='left',fill='both',expand=True)
  left=ttk.Frame(left_canvas,padding=8)
  left_window=left_canvas.create_window((0,0),window=left,anchor='nw')
  def _facade_panel_configure(_event=None):
   left_canvas.configure(scrollregion=left_canvas.bbox('all'))
  def _facade_canvas_configure(event):
   left_canvas.itemconfigure(left_window,width=event.width)
  left.bind('<Configure>',_facade_panel_configure)
  left_canvas.bind('<Configure>',_facade_canvas_configure)
  def _facade_wheel(event):
   if getattr(event,'delta',0): left_canvas.yview_scroll(int(-event.delta/120) or (-1 if event.delta>0 else 1),'units')
   elif getattr(event,'num',None)==4: left_canvas.yview_scroll(-1,'units')
   elif getattr(event,'num',None)==5: left_canvas.yview_scroll(1,'units')
  left_canvas.bind_all('<MouseWheel>',_facade_wheel,add='+')
  left_canvas.bind_all('<Button-4>',_facade_wheel,add='+')
  left_canvas.bind_all('<Button-5>',_facade_wheel,add='+')
  right=ttk.Frame(self.tab_facade,padding=8); right.pack(side='right',fill='both',expand=True)
  ttk.Label(left,text='ASSEMBLY WALL',font=('TkDefaultFont',10,'bold')).pack(anchor='w')
  self.assembly_wall_box=ttk.Combobox(left,state='readonly',textvariable=self.wall_selector,
      values=list(self.wall_names.values()),width=24)
  self.assembly_wall_box.pack(fill='x',pady=(3,4))
  self.assembly_wall_box.bind('<<ComboboxSelected>>',self.switch_wall)
  ttk.Label(left,text='Front/back walls share their width; left/right walls share their depth. Window counts and decoration are independent.',wraplength=275).pack(anchor='w',pady=(2,7))
  ttk.Label(left,text='ISOMETRIC FLOOR STRIPS' ,font=('TkDefaultFont',11,'bold'),wraplength=275).pack(anchor='w')
  ttk.Label(left,text='Modules are applied automatically. Each floor uses a continuous isometric strip; window modules replace segments on both sides.',wraplength=275).pack(anchor='w',pady=(5,8))
  ttk.Label(left,text='Length of one side of the strip (px)').pack(anchor='w')
  self.facade_width_spin=ttk.Spinbox(left,from_=12,to=1000,increment=2,textvariable=self.facade_width,width=8,command=self.render_facade)
  self.facade_width_spin.pack(anchor='w',pady=(2,7))
  self.facade_width_spin.bind('<KeyRelease>',lambda e:self.root.after_idle(self.render_facade))
  ttk.Label(left,text='Number of floors').pack(anchor='w')
  ttk.Spinbox(left,from_=1,to=40,textvariable=self.floors,width=8,command=self.render_facade).pack(anchor='w',pady=(2,7))
  ttk.Label(left,text='Number of windows on EACH side of the floor').pack(anchor='w',pady=(2,3))
  for i,name in enumerate(self.type_names):
   row=ttk.Frame(left); row.pack(fill='x',pady=1)
   ttk.Label(row,text=name,width=19).pack(side='left')
   ttk.Spinbox(row,from_=0,to=40,textvariable=self.floor_counts[i],width=6,command=self.render_facade).pack(side='right')
  ttk.Separator(left).pack(fill='x',pady=5)
  ttk.Label(left,text='WINDOW SPACING',font=('TkDefaultFont',10,'bold'),wraplength=275).pack(anchor='w',pady=(2,5))
  ttk.Label(left,text='Windows on each floor are centred as a group. Only the spacing between neighbouring windows changes.',wraplength=275).pack(anchor='w',pady=(0,5))
  self.floor_gap_vars=[]
  for i,name in enumerate(self.type_names):
   box=ttk.LabelFrame(left,text=name,padding=5); box.pack(fill='x',pady=3)
   gap=tk.IntVar(value=0)
   row=ttk.Frame(box); row.pack(fill='x')
   ttk.Label(row,text='Window spacing (px)').pack(side='left')
   sp=ttk.Spinbox(row,from_=0,to=120,increment=2,textvariable=gap,width=6,command=self.render_facade)
   sp.pack(side='right')
   sp.bind('<KeyRelease>',lambda e:self.root.after_idle(self.render_facade))
   self.floor_gap_vars.append(gap)
  ttk.Label(left,text='Each floor is a continuous V-shaped isometric strip made of repeated wall segments. Windows replace selected segments on both sides. Length is specified per side.',wraplength=275).pack(anchor='w',pady=(3,7))
  ttk.Separator(left).pack(fill='x',pady=5)
  ttk.Separator(left).pack(fill='x',pady=7)
  ttk.Label(left,text='FOUNDATION',font=('TkDefaultFont',10,'bold')).pack(anchor='w',pady=(2,5))
  ttk.Checkbutton(left,text='Add foundation',variable=self.first_foundation,command=self.render_facade).pack(anchor='w',pady=2)
  rr=ttk.Frame(left); rr.pack(fill='x',pady=2)
  ttk.Button(rr,text='Different foundation',command=self.reroll_foundation).pack(side='left',fill='x',expand=True)
  ttk.Checkbutton(left,text='Same colour as wall',variable=self.foundation_color_enabled,command=self.render_facade).pack(anchor='w',pady=2)
  ttk.Button(left,text='Foundation colour…',command=self.choose_foundation_color).pack(fill='x',pady=2)
  ttk.Label(left,text='Foundation offset (px)').pack(anchor='w',pady=(5,1))
  fr=ttk.Frame(left); fr.pack(fill='x')
  ttk.Label(fr,text='X').pack(side='left'); ttk.Spinbox(fr,from_=-100,to=100,textvariable=self.foundation_x,width=6,command=self.render_facade).pack(side='left',padx=(3,10))
  ttk.Label(fr,text='Y').pack(side='left'); ttk.Spinbox(fr,from_=-100,to=100,textvariable=self.foundation_y,width=6,command=self.render_facade).pack(side='left',padx=3)
  ttk.Label(left,text='You can offset the foundation under or away from the wall.',wraplength=270).pack(anchor='w',pady=(2,5))
  ttk.Button(left,text='Refresh preview',command=self.render_facade).pack(fill='x',pady=(6,3))
  self.facade_status=tk.StringVar(value='Module has not been applied yet.')
  ttk.Label(right,text='Final Assembly Preview',font=('TkDefaultFont',11,'bold')).pack(anchor='w')
  ttk.Label(right,text='Original 2:1 isometric facade. The FRONT view is generated automatically for rotation.',wraplength=480).pack(anchor='w')
  self.facade_canvas=tk.Canvas(right,bg='#505357',highlightthickness=0); self.facade_canvas.pack(fill='both',expand=True,pady=(8,4))
  self.facade_canvas.bind('<Configure>',lambda e:self.show_facade())
  ttk.Label(right,textvariable=self.facade_status).pack(anchor='w')
 def _remember_wall(self):
  """Snapshot both the live module editor and the assembled façade."""
  self.type_states[self.active_type]=self._capture_type_state()
  self.wall_configs[self.active_wall]={
   'types':copy.deepcopy(self.type_states),
   'type_modules':{i:im.copy() for i,im in self.type_modules.items()},
   'active_type':self.active_type,'independent':bool(self.independent_edit.get()),
   'applied':bool(getattr(self,'module_applied',False)),
   'applied_module':self.applied_module.copy() if getattr(self,'module_applied',False) else None,
   'width':max(12,int(self.facade_width.get())),
   'counts':[int(v.get()) for v in self.floor_counts],
   'gaps':[int(v.get()) for v in getattr(self,'floor_gap_vars',[])],
   'facade':self.facade.copy() if self.facade is not None else None,
   'facade_front':self.facade_front.copy() if self.facade_front is not None else None,
   'spans':copy.deepcopy(getattr(self,'front_module_spans',None)),
   'band_heights':list(getattr(self,'front_band_heights',[]) or []),
   'band_widths':list(getattr(self,'front_band_widths',[]) or []),
   'wall_height':getattr(self,'facade_wall_height_px',0),
   'rust_first':bool(self.rust_first.get()),'rust_second':bool(self.rust_second.get()),'rust_middle':bool(self.rust_middle.get()),'rust_upper':bool(self.rust_upper.get()),
   'rust_count':int(self.rust_count.get()),
   'foundation':bool(self.first_foundation.get()),
   'foundation_choice':self.foundation_choice,
   'foundation_color':self.foundation_color,
   'foundation_color_enabled':bool(self.foundation_color_enabled.get()),
   'foundation_x':int(self.foundation_x.get()),'foundation_y':int(self.foundation_y.get()),
  }
  group='front' if self.active_wall in ('front','back') else 'side'
  self.pair_widths[group]=max(12,int(self.facade_width.get()))

 def _restore_wall(self,wall):
  cfg=self.wall_configs[wall]
  self.active_wall=wall
  group='front' if wall in ('front','back') else 'side'
  if self.facade_width.get()!=self.pair_widths[group]:self.facade_width.set(self.pair_widths[group])
  self.type_states=copy.deepcopy(cfg['types'])
  self.type_modules={i:im.copy() for i,im in cfg['type_modules'].items()}
  self.active_type=cfg['active_type']
  self.independent_edit.set(bool(cfg['independent']))
  self.module_applied=cfg['applied']
  if cfg['applied_module'] is not None:self.applied_module=cfg['applied_module'].copy()
  self.facade=cfg['facade'].copy() if cfg['facade'] is not None else None
  self.facade_front=cfg['facade_front'].copy() if cfg['facade_front'] is not None else None
  self.front_module_spans=copy.deepcopy(cfg['spans'])
  self.front_band_heights=list(cfg['band_heights'])
  self.front_band_widths=list(cfg['band_widths'])
  self.facade_wall_height_px=cfg['wall_height']
  for i,val in enumerate(cfg['counts']):self.floor_counts[i].set(val)
  for i,val in enumerate(cfg['gaps']):self.floor_gap_vars[i].set(val)
  self.rust_first.set(cfg.get('rust_first',False))
  self.rust_second.set(cfg.get('rust_second',False))
  self.rust_middle.set(cfg.get('rust_middle',False))
  self.rust_upper.set(cfg.get('rust_upper',False))
  self.rust_count.set(cfg.get('rust_count',5))
  self.first_foundation.set(cfg['foundation'])
  self.foundation_choice=cfg['foundation_choice']
  self.foundation_color=cfg['foundation_color']
  self.foundation_color_enabled.set(cfg['foundation_color_enabled'])
  self.foundation_x.set(cfg['foundation_x']);self.foundation_y.set(cfg['foundation_y'])
  self.type_selector.current(self.active_type)
  self._restore_type_state(self.type_states[self.active_type])
  self._compose_only(rustication_enabled=self._rust_for_type(self.active_type))

 def switch_wall(self,event=None):
  # Preserve the requested wall: flushing the previous wall can render a
  # preview, which temporarily restores the selector to its old value.
  selected=self.wall_selector.get()
  if not getattr(self,'_loading_facade_project',False):
   self._flush_live_module()
   self.wall_selector.set(selected)
  wall=next((k for k,name in self.wall_names.items() if name==selected),selected)
  if wall not in self.wall_names or wall==self.active_wall:return
  self._remember_wall()
  if wall not in self.wall_configs:
   # An unedited wall starts from the principal elevation, but immediately
   # becomes an independent set of window styles, placements, and floor counts.
   template=self.wall_configs.get('front',self.wall_configs[self.active_wall])
   cfg=copy.deepcopy(template)
   cfg['facade']=None;cfg['facade_front']=None
   cfg['spans']=None;cfg['band_heights']=[];cfg['band_widths']=[]
   cfg['width']=self.pair_widths['front' if wall in ('front','back') else 'side']
   self.wall_configs[wall]=cfg
  self._restore_wall(wall)
  self.wall_name_label.configure(text=self.wall_names[wall])
  if self.module_applied:self.render_facade()
  else:
   self.facade=None;self.facade_front=None
   self.facade_canvas.delete('all')
  for i in range(4):self.show_type_preview(i)
  self.update_volume_facade()
  self.root.after_idle(self._refresh_elevation_views)

 def _capture_type_state(self):
  return {'wall_color':self.wall_color,'enabled':dict(self.enabled),'choice':dict(self.choice),'offset':{k:list(v) for k,v in self.offset.items()},'front_offset':{k:list(v) for k,v in self.front_offset.items()},'component_colors':dict(self.component_colors),'component_modes':dict(self.component_modes),'component_strength':dict(self.component_strength),'extra_height':int(self.extra_wall_height.get()),'window_size':self.window_size.get(),'window_shape':self.window_shape.get()}
 def _restore_type_state(self,state):
  state=_read_legacy_labels(state)
  self.wall_color=state['wall_color']; self.enabled=dict(state['enabled']); self.choice=dict(state['choice']); self.offset={k:list(v) for k,v in state['offset'].items()}; self.front_offset={k:list(v) for k,v in state.get('front_offset',{c:[0,0] for c in ORDER}).items()}; self.component_colors=dict(state['component_colors']); self.component_modes=dict(state['component_modes']); self.component_strength=dict(state['component_strength']); self.extra_wall_height.set(state['extra_height']); self.window_size.set(state.get('window_size','M')); self.window_shape.set(state.get('window_shape','Arched' if (state.get('choice',{}).get('glass') or {}).get('shape')=='arch' else 'Standard'))
  for c in ORDER: self.check_vars[c].set(self.enabled[c])
  self.swatch.configure(bg=self.wall_color,text=self.wall_color)
  self.wall_palette.set(next((n for n,col in ARCH_PALETTE if col.lower()==self.wall_color.lower()),'Custom colour'))
  self.sync_offset()
 def select_type(self,event=None):
  if self.type_states: self.type_states[self.active_type]=self._capture_type_state()
  new=self.type_selector.current()
  if new<0: return
  self.active_type=new
  if self.independent_edit.get() and new in self.type_states: self._restore_type_state(self.type_states[new])
  else:
   # Shared mode uses the current module definition for all types.
   if self.type_states: self._restore_type_state(self.type_states.get(0,self._capture_type_state()))
  self.compose_module()
 def toggle_independent(self):
  self.type_states[self.active_type]=self._capture_type_state()
  if self.independent_edit.get():
   for i in range(4): self.type_states.setdefault(i,self._capture_type_state())
  else:
   shared=self._capture_type_state()
   for i in range(4): self.type_states[i]=copy.deepcopy(shared)
  self.compose_module()
 def preview_click(self,index,event):
  if index!=self.active_type:
   self.type_states[self.active_type]=self._capture_type_state()
   self.active_type=index; self.type_selector.current(index)
   for w in self._module_selected_type_widgets:
    try:w.current(index)
    except Exception:pass
   if self.independent_edit.get(): self._restore_type_state(self.type_states[index])
   else:
    state=self._capture_type_state()
    for i in range(4): self.type_states[i]=state
   self.compose_module(); return
  cv=self.type_canvases[index]
  if self.module is None:return
  if self.module_view.get()=='FRONT':
   current_image,self.front_layers=self._front_module(index,with_layers=True)
   current_layers=self.front_layers
  else:
   current_image=self.module
   current_layers=self.layers
  scale=min((max(1,cv.winfo_width()-20))/current_image.width,(max(1,cv.winfo_height()-38))/current_image.height,18); scale=max(.25,scale)
  shown_w=max(1,int(current_image.width*scale)); shown_h=max(1,int(current_image.height*scale)); ox=(cv.winfo_width()-shown_w)//2; oy=(cv.winfo_height()-shown_h)//2+8
  self.module_scale=scale; self.module_origin=(ox,oy); self.scale=scale; self.preview_origin=(ox,oy)
  x=int((event.x-ox)/scale); y=int((event.y-oy)/scale)
  for c in reversed(ORDER):
   layer=current_layers.get(c)
   if layer and 0<=x<layer.width and 0<=y<layer.height and layer.getpixel((x,y))[3]>0:
    offsets=self.front_offset if self.module_view.get()=='FRONT' else self.offset
    self.drag=(c,event.x,event.y,offsets[c][0],offsets[c][1]); self.selected.set(LABELS[c]); self.sync_offset(); return
 def open_palette(self, target='wall'):
  # The palette image is shipped inside the embedded library folder.
  palette_path=LIBRARY/'palette.png'
  if not palette_path.exists(): palette_path=ROOT/'palette.png'
  if not palette_path.exists():
   matches=list(ROOT.rglob('palette.png'))
   if matches:palette_path=matches[0]
  if not palette_path.exists():
   chosen=filedialog.askopenfilename(title='Choose palette image',filetypes=[('PNG palette','*.png'),('Images','*.png *.jpg *.jpeg')])
   if not chosen:return
   palette_path=Path(chosen)
  component=self.selected_cat() if target=='component' else None
  initial=(self.component_colors.get(component) if component else None) or self.wall_color
  try: im=Image.open(palette_path).convert('RGB')
  except Exception as e:
   messagebox.showerror('Palette Error',f'Could not open palette image:\n{e}')
   return
  win=tk.Toplevel(self.root); win.title('Architectural Palette' if target=='wall' else 'Decor colour from architectural palette'); win.transient(self.root); win.grab_set()
  maxw,maxh=900,650; scale=min(maxw/im.width,maxh/im.height,1)
  shown=im.resize((max(1,int(im.width*scale)),max(1,int(im.height*scale))),Image.Resampling.NEAREST)
  body=ttk.Frame(win,padding=8); body.pack(fill='both',expand=True)
  side=ttk.Frame(body); side.pack(side='right',fill='y',padx=(10,0))
  canvas=tk.Canvas(body,width=shown.width,height=shown.height,highlightthickness=0,cursor='crosshair')
  canvas.pack(side='left',fill='both',expand=False)
  photo=ImageTk.PhotoImage(shown); canvas.create_image(0,0,image=photo,anchor='nw'); canvas.image=photo
  ttk.Label(side,text='Selected shade',font=('TkDefaultFont',10,'bold')).pack(anchor='w')
  preview=tk.Label(side,bg=initial,relief='sunken',width=18,height=5); preview.pack(pady=6)
  hexvar=tk.StringVar(value=initial); ttk.Label(side,textvariable=hexvar,font=('TkFixedFont',11)).pack(pady=(0,10))
  target_text='wall' if target=='wall' else f'decoration “{LABELS.get(component, "not selected")}”'
  ttk.Label(side,text=f'Click a shade for {target_text}.\nThen click Apply.',justify='left',wraplength=180).pack(anchor='w',pady=(0,12))
  result={'color':initial}; cross=canvas.create_line(0,0,0,0,fill='white',width=1); cross2=canvas.create_line(0,0,0,0,fill='black',width=1)
  def update_at(e):
   x=max(0,min(im.width-1,int(e.x/scale))); y=max(0,min(im.height-1,int(e.y/scale)))
   col=im.getpixel((x,y)); hx='#%02X%02X%02X'%col; result['color']=hx
   px=x*scale; py=y*scale
   canvas.coords(cross,px-8,py,px+8,py); canvas.coords(cross2,px,py-8,px,py+8)
   preview.configure(bg=hx); hexvar.set(hx)
  canvas.bind('<Button-1>',update_at)
  buttons=ttk.Frame(side); buttons.pack(side='bottom',fill='x',pady=(12,0))
  def apply():
   if target=='component':
    c=self.selected_cat()
    if not c:
     messagebox.showinfo('No detail selected','First select a decorative detail in the Selected Detail list.',parent=win); return
    self.component_colors[c]=result['color']
    if hasattr(self,'component_swatch'): self.component_swatch.configure(bg=result['color'],text=result['color'])
   else:
    self.wall_color=result['color']; self.swatch.configure(bg=self.wall_color,text=self.wall_color); self.wall_palette.set('Custom colour')
   self.compose_module(); win.destroy()
  ttk.Button(buttons,text='Apply',command=apply).pack(fill='x',pady=2)
  ttk.Button(buttons,text='Cancel',command=win.destroy).pack(fill='x',pady=2)
  win.update_idletasks(); win.geometry(f'{min(win.winfo_reqwidth(),1150)}x{min(win.winfo_reqheight(),800)}')
 def change_module_view(self):
  # The same module is previewed in two projections; neither view changes the other.
  self.drag=None
  self.sync_offset()
  self.compose_module()

 def show_type_preview(self,index):
  if not hasattr(self,'type_canvases') or self.module is None:return
  current=self._capture_type_state()
  try:
   if self.independent_edit.get() and index!=self.active_type and index in self.type_states:
    self._restore_type_state(self.type_states[index])
   if self.module_view.get()=='FRONT':
    im,_=self._front_module(index,with_layers=True)
   else:
    self._compose_only(rustication_enabled=self._rust_for_type(index))
    im=self.module.copy()
  finally:
   self._restore_type_state(current)
   self._compose_only(rustication_enabled=self._rust_for_type(self.active_type))
  cv=self.type_canvases[index]
  cw,ch=max(1,cv.winfo_width()),max(1,cv.winfo_height())
  scale=min((cw-20)/im.width,(ch-24)/im.height,60);scale=max(.25,scale)
  shown=im.resize((max(1,int(im.width*scale)),max(1,int(im.height*scale))),Image.Resampling.NEAREST)
  photo=ImageTk.PhotoImage(shown);self.type_photos[index]=photo
  cv.delete('all');cv.create_image(cw//2,ch//2+8,image=photo,anchor='center')
  cv.master.configure(relief='solid',borderwidth=4 if index==self.active_type else 1)

 def _rust_for_type(self,index):
  return bool(self.rust_first.get()) if index==0 else bool(self.rust_second.get()) if index==1 else bool(self.rust_middle.get()) if index==2 else bool(self.rust_upper.get())
 def _compose_only(self, rustication_enabled=None):
  w,h=self.module_size(); self.layers={}
  wall=self.extended_wall().copy()
  if rustication_enabled is None: rustication_enabled=self._rust_for_type(self.active_type)
  # Rustication belongs to the wall layer: window/decor sprites are added above it and can never erase it.
  wall=self.apply_rustication(wall,rustication_enabled)
  self.module=wall
  for c in ORDER:
   if not self.enabled[c] or not self.choice[c]: continue
   item=self.choice[c]
   sprite=item['image']  # Light ISO artwork; wall shading is procedural.
   tint=self.component_colors.get(c)
   if tint: sprite=tint_sprite(sprite,tint,self.component_modes[c],self.component_strength[c])
   layer=Image.new('RGBA',(w,h),(0,0,0,0)); bx,by=self.default_position(c,sprite); ox,oy=self.offset[c]
   if c=='cornice' and sprite.height<=5:
    # Cornice is also a repeating 2px isometric segment, not one full-width sprite.
    piece=sprite.crop((0,0,min(2,sprite.width),sprite.height))
    x=bx+ox; y=by+oy
    while x<w:
     place_clipped(layer,piece,x,y); x+=2; y+=1
   else:
    place_clipped(layer,sprite,bx+ox,by+oy)
   self.layers[c]=layer; self.module.alpha_composite(layer)
 def load_assets(self):
  errors=[]
  for fn,(cat,cell) in SHEETS.items():
   path=LIBRARY/fn
   if not path.exists(): errors.append(fn);continue
   try:
    if cat=='wall':
     self.assets[cat]=[{'name':path.stem,'image':Image.open(path).convert('RGBA')}]
    else:
     self.assets[cat]=paired_sheet(path,cell)
   except Exception as e: errors.append(f'{fn}: {e}')
  self.window_sheets={'frame':{},'casing':{},'sandrik':{},'sill':{}}
  self.window_glass=[]
  root=LIBRARY/'windows'
  for shape,filename in (('normal','glass_16x18.png'),('arch','glass_arch_16x18.png')):
   path=root/filename
   try:
    if not path.exists():raise FileNotFoundError(filename)
    glass_pairs=paired_sheet(path,(16,18))
    if len(glass_pairs)!=len(WINDOW_SIZES):
     raise ValueError(f'expected {len(WINDOW_SIZES)} ISO/FRONT pairs, found {len(glass_pairs)}')
    for size,pair in zip(reversed(WINDOW_SIZES),glass_pairs):
     pair['size']=size; pair['shape']=shape
     pair['name']=f'glass {size}' if shape=='normal' else f'glass_arch {size}'
     self.window_glass.append(pair)
   except Exception as e:errors.append(f'{filename}: {e}')
  # All five casing sizes reside in one sheet (XXS -> L), in two
  # independent styles. Never mix a regular casing with arched glass.
  for shape,filename in (('normal','casing_16x18.png'),('arch','casing_arch_16x18.png')):
   path=root/'casing'/filename
   try:
    if not path.exists():raise FileNotFoundError(filename)
    pairs=paired_sheet(path,(16,18))
    if len(pairs)!=len(WINDOW_SIZES):
     raise ValueError(f'expected {len(WINDOW_SIZES)} ISO/FRONT pairs, found {len(pairs)}')
    for size,pair in zip(reversed(WINDOW_SIZES),pairs):
     pair['size']=size;pair['shape']=shape
     self.window_sheets['casing'].setdefault(size,[]).append(pair)
   except Exception as e:errors.append(f'{filename}: {e}')
  for cat,folder in WINDOW_ASSETS.items():
   if cat=='casing':continue
   for path in sorted((root/folder).glob('*.png')) if (root/folder).exists() else []:
    m=re.search(r'(XXS|XS|L|M|S)_([0-9]+)x([0-9]+)',path.stem,re.I)
    if not m:errors.append(f'{path.name}: unknown filename');continue
    size=m.group(1).upper();cell=(int(m.group(2)),int(m.group(3)))
    try:self.window_sheets[cat][size]=paired_sheet(path,cell,size)
    except Exception as e:errors.append(f'{path.name}: {e}')
  self.assets['glass']=list(self.window_glass)
  for cat in WINDOW_ASSETS:
   self.assets[cat]=[a for group in self.window_sheets[cat].values() for a in group]
  self.wall_source=self.assets['wall'][0]['image'] if self.assets['wall'] else None
  if self.assets['foundation']:self.foundation_choice=random.choice(self.assets['foundation'])
  counts=[f'{LABELS[c]}: {len(self.assets[c])} ISO/FRONT pairs' for c in ORDER]
  counts += [f"Glass: {len(self.window_glass)} sizes",f"Rustication: {len(self.assets['rustication'])} pairs",f"Foundation: {len(self.assets['foundation'])} pairs"]
  self.asset_info.set('\n'.join(counts)+(('\nMissing: '+', '.join(errors)) if errors else ''))
  if errors:messagebox.showwarning('Asset Library','Loading issues:'+'\n'.join(errors))
 def _size_assets(self,cat):
  size=self.window_size.get().upper()
  if cat=='glass': return [a for a in self.assets['glass'] if a.get('size')==size and a.get('shape','normal')==self._shape_key()]
  if cat in self.window_sheets:
   variants=self.window_sheets[cat].get(size)
   if cat=='casing':variants=[a for a in (variants or []) if a.get('shape','normal')==self._shape_key()]
   if not variants and size in ('XS','XXS') and cat in ('sandrik','sill'):
    variants=self.window_sheets[cat].get('S')
   return variants or []
  return self.assets.get(cat,[])
 def _shape_key(self):
  return 'arch' if self.window_shape.get()=='Arched' else 'normal'
 def change_window_shape(self,event=None):
  for cat in ('glass','casing'):
   if self.enabled.get(cat):
    options=self._size_assets(cat)
    self.choice[cat]=options[0] if options else None
  self.compose_module()
 def change_window_size(self,event=None):
  size=self.window_size.get().upper()
  if self.enabled.get('glass'):
   opts=self._size_assets('glass'); self.choice['glass']=opts[0] if opts else None
  for cat in ('frame','casing','sill','sandrik'):
   if self.enabled.get(cat):
    opts=self._size_assets(cat); self.choice[cat]=random.choice(opts) if opts else None
  self.compose_module()
 def pick_wall_preset(self,event=None):
  name=self.wall_palette.get()
  for n,col in ARCH_PALETTE:
   if n==name:
    self.wall_color=col; self.swatch.configure(bg=col,text=col); self.compose_module(); return
 def choose_component_color(self):
  self.open_palette('component')
 def change_component_mode(self,event=None):
  c=self.selected_cat()
  if c:
   self.component_modes[c]='hue' if self.mode_var.get()=='Hue shift' else 'shade'; self.compose_module()
 def reset_component_color(self):
  c=self.selected_cat()
  if c:
   self.component_colors[c]=None; self.component_modes[c]='shade'; self.mode_var.set('Preserve shading'); self.component_swatch.configure(bg='#d8d0c2',text='Original'); self.compose_module()
 def selected_cat(self):
  for c in ORDER:
   if LABELS[c]==self.selected.get(): return c
  return None
 def choose_color(self):
  self.open_palette()
 def toggle(self,c):
  self.enabled[c]=self.check_vars[c].get()
  if c=='glass' and self.enabled[c]:
   opts=self._size_assets('glass'); self.choice[c]=opts[0] if opts else None
   if self.choice[c]: self.window_size.set(self.choice[c].get('size','M'))
  else:
   opts=self._size_assets(c); self.choice[c]=random.choice(opts) if self.enabled[c] and opts else None
  self.offset[c]=[0,0];self.front_offset[c]=[0,0];self.compose_module()
 def reroll(self,c):
  if not self.enabled[c]: self.check_vars[c].set(True); self.enabled[c]=True
  arr=self._size_assets(c)
  if arr:
   choices=[a for a in arr if a is not self.choice[c]]; self.choice[c]=random.choice(choices or arr)
   if c=='glass' and self.choice[c]:
    self.window_size.set(self.choice[c].get('size','M'));self.window_shape.set('Arched' if self.choice[c].get('shape')=='arch' else 'Standard')
  self.compose_module()
 def module_size(self):
  w,h=self.wall_source.size if self.wall_source else (12,25)
  return (w,max(5,h+int(self.extra_wall_height.get())))
 def extended_wall(self):
  if not self.wall_source: return Image.new('RGBA',self.module_size(),self.wall_color)
  source=recolor_wall(self.wall_source,self.wall_color)
  extra=self.module_size()[1]-source.height
  if extra==0: return source
  # Keep pixel-art edges crisp: insert/remove rows in the middle of the wall, never resample.
  if extra>0:
   top=max(1,source.height//3); bottom=max(top+1,source.height*2//3)
   band=source.crop((0,top,source.width,bottom))
   rows=[]
   for y in range(extra): rows.append(band.crop((0,(y%band.height),band.width,(y%band.height)+1)))
   out=Image.new('RGBA',(source.width,source.height+extra),(0,0,0,0))
   out.alpha_composite(source.crop((0,0,source.width,top)),(0,0))
   for i,row in enumerate(rows): out.alpha_composite(row,(0,top+i))
   out.alpha_composite(source.crop((0,top,source.width,source.height)),(0,top+extra))
   return out
  cut=-extra; top=max(1,source.height//3); bottom=min(source.height-1,top+cut)
  out=Image.new('RGBA',(source.width,source.height-cut),(0,0,0,0))
  out.alpha_composite(source.crop((0,0,source.width,top)),(0,0))
  out.alpha_composite(source.crop((0,bottom,source.width,source.height)),(0,top))
  return out
 def default_position(self,c,sprite):
  # Initial positions follow the 12x25 wall module; user can refine them pixel-by-pixel.
  w,h=self.module_size(); cx=max(0,(w-sprite.width)//2)
  return {'glass':(max(0,(w-sprite.width)//2),max(1,(h-sprite.height)//3)),'frame':(max(0,(w-sprite.width)//2),max(0,(h-sprite.height)//3-1)),'casing':(max(0,(w-sprite.width)//2),max(0,(h-sprite.height)//3-2)),'sill':(max(0,(w-sprite.width)//2),min(h-sprite.height,h//2+5)),'bracket':(2,19),'sandrik':(max(0,(w-sprite.width)//2),max(0,(h-sprite.height)//3-2)),'cornice':(0,0)}[c]
 def compose_module(self):
  self._compose_only()
  if hasattr(self,'type_states'):
   state=self._capture_type_state()
   if self.independent_edit.get(): self.type_states[self.active_type]=state
   else:
    for i in range(4): self.type_states[i]=state
  if hasattr(self,'type_canvases'):
   for i in range(4): self.show_type_preview(i)
  self.show_module()
  w,h=self.module.size
  self.module_status.set(f'Active type: {self.type_names[self.active_type]} · {self.module_view.get()} · {w} × {h} px. ISO/FRONT offsets are independent.')
  self._schedule_live_module()
 def _schedule_live_module(self):
  # A drag can call compose_module dozens of times each second. Coalesce
  # updates while leaving the module previews interactive.
  if getattr(self,'_loading_facade_project',False) or getattr(self,'_preparing_wall_assemblies',False): return
  if not hasattr(self,'volume_app'):return
  pending=getattr(self,'_live_apply_id',None)
  if pending is not None:
   try:self.root.after_cancel(pending)
   except (ValueError,tk.TclError):pass
  self._live_apply_id=self.root.after(125,self._flush_live_module)
 def _flush_live_module(self):
  pending=getattr(self,'_live_apply_id',None)
  # Nothing changed: avoid rebuilding every wall and its FRONT master when
  # switching walls or opening the Save dialog.
  if pending is None and getattr(self,'module_applied',False):return
  if pending is not None:
   try:self.root.after_cancel(pending)
   except (ValueError,tk.TclError):pass
  self._live_apply_id=None
  if getattr(self,'_loading_facade_project',False) or getattr(self,'_preparing_wall_assemblies',False):return
  if self.module is None:return
  self.apply_module()
 def sync_offset(self,event=None):
  for c in ORDER:
   if LABELS[c]==self.selected.get():
    self.selected_label.configure(text='Selected detail: '+LABELS[c])
    if hasattr(self,'component_selection_text'):self.component_selection_text.set('Selected detail: '+LABELS[c])
    offsets=self.front_offset if self.module_view.get()=='FRONT' else self.offset
    self.xvar.set(offsets[c][0]); self.yvar.set(offsets[c][1])
    col=self.component_colors[c]; self.component_swatch.configure(bg=col or '#d8d0c2',text=col or 'Original')
    self.mode_var.set('Hue shift' if self.component_modes[c]=='hue' else 'Preserve shading')
    return
 def apply_offset(self):
  for c in ORDER:
   if LABELS[c]==self.selected.get() and self.enabled[c]:
    offsets=self.front_offset if self.module_view.get()=='FRONT' else self.offset
    offsets[c]=[int(self.xvar.get()),int(self.yvar.get())];self.compose_module();return
 def draw_image(self,canvas,im):
  cw,ch=max(1,canvas.winfo_width()),max(1,canvas.winfo_height())
  scale=min((cw-30)/im.width,(ch-30)/im.height,18); scale=max(.25,scale)
  shown=im.resize((max(1,int(im.width*scale)),max(1,int(im.height*scale))),Image.Resampling.NEAREST)
  photo=ImageTk.PhotoImage(shown); canvas.delete('all'); canvas.create_image(cw//2,ch//2,image=photo,anchor='center');
  return photo,scale,(cw//2-shown.width//2,ch//2-shown.height//2)
 def show_module(self):
  if self.module is None:return
  if hasattr(self,'type_canvases'):
   for i in range(4): self.show_type_preview(i)
  else:
   self.module_photo,self.module_scale,self.module_origin=self.draw_image(self.module_canvas,self.module)
   self.scale=self.module_scale; self.preview_origin=self.module_origin
 def start_drag(self,e):
  if self.module is None:return
  x=int((e.x-self.module_origin[0])/self.module_scale); y=int((e.y-self.module_origin[1])/self.module_scale)
  for c in reversed(ORDER):
   layer=self.layers.get(c)
   if layer and 0<=x<layer.width and 0<=y<layer.height and layer.getpixel((x,y))[3]>0:
    self.drag=(c,e.x,e.y,self.offset[c][0],self.offset[c][1]); self.selected.set(LABELS[c]); self.sync_offset(); return
 def move_drag(self,e):
  if not self.drag:return
  c,sx,sy,ox,oy=self.drag
  offsets=self.front_offset if self.module_view.get()=='FRONT' else self.offset
  offsets[c]=[ox+round((e.x-sx)/self.module_scale),oy+round((e.y-sy)/self.module_scale)]
  self.xvar.set(offsets[c][0]);self.yvar.set(offsets[c][1]);self.compose_module()
 def apply_module(self):
  # Freeze a current composed module snapshot for assembly; editing the first tab won't silently alter it.
  self.type_states[self.active_type]=self._capture_type_state()
  if not self.independent_edit.get():
   for i in range(4): self.type_states[i]=self._capture_type_state()
  self.type_modules={}
  current=self._capture_type_state()
  original_active=self.active_type
  for i in range(4):
   self.active_type=i
   if self.independent_edit.get(): self._restore_type_state(self.type_states[i])
   else: self._restore_type_state(current)
   self._compose_only(rustication_enabled=self._rust_for_type(i)); self.type_modules[i]=self.module.copy()
  self.active_type=original_active
  self._restore_type_state(current); self._compose_only(rustication_enabled=self._rust_for_type(self.active_type)); self.applied_module=self.type_modules.get(2,self.module.copy()); self.module_applied=True
  self.render_facade()
 def reroll_foundation(self):
  arr=self.assets.get('foundation',[])
  if arr:
   choices=[a for a in arr if a is not self.foundation_choice]
   self.foundation_choice=random.choice(choices or arr)
   self.render_facade()
 def choose_foundation_color(self):
  res=colorchooser.askcolor(color=self.foundation_color,title='Foundation colour')
  if res and res[1]:
   self.foundation_color=res[1]; self.foundation_color_enabled.set(False); self.render_facade()
 def _repeat_iso_trim(self, target, tile, y_start=0):
  """Repeat a 2px-wide trim fragment across the wall, shifting 1px per 2px horizontally."""
  if tile.width > 2:
   tile=tile.crop((0,0,2,tile.height))
  x=0; step=max(1,tile.width); y=int(y_start)
  while x < target.width:
   place_clipped(target,tile,x,y)
   x += step; y += 1
 def apply_rustication(self, base, enabled, state_layers=None):
  if not enabled or not self.assets.get('rustication'): return base
  base=base.copy(); source=self.assets['rustication'][0]['image']
  tile=source.crop((0,0,min(2,source.width),source.height))
  # Recompute the vertical distribution from the CURRENT wall height, not 12x25 defaults.
  # Each horizontal repeat advances (tile.width, 1), so reserve that diagonal drop.
  diagonal_drop=max(0,((base.width-1)//max(1,tile.width)))
  top=0
  lowest_start=max(0,base.height-tile.height-diagonal_drop)
  top=min(top,lowest_start)
  count=max(1,min(40,int(self.rust_count.get())))
  if count==1: starts=[max(0,(top+lowest_start)//2)]
  else: starts=[round(top+i*(lowest_start-top)/(count-1)) for i in range(count)]
  for y_start in starts: self._repeat_iso_trim(base,tile,y_start)
  return base
 def make_first_floor_module(self, base=None, rust=False, add_foundation=True):
  base=(base or self.applied_module).copy()
  if add_foundation and self.first_foundation.get() and self.foundation_choice:
   f=self.foundation_choice['image'].copy()
   color=self.wall_color if self.foundation_color_enabled.get() else self.foundation_color
   f=tint_sprite(f,color,'shade',100)
   ox=int(self.foundation_x.get()); oy=base.height-1+int(self.foundation_y.get())
   left=min(0,ox); top=min(0,oy); right=max(base.width,ox+f.width); bottom=max(base.height,oy+f.height)
   extended=Image.new('RGBA',(right-left,bottom-top),(0,0,0,0))
   extended.alpha_composite(base,(-left,-top)); place_clipped(extended,f,ox-left,oy-top)
   return extended, left, top
  return base,0,0
 def _wall_only_snapshot(self, index):
  current=self._capture_type_state(); enabled=dict(self.enabled); active=self.active_type
  try:
   if self.independent_edit.get() and index in self.type_states: self._restore_type_state(self.type_states[index])
   self.active_type=index
   self.enabled={c:False for c in ORDER}
   self._compose_only(rustication_enabled=self._rust_for_type(index))
   return self.module.copy()
  finally:
   self.enabled=enabled; self.active_type=active; self._restore_type_state(current)
   self._compose_only(rustication_enabled=self._rust_for_type(active))
 def _band_wall_snapshot(self, index):
  """Build the rail tile: wall + that floor's rustication + cornice, no window beads."""
  current=self._capture_type_state(); active=self.active_type
  try:
   if self.independent_edit.get() and index in self.type_states:
    self._restore_type_state(self.type_states[index])
   self.active_type=index
   keep_cornice=bool(self.enabled.get('cornice',False) and self.choice.get('cornice'))
   self.enabled={c:False for c in ORDER}
   self.enabled['cornice']=keep_cornice
   self._compose_only(rustication_enabled=self._rust_for_type(index))
   return self.module.copy()
  finally:
   self.active_type=active
   self._restore_type_state(current)
   self._compose_only(rustication_enabled=self._rust_for_type(active))
 def _facade_width_changed(self, *_args):
  # Do not snap the user's value back to a tile multiple; every 2px change is valid.
  if getattr(self, '_width_render_pending', False) or getattr(self,'_preparing_wall_assemblies',False): return
  self._width_render_pending=True
  def _run():
   self._width_render_pending=False
   if getattr(self, 'module_applied', False) and not getattr(self,'_preparing_wall_assemblies',False): self.render_facade()
  self.root.after_idle(_run)
 def _front_module(self,idx,with_layers=False,window_only=False):
  """FRONT sprites: use visible-pixel anchors around the window glass.

  Each component's manual FRONT offset is separate from the ISO offset.
  The transparent padding in sprite sheets must not shift the details.
  """
  iw,ih=self.module_size()
  fw=max(1,round(iw*2**0.5))
  # Preserve the original per-floor vertical rhythm: avoid rescaling rows.
  fh=max(5,ih-round(iw/2))
  base=Image.new('RGBA',(fw,fh),(0,0,0,0) if window_only else ImageColor.getrgb(self.wall_color)+(255,))
  layers={}
  if not window_only and self._rust_for_type(idx) and self.assets.get('rustication'):
   rust=self.assets['rustication'][0]['front_image']
   self._fill_front_rust(base,rust)
  sprites={}
  for cat in ORDER:
   item=self.choice.get(cat)
   if not self.enabled.get(cat) or not item:continue
   sprite=item.get('front_image',item['image'])
   tint=self.component_colors.get(cat)
   if tint:sprite=tint_sprite(sprite,tint,self.component_modes[cat],self.component_strength[cat])
   sprites[cat]=sprite

  # Anchor the visible GLASS, not the dimensions of the transparent PNG cell.
  glass=sprites.get('glass')
  gb=glass.getbbox() if glass is not None else None
  if gb is None:
   # Fallback when glass is disabled: use the frame as a central reference.
   glass=sprites.get('frame') or sprites.get('casing')
   gb=glass.getbbox() if glass is not None else None
  if gb is None:gb=(0,0,fw//2, max(3,fh//2))
  visible_w=gb[2]-gb[0];visible_h=gb[3]-gb[1]
  center_x=fw//2
  # Position the painted glass in the lower half to leave room for pediments.
  glass_top=max(2,round(fh*0.52)-visible_h//2)
  glass_bottom=glass_top+visible_h

  for cat in ORDER:
   if window_only and cat=='cornice':continue
   sprite=sprites.get(cat)
   if sprite is None:continue
   bbox=sprite.getbbox()
   if bbox is None:continue
   l,t,r,b=bbox
   visible_center2=l+r
   # Vertical offsets below are relative to the VISIBLE glass edges.
   # Multiple window decorations share exactly the same horizontal axis.
   x=round(center_x-visible_center2/2)
   if cat=='glass':
    y=glass_top-t
   elif cat in ('frame','casing'):
    y=glass_top-t
   elif cat=='sill':
    y=glass_bottom-t
   elif cat=='sandrik':
    y=glass_top-b
   elif cat=='bracket':
    y=glass_bottom-t
   else:
    y=-t
   dx,dy=self.front_offset.get(cat,(0,0))
   if cat!='glass' and glass is sprites.get('glass'):
    gx,gy=self.front_offset.get('glass',(0,0))
    dx+=gx;dy+=gy
   x+=dx;y+=dy
   layer=Image.new('RGBA',(fw,fh),(0,0,0,0))
   if cat=='cornice':
    # Repeating FRONT horizontal trim shares one stable baseline.
    piece=sprite
    first_x=x
    for xx in range(first_x,fw,max(1,piece.width)):
     place_clipped(layer,piece,xx,y)
    for xx in range(first_x-piece.width,-piece.width,-piece.width):
     place_clipped(layer,piece,xx,y)
   else:
    place_clipped(layer,sprite,x,y)
   layers[cat]=layer
   base.alpha_composite(layer)
  return (base,layers) if with_layers else base

 def _fill_front_rust(self, target, tile):
  """Full-height, continuous front rustication, without gaps between windows.

  The hand-drawn front tile is repeated in its original pixel dimensions,
  never scaled. Transparent pixels reveal the wall base color.
  """
  if tile is None or not tile.getbbox():return
  tw,th=tile.size
  # The ISO module uses an explicit rust_count. FRONT must honour the same
  # count, not blindly repeat a 5px tile and lose stripes when a floor is
  # mapped to the physical wall height by Volume Editor.
  count=max(1,min(40,int(self.rust_count.get())))
  bbox=tile.getbbox()
  if bbox is None:return
  # Pin the visible lower edge of the last rustication strip to the floor's
  # final row. Keeping a one- or two-pixel aesthetic margin at the bottom
  # previously left an unwanted un-rusticated band above the foundation.
  top=-bbox[1]
  bottom=max(top,target.height-bbox[3])
  positions=([round((top+bottom)/2)] if count==1 else
             [round(top+i*(bottom-top)/(count-1)) for i in range(count)])
  for y in dict.fromkeys(positions):
   for x in range(0,target.width,max(1,tw)):
    place_clipped(target,tile,x,y)

 def _build_front_facade(self):
  """One continuous FRONT facade background; windows are transparent overlays.

  Cornices and rustication are drawn across the whole elevation *before*
  placing windows. Window sprite backgrounds cannot erase the decoration.
  """
  rows=max(1,min(40,int(self.floors.get())))
  front_w=max(1,round(int(self.facade_width.get())*2**0.5))
  modules={}; states={}
  snapshot=self._capture_type_state(); active=self.active_type
  try:
   for i in range(4):
    if self.independent_edit.get() and i in self.type_states:
     self._restore_type_state(self.type_states[i])
    states[i]=self._capture_type_state()
    modules[i]=self._front_module(i,window_only=True)
  finally:
   self._restore_type_state(snapshot);self.active_type=active
  bands=[]
  front_spans=[]
  front_band_widths=[]
  for row in range(rows):
   idx=0 if row==0 else 1 if row==1 else 3 if row==rows-1 else 2
   tile=modules[idx]
   state=states[idx]
   count=max(0,min(40,int(self.floor_counts[idx].get())))
   iw=self.type_modules.get(idx,self.applied_module).width
   gap=max(0,int(self.floor_gap_vars[idx].get()))
   pitch=round((iw+gap)*2**0.5)
   full_w=max(front_w,tile.width+(count-1)*pitch if count else front_w)
   wall_color=ImageColor.getrgb(state['wall_color'])+(255,)
   band=Image.new('RGBA',(full_w,tile.height),wall_color)
   # Full-width/floor-height base decoration, independent of module count.
   if self._rust_for_type(idx) and self.assets.get('rustication'):
    self._fill_front_rust(band,self.assets['rustication'][0]['front_image'])
   if state['enabled'].get('cornice') and state['choice'].get('cornice'):
    item=state['choice']['cornice']
    trim=item.get('front_image',item['image'])
    tint=state['component_colors'].get('cornice')
    if tint:trim=tint_sprite(trim,tint,state['component_modes']['cornice'],state['component_strength']['cornice'])
    # Respect the cornice position from the FRONT module editor, including
    # trim placed at the bottom of a floor. Do not force every trim to y=2.
    _,dy=state.get('front_offset',{}).get('cornice',(0,0))
    bbox=trim.getbbox()
    anchor_y=-(bbox[1] if bbox else 0)+int(dy)
    for xx in range(0,full_w,max(1,trim.width)):
     place_clipped(band,trim,xx,anchor_y)
   start=round((full_w-(tile.width+(count-1)*pitch))/2) if count else 0
   front_spans.append([(start+j*pitch, start+j*pitch+tile.width) for j in range(count)])
   front_band_widths.append(full_w)
   for j in range(count):place_clipped(band,tile,start+j*pitch,0)
   if row==0 and self.first_foundation.get() and self.foundation_choice:
    f=self.foundation_choice['front_image']
    color=self.wall_color if self.foundation_color_enabled.get() else self.foundation_color
    f=tint_sprite(f,color,'shade',100)
    # The foundation belongs INSIDE the ground floor, immediately above its
    # bottom edge. Extending the image here used to add a fake extra floor
    # height, which subsequently desynchronised the Volume Editor wall.
    fy=band.height-f.height+int(self.foundation_y.get())
    for xx in range(round(self.foundation_x.get()*2**0.5),full_w,max(1,f.width)):
     place_clipped(band,f,xx,fy)
   bands.append(band)
  self.front_band_heights=[im.height for im in bands]
  self.front_module_spans=front_spans
  self.front_band_widths=front_band_widths
  total=sum(im.height for im in bands)
  out=Image.new('RGBA',(max(i.width for i in bands),total),(0,0,0,0))
  y=0
  for im in reversed(bands):
   out.alpha_composite(im,((out.width-im.width)//2,y));y+=im.height
  return out

 def render_facade(self):
  if not getattr(self,'module_applied',False):
   # Initial defaults and imported states are usable without pressing Apply.
   self._flush_live_module()
   if not getattr(self,'module_applied',False):return
  rows=max(1,min(40,int(self.floors.get())))
  floor_types=[]
  for row in range(rows):
   if row==0: idx=0
   elif row==1: idx=1
   elif row==rows-1: idx=3
   else: idx=2
   floor_types.append(idx)
  bands=[]
  for idx in floor_types:
   module=self.type_modules.get(idx,self.applied_module).copy()
   mw,mh=module.size
   iso_dy=max(1,round(mw/2))
   rail=self._band_wall_snapshot(idx).copy()
   # The rail for each floor uses that floor type's own editable wall height.
   # Never reuse the default module height: that caused gaps when a floor was taller/shorter.
   tile=Image.new('RGBA',(mw,mh),(0,0,0,0))
   place_clipped(tile,rail,0,mh-rail.height)
   count=max(0,min(40,int(self.floor_counts[idx].get())))
   gap=max(0,min(120,int(self.floor_gap_vars[idx].get())))
   pitch=mw+gap
   group_w=0 if count<=0 else mw+(count-1)*pitch
   band_w=max(1,int(self.facade_width.get()),group_w)
   if band_w%2: band_w+=1
   # Continuous wall rail, made from repeated full wall segments. Each segment advances
   # diagonally by half its width. The wall and window modules share the same floor height.
   segments=max(1,(band_w+mw-1)//mw)
   band_h=mh+(segments-1)*iso_dy
   band=Image.new('RGBA',(band_w,band_h),(0,0,0,0))
   for j in range(segments):
    x=j*mw; y=j*iso_dy
    place_clipped(band,tile,x,y)
   # Center the window group as a single mass on the facade midpoint, regardless of count.
   if count>0:
    start_x=(band_w-group_w)//2
    for j in range(count):
     x=start_x+j*pitch
     y=round(x*iso_dy/mw)
     place_clipped(band,module,x,y)
   # Foundation is a continuous rail attached only to the ground-floor band.
   # Repeat the 12px foundation segment across the width with the same isometric drift.
   if idx==0 and self.first_foundation.get() and self.foundation_choice:
    foundation=self.foundation_choice['image'].copy()
    fcolor=self.wall_color if self.foundation_color_enabled.get() else self.foundation_color
    foundation=tint_sprite(foundation,fcolor,'shade',100)
    # The ISO ground line rises by 1 pixel per 2 horizontal pixels.
    # Place the foundation along that SAME ground line and inside the
    # existing band instead of appending hundreds of transparent pixels.
    # The old band.height-1 anchor was at the very lowest *right* corner
    # of the sheared wall, far below its left corner.
    fx=int(self.foundation_x.get())
    fy=mh-foundation.height+int(self.foundation_y.get())
    x=fx
    while x < band.width:
     y=fy+round(x/2)
     place_clipped(band,foundation,x,y)
     x+=foundation.width
   bands.append((band,idx,mh,iso_dy))
  # Stack from the top down using each band's actual height. Adjacent floors overlap
  # by their own module height minus the isometric diagonal step, so custom heights
  # cannot create holes or detach the top floor.
  placements=[]
  y_positions=[0]*len(bands)
  for i in range(len(bands)-2,-1,-1):
   upper_height=bands[i+1][2]
   upper_dy=bands[i+1][3]
   y_positions[i]=y_positions[i+1]+max(1,upper_height-upper_dy)
  for i,(band,idx,mh,dy) in enumerate(bands):
   placements.append((0,y_positions[i],band))
  minx=min(x for x,y,im in placements); miny=min(y for x,y,im in placements)
  maxx=max(x+im.width for x,y,im in placements); maxy=max(y+im.height for x,y,im in placements)
  out=Image.new('RGBA',(max(1,maxx-minx),max(1,maxy-miny)),(0,0,0,0))
  for x,y,im in placements: place_clipped(out,im,x-minx,y-miny)
  # Physical wall height at the near-left corner of the ISO facade.
  # This is NOT the bounding-box height of a diagonally sheared picture:
  # the latter contains an additional width/2 pixels of horizontal run.
  # Derive it from the actual stacked floor modules, independently of
  # foundation decorations and transparent image margins.
  # An ISO floor image can end 2-6 px ABOVE its nominal module box.
  # Measure the actually painted bottom envelope instead of sizing a wall
  # from its transparent padding. Every x adds x/2 to the 2:1 baseline.
  # Use the median over the facade: individual decorations and pixel steps
  # cannot move the overall ground plane.
  import statistics
  alpha=out.getchannel('A')
  baselines=[]
  for xx in range(out.width):
   for yy in range(out.height-1,-1,-1):
    if alpha.getpixel((xx,yy)):
     baselines.append(yy+1-xx/2)
     break
  self.facade_wall_height_px=max(1,statistics.median(baselines)) if baselines else 1
  self.facade=out
  # A second master is constructed from the FRONT assets, not transformed
  # from the isometric façade. This is intentionally independent of blur.
  self.facade_front=self._build_front_facade()
  self.show_facade()
  if hasattr(self,"volume_app") and self.tabs.index(self.tabs.select())==2: self.update_volume_facade()
  counts=', '.join(f'{self.type_names[i]}: {self.floor_counts[i].get()}' for i in range(4))
  heights=', '.join(f'{self.type_names[idx]} {self.type_modules.get(idx,self.applied_module).height}px' for idx in sorted(set(floor_types)))
  self.facade_status.set(f'{self.wall_names[self.active_wall]} · width {int(self.facade_width.get())}px · {rows} floors · {heights} · {counts} · size {out.width} × {out.height} px')
  self._remember_wall()
  if hasattr(self,'volume_app'):
   self.update_volume_facade()
  if hasattr(self,'elevations_tray_canvas'):
   self.root.after_idle(self._refresh_elevation_views)
 def _build_volume_bridge(self):
  # Separate controls are attached to the existing Volume Editor's right
  # panel, keeping its geometry, rotation, save and cast-shadow UI intact.
  bar=ttk.Frame(self.volume_app.canvas.master)
  bar.pack(before=self.volume_app.canvas,fill='x',pady=(0,5))
  ttk.Checkbutton(bar,text='Facade on wall',variable=self.volume_apply_enabled,command=self.update_volume_facade).pack(side='left',padx=4)
  ttk.Checkbutton(bar,text='Dimensions from facade',variable=self.volume_sync_enabled,command=self.update_volume_facade).pack(side='left',padx=4)
  # Second, compact rotation slider in the open space at right.  Both
  # sliders stay synchronised by Volume Editor's angle update routine.
  vol=self.volume_app
  ttk.Label(bar,text='Rotation').pack(side='left',padx=(10,4))
  slider=ttk.Scale(bar,from_=-12,to=12,orient='horizontal',command=vol.slide_rotation)
  slider.pack(side='left',fill='x',expand=True,padx=(0,6))
  label=ttk.Label(bar,text='0°',width=5)
  label.pack(side='left',padx=(0,4))
  vol.bridge_angle_slider=slider
  vol.bridge_angle_label=label
  try:
   vol.rotation_bar.pack_forget()
  except AttributeError:
   pass
  # The facade updates automatically; no duplicate refresh button.
  self._refresh_auto_filter()

 def _manual_filter_selected(self,event=None):
  # Any manual selection takes precedence until Auto is turned on again.
  self.volume_auto_filter.set(False)
  self.update_volume_facade()

 def _refresh_auto_filter(self):
  if self.volume_auto_filter.get():
   angle=self.volume_app.angle % 360
   # Standard iso and exact screen-horizontal walls need no blur.
   # All other 15-degree steps use gentle filtering by default.
   mode='Pixels' if angle%45==0 else 'Smooth'
   self.volume_filter.set(mode)
  self.update_volume_facade()

 def _on_tab_changed(self,event=None):
  if self.tabs.index(self.tabs.select())==2: self.update_volume_facade()

 def _prepare_wall_assemblies(self):
  """Keep opposite sides physically equal without stretching source sprites.

  If the required window group exceeds the nominal body size, enlarge both
  facing wall rails and rebuild them at their true native pixel pitches.
  """
  if getattr(self,'_preparing_wall_assemblies',False):return
  front=self.wall_configs.get('front')
  if not front or not front['applied']:return
  self._preparing_wall_assemblies=True
  self._suppress_volume_bridge=True
  original=self.active_wall
  try:
   for wall in self.wall_names:
    if wall in self.wall_configs:continue
    cfg=copy.deepcopy(front)
    if wall in ('left','right'):
     cfg['counts']=[min(3,v) for v in cfg['counts']]
    cfg['facade']=None;cfg['facade_front']=None
    cfg['spans']=None;cfg['band_heights']=[];cfg['band_widths']=[]
    cfg['width']=self.pair_widths['front' if wall in ('front','back') else 'side']
    self.wall_configs[wall]=cfg
   # A facade band may grow beyond its nominal width if many windows and
   # gaps are requested. All four wall masters must then be rebuilt at the
   # exact width of their physical pair, rather than image-scaled in 3D.
   actual={}
   for wall,cfg in self.wall_configs.items():
    group='front' if wall in ('front','back') else 'side'
    required=max(12,self.pair_widths[group])
    for idx,mod in cfg['type_modules'].items():
     count=max(0,int(cfg['counts'][idx]));gap=max(0,int(cfg['gaps'][idx]))
     if count:
      required=max(required,mod.width+(count-1)*(mod.width+gap))
    if required%2:required+=1
    actual[group]=max(actual.get(group,0),required)
   for group,w in actual.items():self.pair_widths[group]=w
   for wall,cfg in list(self.wall_configs.items()):
    required=self.pair_widths['front' if wall in ('front','back') else 'side']
    if cfg['facade'] is not None and cfg['width']==required and cfg['facade'].width==required:
     continue
    self._restore_wall(wall)
    self.facade_width.set(required)
    if self.module_applied:self.render_facade()
   self._restore_wall(original)
   self.wall_selector.set(self.wall_names[original])
   self.wall_name_label.configure(text=self.wall_names[original])
   if self.facade is not None:self.show_facade()
  finally:
   self._suppress_volume_bridge=False
   self._preparing_wall_assemblies=False

 def update_volume_facade(self):
  if not hasattr(self,'volume_app'):return
  vol=self.volume_app
  if getattr(self,'_suppress_volume_bridge',False):return
  if getattr(self,'module_applied',False) and self.facade is not None:
   self._remember_wall()
   self._prepare_wall_assemblies()
  if not self.volume_apply_enabled.get():
   vol.facade_texture=None;vol.facade_source=None;vol.facade_front=None
   vol.wall_facades={};vol.accessory_wall_color=None;vol.schedule();return

  # Each wall has independent artwork, counts, gaps and preview bands.
  # Main and rear share real X width; left/right share real Y depth.
  mapping={}
  layouts={}
  floors=max(1,int(self.floors.get()))
  for wall in self.wall_names:
   cfg=self.wall_configs.get(wall)
   if cfg is None or not cfg['applied'] or cfg['facade'] is None:continue
   mapping[wall]={'iso':cfg['facade'],'front':cfg['facade_front']}
   width=max(1,cfg['facade'].width)
   spans=[];row_counts=[]
   for row in range(floors):
    kind=0 if row==0 else 1 if row==1 else 3 if row==floors-1 else 2
    count=max(1,int(cfg['counts'][kind]))
    row_counts.append(count)
    module=cfg['type_modules'].get(kind,cfg['applied_module'])
    module_width=max(1,module.width if module is not None else 12)
    gap=max(0,int(cfg['gaps'][kind]))
    pitch=module_width+gap
    group_width=module_width+(count-1)*pitch
    start=(width-group_width)/2
    edges=[max(0,min(1,(start+j*pitch-(gap/2 if j else 0))/width)) for j in range(count)]
    edges.append(max(0,min(1,(start+group_width)/width)))
    spans.append([(edges[j],edges[j+1]) for j in range(count)])
   layouts[wall]={
     'floors':floors,'counts':row_counts,'spans':spans,
     'front_spans':cfg['spans'],
     'band_heights':cfg['band_heights'],'band_widths':cfg['band_widths']}
  front=self.wall_configs.get('front')
  if front and front['facade'] is not None:
   vol.facade_source=front['facade']
   vol.facade_front=front['facade_front']
  else:
   vol.facade_source=None;vol.facade_front=None
  vol.facade_texture=vol.facade_source
  vol.wall_facades=mapping
  vol.set_wall_layouts(layouts)
  # Preserve old projects where only the front facade was available.
  if 'front' in layouts:
   f=layouts['front']
   vol.set_module_layout(floors,f['counts'],f['spans'],
       front_spans=f['front_spans'],band_heights=f['band_heights'],
       band_widths=f['band_widths'])
  vol.accessory_wall_color=ImageColor.getrgb(self.wall_color)
  vol.facade_filter=self.volume_filter.get()
  if self.volume_sync_enabled.get() and vol.blocks:
   b=vol.blocks[0]
   # A single rectangular block cannot have four independent edge lengths.
   # Opposite walls therefore share their physical extent by construction.
   b.w=max(12,self.pair_widths['front'])
   b.d=max(12,self.pair_widths['side'])
   if front and front['facade'] is not None:
    iso_master_h=max(1,front['wall_height'] or
                  (front['facade'].height-(front['facade'].width-1)/2))
    front_master_h=sum(front['band_heights'])
    if not front_master_h and front['facade_front'] is not None:
     front_master_h=front['facade_front'].height
    b.h=max(10,round(max(1,front_master_h or iso_master_h)/2))
   vol.refresh_list()
  vol.schedule()

 def show_facade(self):
  if self.facade is None:return
  preview=self.facade
  self.facade_photo,self.facade_scale,self.facade_origin=self.draw_image(self.facade_canvas,preview)
 def save_module(self):
  p=filedialog.asksaveasfilename(initialdir=str(OUT),initialfile='facade_module.png',defaultextension='.png',filetypes=[('PNG','*.png')],title='Save module')
  if not p:return
  self.module.save(p); Path(p).with_suffix('.json').write_text(json.dumps(self.module_data(),ensure_ascii=False,indent=2),encoding='utf-8')
  self.module_status.set('Module and editable settings saved.')
 def module_data(self):
  return {'version':19.0,'window_size':self.window_size.get(),'active_type':self.type_names[self.active_type],'independent_edit':self.independent_edit.get(),'module_size':list(self.module.size),'wall_color':self.wall_color,'components':{c:{'enabled':self.enabled[c],'asset':self.choice[c]['name'] if self.choice[c] else None,'offset':self.offset[c],'front_offset':self.front_offset[c],'color':self.component_colors[c],'color_mode':self.component_modes[c],'color_strength':self.component_strength[c]} for c in ORDER}}
 def _encode_state(self,state):
  data=copy.deepcopy({k:v for k,v in state.items() if k!='choice'})
  data['choice']={cat:(item.get('name') if item else None) for cat,item in state['choice'].items()}
  return data

 def _decode_state(self,data):
  base=self._capture_type_state()
  for key in ('wall_color','enabled','offset','front_offset','component_colors','component_modes','component_strength','extra_height','window_size','window_shape'):
   if key in data:base[key]=copy.deepcopy(data[key])
  if 'window_shape' not in data:
   saved_glass=data.get('choice',{}).get('glass') or ''
   base['window_shape']='Arched' if str(saved_glass).startswith('glass_arch') else 'Standard'
  for cat,name in data.get('choice',{}).items():
   if cat not in ORDER:continue
   candidates=self.assets.get(cat,[])
   selected=next((a for a in candidates if a['name']==name),None)
   if selected is None and cat=='glass' and name:
    size=str(name).split()[-1]
    selected=next((a for a in candidates if a.get('size')==size and a.get('shape')=='normal'),None)
   if selected is None and cat=='casing' and name:
    size=base.get('window_size','M')
    shape='arch' if base.get('window_shape')=='Arched' else 'normal'
    selected=next((a for a in candidates if a.get('size')==size and a.get('shape')==shape),None)
   base['choice'][cat]=selected
  # Preserve compatibility with existing v2.1 project files.
  if 'window_shape' not in data:
   glass=base['choice'].get('glass')
   base['window_shape']='Arched' if glass and glass.get('shape')=='arch' else 'Standard'
  return base

 def save_project(self):
  self._flush_live_module()
  p=filedialog.asksaveasfilename(initialdir=str(OUT),initialfile='facade_project.json',defaultextension='.json',filetypes=[('Project JSON','*.json')],title='Save facade project')
  if not p:return
  self.type_states[self.active_type]=self._capture_type_state()
  self._remember_wall()
  assembly={'facade_width':self.pair_widths['front'],'side_width':self.pair_widths['side'],'floors':self.floors.get(),
            'floor_counts':[v.get() for v in self.floor_counts],
            'floor_gaps':[v.get() for v in self.floor_gap_vars],
            'rust_first':self.rust_first.get(),'rust_second':self.rust_second.get(),'rust_middle':self.rust_middle.get(),'rust_upper':self.rust_upper.get(),
            'rust_count':self.rust_count.get(),'first_foundation':self.first_foundation.get(),
            'foundation_name':self.foundation_choice.get('name') if self.foundation_choice else None,
            'foundation_color':self.foundation_color,'foundation_color_enabled':self.foundation_color_enabled.get(),
            'foundation_x':self.foundation_x.get(),'foundation_y':self.foundation_y.get()}
  # v0.9 stores each wall separately while keeping old front-only keys.
  wall_data={}
  for wall,cfg in self.wall_configs.items():
   wall_data[wall]={'width':cfg['width'],'counts':cfg['counts'],'gaps':cfg['gaps'],
     'active_type':cfg['active_type'],'independent_edit':cfg['independent'],
     'rust_first':cfg.get('rust_first',False),'rust_second':cfg.get('rust_second',False),'rust_middle':cfg.get('rust_middle',False),'rust_upper':cfg.get('rust_upper',False),
     'rust_count':cfg.get('rust_count',5),
     'foundation':cfg.get('foundation',False),
     'foundation_name':cfg['foundation_choice'].get('name') if cfg.get('foundation_choice') else None,
     'foundation_color':cfg.get('foundation_color',self.foundation_color),
     'foundation_color_enabled':cfg.get('foundation_color_enabled',True),
     'foundation_x':cfg.get('foundation_x',0),
     'foundation_y':cfg.get('foundation_y',0),
     'types':{str(i):self._encode_state(st) for i,st in cfg['types'].items()}}
  data={'format':'sc3k-architecture-facade','version':0.9,'assembly':assembly,
        'active_wall':self.active_wall,'walls':wall_data,
        'active_type':self.active_type,'independent_edit':self.independent_edit.get(),
        'types':{str(i):self._encode_state(self.type_states.get(i,self._capture_type_state())) for i in range(4)}}
  try:
   Path(p).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
   self.facade_status.set('Project saved: '+p)
  except Exception as exc:messagebox.showerror('Save Error',str(exc))

 def load_project(self):
  pending=getattr(self,'_live_apply_id',None)
  if pending is not None:
   try:self.root.after_cancel(pending)
   except (ValueError,tk.TclError):pass
  self._live_apply_id=None
  self._loading_facade_project=True
  try:
   self._load_project_impl()
  finally:
   self._loading_facade_project=False

 def _load_project_impl(self):
  p=filedialog.askopenfilename(initialdir=str(OUT),filetypes=[('Project JSON','*.json')],title='Open facade project')
  if not p:return
  try:
   data=json.loads(Path(p).read_text(encoding='utf-8'))
   data=_read_legacy_labels(data)
   if data.get('format')!='sc3k-architecture-facade':
    raise ValueError('This is not a supported SC3K project. An incomplete legacy JSON file cannot be recovered without losing settings.')
   a=data['assembly']
   states={int(i):self._decode_state(st) for i,st in data['types'].items()}
   self.facade_width.set(int(a['facade_width']));self.floors.set(int(a['floors']))
   for i,v in enumerate(a['floor_counts'][:4]):self.floor_counts[i].set(int(v))
   for i,v in enumerate(a['floor_gaps'][:4]):self.floor_gap_vars[i].set(int(v))
   self.rust_first.set(bool(a['rust_first']));self.rust_second.set(bool(a['rust_second']));self.rust_middle.set(bool(a.get('rust_middle',False)));self.rust_upper.set(bool(a.get('rust_upper',False)))
   self.rust_count.set(int(a['rust_count']))
   self.first_foundation.set(bool(a['first_foundation']))
   self.foundation_color=a['foundation_color']
   self.foundation_color_enabled.set(bool(a['foundation_color_enabled']))
   self.foundation_x.set(int(a['foundation_x']));self.foundation_y.set(int(a['foundation_y']))
   foundation_name=a.get('foundation_name')
   self.foundation_choice=next((item for item in self.assets['foundation'] if item['name']==foundation_name),None)
   self.independent_edit.set(bool(data.get('independent_edit',False)))
   self.type_states=states
   self.active_type=max(0,min(3,int(data.get('active_type',0))))
   self.type_selector.current(self.active_type)
   self._restore_type_state(states[self.active_type])
   self.compose_module()
   self.apply_module()
   self.render_facade()
   if data.get('walls'):
    self._suppress_volume_bridge=True
    try:
     self._remember_wall()
     self.pair_widths['front']=int(a.get('facade_width',48))
     self.pair_widths['side']=int(a.get('side_width',32))
     template=copy.deepcopy(self.wall_configs['front'])
     for wall,record in data['walls'].items():
      if wall not in self.wall_names:continue
      cfg=copy.deepcopy(template)
      cfg['width']=int(record.get('width',cfg['width']))
      cfg['counts']=list(record.get('counts',cfg['counts']))
      cfg['gaps']=list(record.get('gaps',cfg['gaps']))
      cfg['active_type']=max(0,min(3,int(record.get('active_type',0))))
      cfg['independent']=bool(record.get('independent_edit',False))
      cfg['rust_first']=bool(record.get('rust_first',cfg.get('rust_first',False)))
      cfg['rust_second']=bool(record.get('rust_second',cfg.get('rust_second',False)))
      cfg['rust_middle']=bool(record.get('rust_middle',cfg.get('rust_middle',False)))
      cfg['rust_upper']=bool(record.get('rust_upper',cfg.get('rust_upper',False)))
      cfg['rust_count']=int(record.get('rust_count',cfg.get('rust_count',5)))
      cfg['foundation']=bool(record.get('foundation',cfg.get('foundation',False)))
      cfg['foundation_choice']=next((x for x in self.assets['foundation'] if x['name']==record.get('foundation_name')),None)
      cfg['foundation_color']=record.get('foundation_color',cfg.get('foundation_color',self.foundation_color))
      cfg['foundation_color_enabled']=bool(record.get('foundation_color_enabled',True))
      cfg['foundation_x']=int(record.get('foundation_x',0))
      cfg['foundation_y']=int(record.get('foundation_y',0))
      cfg['types']={int(i):self._decode_state(st) for i,st in record.get('types',{}).items()}
      if not cfg['types']:cfg['types']=copy.deepcopy(template['types'])
      cfg['facade']=None;cfg['facade_front']=None
      cfg['applied']=True
      self.wall_configs[wall]=cfg
     for wall in list(data['walls']):
      if wall not in self.wall_names:continue
      self._restore_wall(wall)
      self.apply_module()
     final_wall=data.get('active_wall','front')
     if final_wall not in self.wall_configs:final_wall='front'
     self._restore_wall(final_wall)
     self.wall_selector.set(self.wall_names[final_wall])
     self.wall_name_label.configure(text=self.wall_names[final_wall])
     self.show_facade()
    finally:
     self._suppress_volume_bridge=False
    self.update_volume_facade()
   self.facade_status.set('Project loaded: '+p)
  except Exception as exc:messagebox.showerror('Project Open Error',str(exc))
 def export_facade(self):
  self._flush_live_module()
  if self.facade is None: self.render_facade()
  if self.facade is None:return
  p=filedialog.asksaveasfilename(initialdir=str(OUT),initialfile='facade.png',defaultextension='.png',filetypes=[('PNG','*.png')],title='Export facade')
  if p:self.facade.save(p); self.facade_status.set('PNG exported: '+p)
if __name__ == '__main__':
 root=tk.Tk(); app=App(root); root.mainloop()
