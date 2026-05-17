"""
freeform_mcp_server.py  (v5 — critical fix: never opens new board mid-diagram)
===============================================================================
MCP server connecting Claude AI to Apple Freeform.
macOS only. Python 3.10+.

THE BUG THAT WAS FIXED IN v5:
  _ensure_freeform() was calling _open_new_board() on EVERY tool call
  (shape_add, connector_add, etc.), which created a new Freeform document
  each time, scattering each shape across separate blank boards.

THE FIX:
  _ensure_freeform() now ONLY activates Freeform and brings it to front.
  It NEVER opens a new board. Period.

  _open_new_board() is now ONLY called from board_new().
  board_new() is the ONLY tool that intentionally creates a new document.

  This means: call board_new() once at the start, then all subsequent
  shape_add / connector_add / text_add / sticky_add calls draw onto
  THAT SAME board without ever opening a new one.
"""

import base64
import subprocess
import time
from io import BytesIO
from pathlib import Path

import pyautogui
from mcp.server.fastmcp import FastMCP
from PIL import ImageGrab

mcp = FastMCP("Freeform MCP")
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.15


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _run_as(script):
    """Run an AppleScript; return (stdout, stderr, returncode)."""
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.stdout.strip(), r.stderr.strip(), r.returncode


def _window_count():
    """Return number of open Freeform windows."""
    out, _, _ = _run_as("""
    tell application "System Events"
        tell process "Freeform"
            return count of windows
        end tell
    end tell
    """)
    try:
        return int(out)
    except Exception:
        return 0


def _has_open_window():
    """True if Freeform has at least one visible non-minimised window."""
    out, _, _ = _run_as("""
    tell application "System Events"
        tell process "Freeform"
            set wc to count of windows
            if wc = 0 then return "none"
            if minimized of front window then return "minimised"
            return "open"
        end tell
    end tell
    """)
    return out == "open"


def _activate_freeform():
    """
    Bring Freeform to the front. Does NOT open any new board.
    This is the only thing _ensure_freeform() does now.
    """
    # Launch if completely not running
    out, _, _ = _run_as(
        'tell application "System Events" to (name of processes) contains "Freeform"'
    )
    if out != "true":
        subprocess.Popen(["open", "-a", "Freeform"])
        time.sleep(3.5)

    # Unminimise front window if needed
    state, _, _ = _run_as("""
    tell application "System Events"
        tell process "Freeform"
            set wc to count of windows
            if wc = 0 then return "none"
            if minimized of front window then return "minimised"
            return "open"
        end tell
    end tell
    """)
    if state == "minimised":
        _run_as("""
        tell application "System Events"
            tell process "Freeform"
                set minimized of front window to false
            end tell
        end tell
        """)
        time.sleep(0.6)

    # Activate (bring to front)
    _run_as('tell application "Freeform" to activate')
    time.sleep(0.4)


# _ensure_freeform is now just an alias for _activate_freeform.
# It does NOT open new boards. Ever.
_ensure_freeform = _activate_freeform


def _open_new_board():
    """
    Open a new Freeform board. Called ONLY from board_new().
    Never called from drawing tools.
    Tries four methods in order until a window appears.
    """
    # Method 1: make new document (direct app-level AppleScript)
    _run_as('tell application "Freeform" to make new document')
    time.sleep(2.0)
    if _has_open_window():
        return True

    # Method 2: Click "New Board" button in gallery via Accessibility
    _run_as("""
    tell application "System Events"
        tell process "Freeform"
            try
                repeat with w in windows
                    repeat with b in (every button of w)
                        if description of b contains "New" or name of b contains "New" then
                            click b
                            return "clicked"
                        end if
                    end repeat
                end repeat
            end try
        end tell
    end tell
    """)
    time.sleep(2.0)
    if _has_open_window():
        return True

    # Method 3: File > New Board menu
    _run_as("""
    tell application "System Events"
        tell process "Freeform"
            tell menu bar 1
                tell menu bar item "File"
                    tell menu "File"
                        click menu item "New Board"
                    end tell
                end tell
            end tell
        end tell
    end tell
    """)
    time.sleep(2.0)
    if _has_open_window():
        return True

    # Method 4: Cmd+N with long focus delay
    _run_as('tell application "Freeform" to activate')
    time.sleep(1.5)
    pyautogui.hotkey("command", "n")
    time.sleep(2.5)
    return _has_open_window()


