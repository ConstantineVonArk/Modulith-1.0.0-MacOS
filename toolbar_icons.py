"""Presentation-only toolbar icon thumbnails, shared by both editors.

The supplied 64-65 pixel artworks remain untouched.  A quality downsample
keeps sub-pixel details visible at the existing 31-32 px UI size.
"""
from PIL import Image, ImageFilter


def thumbnail(source, size=31):
    """Return a crisp, aspect-preserving RGBA thumbnail on a fixed square.

    NEAREST at 64->31 discards half of the source samples and can erase thin
    lines. LANCZOS incorporates them; a modest unsharp mask restores visual
    definition without the strong haloes of aggressive sharpening.
    """
    image = source.convert('RGBA')
    image.thumbnail((size, size), Image.Resampling.LANCZOS)
    image = image.filter(ImageFilter.UnsharpMask(radius=0.7, percent=130, threshold=2))
    result = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    result.alpha_composite(image, ((size-image.width)//2, (size-image.height)//2))
    return result


def attach_tooltip(widget, text, delay=550):
    """Show a small non-modal explanation beneath an icon on hover."""
    import tkinter as tk
    pending = None
    bubble = None

    def hide(_event=None):
        nonlocal pending, bubble
        if pending is not None:
            try: widget.after_cancel(pending)
            except tk.TclError: pass
            pending = None
        if bubble is not None:
            try: bubble.destroy()
            except tk.TclError: pass
            bubble = None

    def show():
        nonlocal pending, bubble
        pending = None
        if not widget.winfo_exists() or bubble is not None:
            return
        bubble = tk.Toplevel(widget)
        bubble.withdraw()
        bubble.overrideredirect(True)
        bubble.configure(bg='#34383b')
        tk.Label(bubble, text=text, bg='#34383b', fg='#ffffff',
                 padx=9, pady=5, justify='left', font=('Helvetica',10),
                 wraplength=300).pack()
        x = widget.winfo_rootx()
        y = widget.winfo_rooty()+widget.winfo_height()+5
        bubble.geometry(f'+{x}+{y}')
        bubble.deiconify()

    def enter(_event=None):
        nonlocal pending
        hide()
        pending = widget.after(delay,show)

    widget.bind('<Enter>',enter,add='+')
    widget.bind('<Leave>',hide,add='+')
    widget.bind('<ButtonPress>',hide,add='+')
    widget.bind('<Destroy>',hide,add='+')
