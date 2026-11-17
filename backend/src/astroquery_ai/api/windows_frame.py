"""Native Windows frame. The WebView document is never modified."""
from __future__ import annotations


def chrome_metrics(dpi=96):
    scale = max(1, dpi) / 96
    return {name: max(1, round(value * scale)) for name, value in
            {'height': 32, 'button_width': 46, 'resize_grip': 5}.items()}


def resize_hit(x, y, width, height, grip):
    left, right, top, bottom = x < grip, x >= width-grip, y < grip, y >= height-grip
    if top: return 13 if left else 14 if right else 12
    if bottom: return 16 if left else 17 if right else 15
    return 10 if left else 11 if right else 2


def install(window):
    """Replace only non-client chrome, keeping native system/window semantics."""
    import ctypes as C
    from ctypes import wintypes as W
    import System
    from System import Action
    from System.Drawing import Color, Font, FontStyle, Point, Size
    from System.Windows.Forms import (Panel, Button, DockStyle, FlatStyle,
        FormWindowState, Cursors, Screen, MouseButtons)

    form = window.native

    def mount():
        if getattr(form, '_astroquery_frame', None): return
        hwnd = int(form.Handle.ToInt64())
        user = C.windll.user32
        dpi_fn = getattr(user, 'GetDpiForWindow', None)
        metrics = chrome_metrics(dpi_fn(hwnd) if dpi_fn else 96)
        content_controls = list(form.Controls)
        base = Color.White
        hover = Color.FromArgb(240, 242, 244)
        ink = Color.FromArgb(31, 41, 55)
        panel = Panel()
        panel.Dock, panel.Height, panel.BackColor = DockStyle.Top, metrics['height'], base
        panel.AccessibleName = '窗口控制区'
        panel.TabStop = False

        user.ReleaseCapture.argtypes = []
        user.SendMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        user.SendMessageW.restype = C.c_ssize_t

        def mouse_down(sender, event):
            if event.Button != MouseButtons.Left: return
            if event.Clicks == 2:
                toggle(None, None)
                return
            screen = sender.PointToScreen(event.Location)
            local = form.PointToClient(screen)
            grip = metrics['resize_grip']
            hit = resize_hit(local.X, local.Y, form.ClientSize.Width, form.ClientSize.Height, grip)
            if form.WindowState == FormWindowState.Maximized: hit = 2
            user.ReleaseCapture()
            user.SendMessageW(hwnd, 0xA1, hit, 0)

        panel.MouseDown += mouse_down

        def toggle(sender, event):
            form.WindowState = (FormWindowState.Normal if form.WindowState == FormWindowState.Maximized
                                else FormWindowState.Maximized)

        buttons = []
        def button(label, glyph, callback):
            b = Button()
            b.Text, b.AccessibleName = glyph, label
            b.Dock, b.Width = DockStyle.Right, metrics['button_width']
            b.FlatStyle, b.BackColor, b.ForeColor = FlatStyle.Flat, base, ink
            b.FlatAppearance.BorderSize = 0
            b.FlatAppearance.MouseOverBackColor = Color.FromArgb(196, 43, 28) if label == '关闭窗口' else hover
            b.FlatAppearance.MouseDownBackColor = Color.FromArgb(170, 35, 25) if label == '关闭窗口' else hover
            b.Font = Font('Segoe MDL2 Assets', 10, FontStyle.Regular)
            b.TabStop = True
            b.Click += callback
            if label == '关闭窗口':
                b.MouseEnter += lambda *_: setattr(b, 'ForeColor', Color.White)
                b.MouseLeave += lambda *_: setattr(b, 'ForeColor', ink)
            panel.Controls.Add(b)
            buttons.append(b)
            return b

        button('最小化窗口', '\ue921', lambda *_: setattr(form, 'WindowState', FormWindowState.Minimized))
        maximum = button('最大化窗口', '\ue922', toggle)
        button('关闭窗口', '\ue8bb', lambda *_: form.Close())

        # The default frame styles remain, so taskbar, system menu, Snap keyboard
        # commands and normal resize/min/max semantics stay with Windows.
        # Remove its visual caption only; preserve form.Text for Alt+Tab/UIA.
        class RECT(C.Structure):
            _fields_ = [('left', C.c_long), ('top', C.c_long), ('right', C.c_long), ('bottom', C.c_long)]
        result_type = C.c_ssize_t
        callback_type = C.WINFUNCTYPE(result_type, W.HWND, W.UINT, W.WPARAM, W.LPARAM, C.c_size_t, C.c_size_t)
        comctl = C.WinDLL('comctl32')
        comctl.DefSubclassProc.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        comctl.DefSubclassProc.restype = result_type
        comctl.SetWindowSubclass.argtypes = [W.HWND, callback_type, C.c_size_t, C.c_size_t]
        comctl.SetWindowSubclass.restype = W.BOOL
        comctl.RemoveWindowSubclass.argtypes = [W.HWND, callback_type, C.c_size_t]

        def proc(h, msg, wp, lp, sid, ref):
            if msg == 0x83 and wp:  # WM_NCCALCSIZE, first rect of NCCALCSIZE_PARAMS
                rect = C.cast(lp, C.POINTER(RECT)).contents
                if form.WindowState == FormWindowState.Maximized:
                    work = Screen.FromHandle(form.Handle).WorkingArea
                    rect.left, rect.top, rect.right, rect.bottom = work.Left, work.Top, work.Right, work.Bottom
                return 0
            if msg == 0x82:  # WM_NCDESTROY
                comctl.RemoveWindowSubclass(h, hook, sid)
            return comctl.DefSubclassProc(h, msg, wp, lp)

        hook = callback_type(proc)
        if not comctl.SetWindowSubclass(hwnd, hook, 0x4151, 0):
            raise OSError('Cannot install the native desktop frame')

        # Narrow native resize targets, outside the unchanged WebView content.
        grips = []
        for dock, cursor in [(DockStyle.Left, Cursors.SizeWE), (DockStyle.Right, Cursors.SizeWE),
                             (DockStyle.Bottom, Cursors.SizeNS)]:
            edge = Panel()
            edge.Dock, edge.BackColor, edge.Cursor = dock, Color.White, cursor
            edge.Width = edge.Height = metrics['resize_grip']
            edge.MouseDown += mouse_down
            form.Controls.Add(edge)
            grips.append(edge)
        form.Controls.Add(panel)
        # WinForms docks in reverse z-order. Keep the existing fill control
        # first so it receives only the space left by the native chrome.
        for content in content_controls: content.BringToFront()

        def resized(*_):
            maximized = form.WindowState == FormWindowState.Maximized
            maximum.Text = '\ue923' if maximized else '\ue922'
            maximum.AccessibleName = '还原窗口' if maximized else '最大化窗口'
            for edge in grips: edge.Visible = not maximized

        form.Resize += resized
        resized()
        dwm = C.WinDLL('dwmapi')
        dwm.DwmSetWindowAttribute.argtypes = [W.HWND, W.DWORD, C.c_void_p, W.DWORD]
        corner, border = C.c_int(2), C.c_uint(0xFFFFFFFE)  # DWMWA_COLOR_NONE
        dwm.DwmSetWindowAttribute(hwnd, 33, C.byref(corner), C.sizeof(corner))
        dwm.DwmSetWindowAttribute(hwnd, 34, C.byref(border), C.sizeof(border))
        user.SetWindowPos.argtypes = [W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT]
        user.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0027)  # FRAMECHANGED|NOMOVE|NOSIZE|NOZORDER
        form.PerformLayout()
        form.Invalidate(True)
        form._astroquery_frame = (hook, panel, buttons, grips, resized, mouse_down)

    form.Invoke(Action(mount))