def _window_bounds():
    """
    Return {x, y, width, height} of the front Freeform window.
    Three methods, falls back to screen size estimate.
    """
    # Method 1: System Events position + size
    out1, _, rc1 = _run_as("""
    tell application "System Events"
        tell process "Freeform"
            set w to front window
            set px to item 1 of (get position of w)
            set py to item 2 of (get position of w)
            set sw to item 1 of (get size of w)
            set sh to item 2 of (get size of w)
            return (px as string) & "," & (py as string) & "," & (sw as string) & "," & (sh as string)
        end tell
    end tell
    """)
    if rc1 == 0 and out1 and "," in out1:
        try:
            parts = [int(float(v.strip())) for v in out1.split(",")]
            if len(parts) == 4 and parts[2] > 100 and parts[3] > 100:
                return {"x": parts[0], "y": parts[1], "width": parts[2], "height": parts[3]}
        except ValueError:
            pass

    # Method 2: Freeform bounds property
    out2, _, rc2 = _run_as("""
    tell application "Freeform"
        set w to front window
        set b to bounds of w
        return (item 1 of b as string) & "," & (item 2 of b as string) & "," & ((item 3 of b - item 1 of b) as string) & "," & ((item 4 of b - item 2 of b) as string)
    end tell
    """)
    if rc2 == 0 and out2 and "," in out2:
        try:
            parts = [int(float(v.strip())) for v in out2.split(",")]
            if len(parts) == 4 and parts[2] > 100 and parts[3] > 100:
                return {"x": parts[0], "y": parts[1], "width": parts[2], "height": parts[3]}
        except ValueError:
            pass

    # Method 3: Screen size fallback
    try:
        img = ImageGrab.grab()
        sw, sh = img.size
        return {"x": 0, "y": 28, "width": sw, "height": sh - 28}
    except Exception:
        pass

    return {"x": 0, "y": 28, "width": 1440, "height": 872}


def _canvas_to_screen(cx, cy):
    """Canvas (0,0) = centre of Freeform content area (below toolbar)."""
    b = _window_bounds()
    toolbar_height = 80
    sx = b["x"] + b["width"] // 2 + cx
    sy = b["y"] + toolbar_height + (b["height"] - toolbar_height) // 2 + cy
    return int(sx), int(sy)


def _screenshot_window():
    """Capture Freeform window as base64 PNG."""
    _activate_freeform()
    time.sleep(0.4)
    b = _window_bounds()
    img = ImageGrab.grab(bbox=(b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"]))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _click_menu(*path):
    """Click an AppleScript menu path (depth 2 or 3)."""
    if len(path) == 2:
        menu, item = path
        script = f"""
tell application "System Events"
    tell process "Freeform"
        tell menu bar 1
            tell menu bar item "{menu}"
                tell menu "{menu}"
                    click menu item "{item}"
                end tell
            end tell
        end tell
    end tell
end tell"""
    elif len(path) == 3:
        menu, sub, leaf = path
        script = f"""
tell application "System Events"
    tell process "Freeform"
        tell menu bar 1
            tell menu bar item "{menu}"
                tell menu "{menu}"
                    tell menu item "{sub}"
                        tell menu "{sub}"
                            click menu item "{leaf}"
                        end tell
                    end tell
                end tell
            end tell
        end tell
    end tell
end tell"""
    else:
        return False
    _, _, rc = _run_as(script)
    time.sleep(0.4)
    return rc == 0


def _esc():
    pyautogui.press("escape")
    time.sleep(0.15)


def _paste(text):
    """Copy text to clipboard and paste into focused field."""
    safe = text.replace("\\", "\\\\").replace('"', '\\"')
    _run_as(f'set the clipboard to "{safe}"')
    pyautogui.hotkey("command", "v")
    time.sleep(0.2)


# ============================================================
# DEBUG / DIAGNOSTIC TOOL
# ============================================================

@mcp.tool()
def debug_info() -> dict:
    """
    Diagnostic tool. Returns window state, bounds, screen size.
    Call this if drawing tools misbehave.
    """
    _activate_freeform()

    has_window = _has_open_window()
    wcount = _window_count()

    out1, err1, rc1 = _run_as("""
    tell application "System Events"
        tell process "Freeform"
            set wc to count of windows
            if wc = 0 then return "NO_WINDOWS"
            set w to front window
            set px to item 1 of (get position of w)
            set py to item 2 of (get position of w)
            set sw to item 1 of (get size of w)
            set sh to item 2 of (get size of w)
            return (px as string) & "," & (py as string) & "," & (sw as string) & "," & (sh as string)
        end tell
    end tell
    """)

    out2, err2, rc2 = _run_as("""
    tell application "Freeform"
        if (count of windows) = 0 then return "NO_WINDOWS"
        set w to front window
        set b to bounds of w
        return (item 1 of b as string) & "," & (item 2 of b as string) & "," & (item 3 of b as string) & "," & (item 4 of b as string)
    end tell
    """)

    out3, _, _ = _run_as("""
    tell application "System Events"
        tell process "Freeform"
            set names to {}
            repeat with w in windows
                set end of names to (name of w as string) & "[min=" & (minimized of w as string) & "]"
            end repeat
            return names as string
        end tell
    end tell
    """)

    try:
        img = ImageGrab.grab()
        screen_size = list(img.size)
    except Exception as e:
        screen_size = str(e)

    computed = _window_bounds()
    centre = _canvas_to_screen(0, 0)

    return {
        "has_open_window": has_window,
        "window_count": wcount,
        "window_names": out3,
        "method1_raw": out1, "method1_error": err1, "method1_rc": rc1,
        "method2_raw": out2, "method2_error": err2, "method2_rc": rc2,
        "screen_size": screen_size,
        "computed_bounds": computed,
        "canvas_centre_screen": centre,
    }


# ============================================================
# BOARD MANAGEMENT
# ============================================================

@mcp.tool()
def board_new() -> dict:
    """
    Create a brand-new blank Freeform board.

    Call this ONCE at the start of a new diagram.
    All subsequent shape_add / connector_add / text_add / sticky_add
    calls will draw onto THIS board without creating new ones.

    If Freeform is not running it will be launched first.
    """
    # Launch if needed
    out, _, _ = _run_as(
        'tell application "System Events" to (name of processes) contains "Freeform"'
    )
    if out != "true":
        subprocess.Popen(["open", "-a", "Freeform"])
        time.sleep(4.0)

    _run_as('tell application "Freeform" to activate')
    time.sleep(1.0)

    opened = _open_new_board()
    time.sleep(0.5)
    b = _window_bounds()
    return {
        "status": "ok" if opened else "warning",
        "board_opened": opened,
        "window_bounds": b,
        "note": "All drawing tools will now draw on this board. Do not call board_new() again unless you want a second separate board."
    }


@mcp.tool()
def board_open(file_path: str) -> dict:
    """Open an existing .freeform file. file_path: absolute path."""
    p = Path(file_path).expanduser()
    if not p.exists():
        return {"status": "error", "message": f"File not found: {file_path}"}
    subprocess.Popen(["open", str(p)])
    time.sleep(3)
    _run_as('tell application "Freeform" to activate')
    return {"status": "ok", "file": p.name, "window_bounds": _window_bounds()}


@mcp.tool()
def board_save() -> dict:
    """Save the current board (Cmd+S)."""
    _activate_freeform()
    pyautogui.hotkey("command", "s")
    time.sleep(0.8)
    return {"status": "ok"}


@mcp.tool()
def board_undo() -> dict:
    """Undo the last action (Cmd+Z)."""
    _activate_freeform()
    pyautogui.hotkey("command", "z")
    time.sleep(0.3)
    return {"status": "ok"}


@mcp.tool()
def board_redo() -> dict:
    """Redo the last undone action (Cmd+Shift+Z)."""
    _activate_freeform()
    pyautogui.hotkey("command", "shift", "z")
    time.sleep(0.3)
    return {"status": "ok"}


@mcp.tool()
def board_screenshot() -> dict:
    """
    Screenshot the current Freeform board. Returns base64 PNG.
    Use this to READ what is on the board.
    """
    img_b64 = _screenshot_window()
    return {"status": "ok", "format": "png", "image_base64": img_b64}


@mcp.tool()
def board_zoom(level: str = "fit") -> dict:
    """Zoom the canvas. level: fit, in, out, 100"""
    _activate_freeform()
    zm = {
        "fit": ("View", "Zoom to Fit"),
        "in":  ("View", "Zoom In"),
        "out": ("View", "Zoom Out"),
        "100": ("View", "Actual Size"),
    }
    if level not in zm:
        return {"status": "error", "message": f"Use one of: {list(zm)}"}
    _click_menu(*zm[level])
    return {"status": "ok", "zoom": level}


# ============================================================
# SHAPE TOOLS
# ============================================================

SHAPE_MENU = {
    "rectangle":         "Rectangle",
    "rounded_rectangle": "Rounded Rectangle",
    "circle":            "Circle",
    "oval":              "Oval",
    "triangle":          "Triangle",
    "right_triangle":    "Right Triangle",
    "diamond":           "Diamond",
    "pentagon":          "Pentagon",
    "hexagon":           "Hexagon",
    "octagon":           "Octagon",
    "star":              "Star",
    "heart":             "Heart",
    "speech_bubble":     "Speech Bubble",
    "thought_bubble":    "Thought Bubble",
    "parallelogram":     "Parallelogram",
    "trapezoid":         "Trapezoid",
    "cylinder":          "Cylinder",
    "cloud":             "Cloud",
    "cross":             "Cross",
    "bracket":           "Open Bracket",
    "brace":             "Open Brace",
    "arrow_right":       "Right Arrow",
    "arrow_left":        "Left Arrow",
    "arrow_up":          "Up Arrow",
    "arrow_down":        "Down Arrow",
    "double_arrow":      "Double Arrow",
}


@mcp.tool()
def shape_add(
    shape: str,
    canvas_x: int = 0,
    canvas_y: int = 0,
    width: int = 150,
    height: int = 80,
    label: str = "",
) -> dict:
    """
    Insert a shape onto the CURRENT board (does not create a new board).

    shape    : rectangle, rounded_rectangle, circle, diamond, star,
               speech_bubble, arrow_right, arrow_down, cloud, cylinder,
               triangle, hexagon, oval, heart, parallelogram, and more.
    canvas_x : pixels right of board centre (negative = left)
    canvas_y : pixels below board centre   (negative = up)
    width    : shape width  in pixels (default 150)
    height   : shape height in pixels (default 80)
    label    : text inside the shape (optional)

    Layout reference — (0,0) is board centre:
      Row of 3 boxes:    (-300,0)  (0,0)  (300,0)
      Column of 4 boxes: (0,-300)  (0,-100)  (0,100)  (0,300)
      2x2 grid:          (-200,-120)  (200,-120)  (-200,120)  (200,120)
    """
    # IMPORTANT: only activate, never open a new board
    _activate_freeform()

    key = shape.lower().replace(" ", "_")
    menu_name = SHAPE_MENU.get(key)
    if not menu_name:
        return {"status": "error",
                "message": f"Unknown shape '{shape}'. Options: {list(SHAPE_MENU)}"}

    ok = _click_menu("Insert", "Shape", menu_name)
    time.sleep(0.6)

    b = _window_bounds()
    toolbar_height = 80
    cx = b["x"] + b["width"] // 2
    cy = b["y"] + toolbar_height + (b["height"] - toolbar_height) // 2
    tx, ty = _canvas_to_screen(canvas_x, canvas_y)

    if abs(tx - cx) > 5 or abs(ty - cy) > 5:
        pyautogui.moveTo(cx, cy, duration=0.25)
        time.sleep(0.1)
        pyautogui.dragTo(tx, ty, duration=0.5, button="left")
        time.sleep(0.35)

    if label:
        pyautogui.doubleClick(tx, ty)
        time.sleep(0.35)
        pyautogui.hotkey("command", "a")
        _paste(label)
        _esc()

    _esc()
    return {
        "status": "ok",
        "shape": shape,
        "label": label,
        "canvas_position": {"x": canvas_x, "y": canvas_y},
        "screen_position": {"x": tx, "y": ty},
        "size": {"width": width, "height": height},
        "menu_ok": ok,
    }


# ============================================================
# CONNECTOR / LINE TOOLS
# ============================================================

@mcp.tool()
def connector_add(
    from_x: int, from_y: int,
    to_x: int,   to_y: int,
    label: str = "",
) -> dict:
    """
    Draw a connector line on the CURRENT board (does not create a new board).

    from_x, from_y : start point (canvas coords, relative to centre)
    to_x,   to_y   : end point   (canvas coords, relative to centre)
    label          : optional text label on the connector
    """
    # IMPORTANT: only activate, never open a new board
    _activate_freeform()

    ok = _click_menu("Insert", "Line")
    time.sleep(0.5)

    fx, fy = _canvas_to_screen(from_x, from_y)
    tx, ty = _canvas_to_screen(to_x, to_y)

    pyautogui.moveTo(fx, fy, duration=0.2)
    time.sleep(0.05)
    pyautogui.dragTo(tx, ty, duration=0.6, button="left")
    time.sleep(0.4)

    if label:
        mx, my = (fx + tx) // 2, (fy + ty) // 2
        pyautogui.doubleClick(mx, my)
        time.sleep(0.3)
        _paste(label)
        _esc()

    _esc()
    return {
        "status": "ok",
        "from": {"x": from_x, "y": from_y},
        "to":   {"x": to_x,   "y": to_y},
        "label": label,
        "menu_ok": ok,
    }


# ============================================================
# TEXT TOOLS
# ============================================================

@mcp.tool()
def text_add(
    text: str,
    canvas_x: int = 0,
    canvas_y: int = 0,
    bold: bool = False,
    italic: bool = False,
) -> dict:
    """
    Add a text box to the CURRENT board (does not create a new board).
    canvas_x, canvas_y: offset from board centre (px).
    """
    _activate_freeform()
    ok = _click_menu("Insert", "Text Box")
    time.sleep(0.5)

    sx, sy = _canvas_to_screen(canvas_x, canvas_y)
    pyautogui.click(sx, sy)
    time.sleep(0.3)

    if bold:
        pyautogui.hotkey("command", "b")
    if italic:
        pyautogui.hotkey("command", "i")

    _paste(text)
    _esc()
    _esc()
    return {"status": "ok", "text": text,
            "canvas_position": {"x": canvas_x, "y": canvas_y}, "menu_ok": ok}


# ============================================================
# STICKY NOTE TOOLS
# ============================================================

@mcp.tool()
def sticky_add(text: str, canvas_x: int = 0, canvas_y: int = 0) -> dict:
    """
    Add a sticky note to the CURRENT board (does not create a new board).
    canvas_x, canvas_y: offset from board centre (px).
    """
    _activate_freeform()
    ok = _click_menu("Insert", "Sticky Note")
    time.sleep(0.6)

    b = _window_bounds()
    cx = b["x"] + b["width"] // 2
    cy = b["y"] + 80 + (b["height"] - 80) // 2
    tx, ty = _canvas_to_screen(canvas_x, canvas_y)

    pyautogui.moveTo(cx, cy, duration=0.2)
    time.sleep(0.05)
    pyautogui.dragTo(tx, ty, duration=0.5, button="left")
    time.sleep(0.3)

    pyautogui.doubleClick(tx, ty)
    time.sleep(0.3)
    _paste(text)
    _esc()
    _esc()
    return {"status": "ok", "text": text,
            "canvas_position": {"x": canvas_x, "y": canvas_y}, "menu_ok": ok}


# ============================================================
# SELECTION AND OBJECT MANIPULATION
# ============================================================

@mcp.tool()
def select_all() -> dict:
    """Select all objects on the board (Cmd+A)."""
    _activate_freeform()
    pyautogui.hotkey("command", "a")
    time.sleep(0.2)
    return {"status": "ok"}


@mcp.tool()
def select_at(canvas_x: int, canvas_y: int) -> dict:
    """Click to select an object at a canvas position."""
    _activate_freeform()
    sx, sy = _canvas_to_screen(canvas_x, canvas_y)
    pyautogui.click(sx, sy)
    time.sleep(0.2)
    return {"status": "ok", "clicked": {"x": canvas_x, "y": canvas_y},
            "screen": {"x": sx, "y": sy}}


@mcp.tool()
def select_deselect() -> dict:
    """Deselect everything (Escape)."""
    _activate_freeform()
    _esc()
    return {"status": "ok"}


@mcp.tool()
def object_delete() -> dict:
    """Delete the currently selected object(s)."""
    _activate_freeform()
    pyautogui.press("delete")
    time.sleep(0.2)
    return {"status": "ok"}


@mcp.tool()
def object_duplicate() -> dict:
    """Duplicate selected object(s) (Cmd+D)."""
    _activate_freeform()
    pyautogui.hotkey("command", "d")
    time.sleep(0.3)
    return {"status": "ok"}


@mcp.tool()
def object_move(delta_x: int, delta_y: int) -> dict:
    """
    Move selected object(s) by pixel offset.
    delta_x: positive=right, negative=left.
    delta_y: positive=down,  negative=up.
    """
    _activate_freeform()

    def _axis(amount, pos_key, neg_key):
        key = pos_key if amount > 0 else neg_key
        n = abs(amount)
        for _ in range(n // 10):
            pyautogui.hotkey("shift", key)
        for _ in range(n % 10):
            pyautogui.press(key)

    _axis(delta_x, "right", "left")
    _axis(delta_y, "down", "up")
    time.sleep(0.2)
    return {"status": "ok", "moved": {"dx": delta_x, "dy": delta_y}}


@mcp.tool()
def object_group() -> dict:
    """Group selected objects (Cmd+G)."""
    _activate_freeform()
    pyautogui.hotkey("command", "g")
    time.sleep(0.3)
    return {"status": "ok"}


@mcp.tool()
def object_ungroup() -> dict:
    """Ungroup a selected group (Cmd+Shift+G)."""
    _activate_freeform()
    pyautogui.hotkey("command", "shift", "g")
    time.sleep(0.3)
    return {"status": "ok"}


# ============================================================
# ARRANGE AND ALIGN
# ============================================================

@mcp.tool()
def arrange(action: str) -> dict:
    """
    Arrange or align selected objects.
    action: align_left, align_right, align_top, align_bottom,
            center_h, center_v, distribute_h, distribute_v,
            bring_front, bring_forward, send_back, send_backward,
            group, ungroup
    """
    _activate_freeform()
    actions = {
        "align_left":    ("Arrange", "Align Objects", "Align Left Edges"),
        "align_right":   ("Arrange", "Align Objects", "Align Right Edges"),
        "align_top":     ("Arrange", "Align Objects", "Align Top Edges"),
        "align_bottom":  ("Arrange", "Align Objects", "Align Bottom Edges"),
        "center_h":      ("Arrange", "Align Objects", "Center Horizontally"),
        "center_v":      ("Arrange", "Align Objects", "Center Vertically"),
        "distribute_h":  ("Arrange", "Distribute Objects", "Distribute Horizontally"),
        "distribute_v":  ("Arrange", "Distribute Objects", "Distribute Vertically"),
        "bring_front":   ("Arrange", "Bring to Front"),
        "bring_forward": ("Arrange", "Bring Forward"),
        "send_back":     ("Arrange", "Send to Back"),
        "send_backward": ("Arrange", "Send Backward"),
        "group":         ("Arrange", "Group"),
        "ungroup":       ("Arrange", "Ungroup"),
    }
    if action not in actions:
        return {"status": "error", "message": f"Choose from: {list(actions)}"}
    ok = _click_menu(*actions[action])
    return {"status": "ok" if ok else "error", "action": action}


# ============================================================
# IMAGE INSERTION
# ============================================================

@mcp.tool()
def image_insert(file_path: str, canvas_x: int = 0, canvas_y: int = 0) -> dict:
    """
    Insert a PNG, JPG, or GIF onto the current board.
    file_path: absolute path. canvas_x/y: position relative to board centre.
    """
    _activate_freeform()
    p = Path(file_path).expanduser()
    if not p.exists():
        return {"status": "error", "message": f"File not found: {file_path}"}

    _click_menu("Insert", "Image", "Choose...")
    time.sleep(1.5)

    pyautogui.hotkey("command", "shift", "g")
    time.sleep(0.5)
    pyautogui.typewrite(str(p.parent), interval=0.03)
    pyautogui.press("return")
    time.sleep(0.5)
    pyautogui.typewrite(p.name, interval=0.03)
    pyautogui.press("return")
    time.sleep(1.0)

    b = _window_bounds()
    cx = b["x"] + b["width"] // 2
    cy = b["y"] + 80 + (b["height"] - 80) // 2
    tx, ty = _canvas_to_screen(canvas_x, canvas_y)
    pyautogui.moveTo(cx, cy, duration=0.2)
    pyautogui.dragTo(tx, ty, duration=0.5, button="left")
    time.sleep(0.3)
    _esc()
    return {"status": "ok", "image": p.name,
            "canvas_position": {"x": canvas_x, "y": canvas_y}}


# ============================================================
# FREEHAND DRAWING
# ============================================================

@mcp.tool()
def draw_freehand(points: list) -> dict:
    """
    Draw a freehand pen stroke on the current board.
    points: list of {"x": int, "y": int} dicts.
    """
    _activate_freeform()
    if len(points) < 2:
        return {"status": "error", "message": "Need at least 2 points."}

    _click_menu("Insert", "Pencil Drawing")
    time.sleep(0.5)

    pts = [_canvas_to_screen(p["x"], p["y"]) for p in points]
    pyautogui.moveTo(pts[0][0], pts[0][1], duration=0.2)
    pyautogui.mouseDown()
    for px, py in pts[1:]:
        pyautogui.moveTo(px, py, duration=0.08)
    pyautogui.mouseUp()
    time.sleep(0.3)
    _esc()
    return {"status": "ok", "points_drawn": len(points)}


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "dev":
        mcp.run()
    else:
        mcp.run(transport="stdio")
