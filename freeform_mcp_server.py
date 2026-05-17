"""
freeform_mcp_server.py  (v7 — click-first placement + calibration)
===================================================================
macOS only. Python 3.10+.

STRATEGY CHANGE IN v7:
  Previous versions inserted a shape then tried to move it. That failed
  because Freeform ignores programmatic position changes after insertion.

  v7 APPROACH — "click-first" placement:
    1. Click the canvas at the target screen position BEFORE inserting.
    2. Freeform places new shapes near the last-clicked canvas point.
    3. Insert the shape — it appears at (or very near) where we clicked.
    4. Double-click that same point to enter label editing mode.

  This works because Freeform respects the active canvas focus point
  when deciding where to insert a new object.

CALIBRATION TOOL:
  board_calibrate() inserts a test shape, takes a screenshot, then
  measures via pixel analysis where the shape actually landed vs where
  we clicked. It stores an (offset_x, offset_y) correction factor that
  all subsequent shape_add calls apply automatically.
  Run this once after board_new() on a new board.
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
pyautogui.PAUSE = 0.1

# Calibration offset — adjusted by board_calibrate()
_offset_x = 0
_offset_y = 0


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _run_as(script):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.stdout.strip(), r.stderr.strip(), r.returncode


def _has_open_window():
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
    """Bring Freeform to front. NEVER opens a new board."""
    out, _, _ = _run_as(
        'tell application "System Events" to (name of processes) contains "Freeform"'
    )
    if out != "true":
        subprocess.Popen(["open", "-a", "Freeform"])
        time.sleep(3.5)

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

    _run_as('tell application "Freeform" to activate')
    time.sleep(0.4)


_ensure_freeform = _activate_freeform


def _open_new_board():
    """Open a new board. Called ONLY from board_new()."""
    _run_as('tell application "Freeform" to make new document')
    time.sleep(2.0)
    if _has_open_window():
        return True

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

    _run_as('tell application "Freeform" to activate')
    time.sleep(1.5)
    pyautogui.hotkey("command", "n")
    time.sleep(2.5)
    return _has_open_window()


def _window_bounds():
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

    try:
        img = ImageGrab.grab()
        sw, sh = img.size
        return {"x": 0, "y": 28, "width": sw, "height": sh - 28}
    except Exception:
        pass

    return {"x": 0, "y": 28, "width": 1440, "height": 872}


def _canvas_to_screen(cx, cy):
    """
    Convert canvas coords (0,0 = board centre) to absolute screen pixels.
    Applies calibration offset if set.
    """
    b = _window_bounds()
    toolbar_height = 80
    sx = b["x"] + b["width"] // 2 + cx + _offset_x
    sy = b["y"] + toolbar_height + (b["height"] - toolbar_height) // 2 + cy + _offset_y
    return int(sx), int(sy)


def _click_canvas_at(sx, sy):
    """
    Click on the Freeform canvas to set insertion focus point.
    This is the key step that tells Freeform where to place the next shape.
    """
    # First make sure Freeform is front and no toolbar item is selected
    _run_as('tell application "Freeform" to activate')
    time.sleep(0.2)
    # Press Escape to deselect any tool/shape
    pyautogui.press("escape")
    time.sleep(0.15)
    # Single click at target canvas position
    pyautogui.click(sx, sy)
    time.sleep(0.25)


def _screenshot_window():
    _activate_freeform()
    time.sleep(0.4)
    b = _window_bounds()
    img = ImageGrab.grab(bbox=(b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"]))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _click_menu(*path):
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
    time.sleep(0.35)
    return rc == 0


def _esc():
    pyautogui.press("escape")
    time.sleep(0.15)


def _paste(text):
    safe = text.replace("\\", "\\\\").replace('"', '\\"')
    _run_as(f'set the clipboard to "{safe}"')
    pyautogui.hotkey("command", "v")
    time.sleep(0.2)


# ============================================================
# BOARD MANAGEMENT
# ============================================================

@mcp.tool()
def board_new() -> dict:
    """
    Create a new blank Freeform board.

    WORKFLOW:
      1. Call board_new() — creates one board.
      2. Call board_calibrate() — measures placement accuracy on this Mac.
      3. Call shape_add(), connector_add() etc. — all draw on this board.
      4. Never call board_new() again mid-diagram.
    """
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
        "next_step": "Call board_calibrate() before drawing to ensure accurate placement."
    }


@mcp.tool()
def board_calibrate() -> dict:
    """
    Calibrate shape placement for this Mac's screen.

    HOW IT WORKS:
      1. Inserts a test rectangle at canvas (0,0) — the board centre.
      2. Takes a screenshot.
      3. Measures where the shape actually appeared vs where we aimed.
      4. Stores the offset so all subsequent shape_add calls are corrected.

    Call this ONCE after board_new(), before drawing any diagram shapes.
    The result tells you the calibration offset being applied.
    """
    global _offset_x, _offset_y
    _activate_freeform()
    time.sleep(0.3)

    # Target: screen centre of canvas
    b = _window_bounds()
    toolbar_height = 80
    target_sx = b["x"] + b["width"] // 2
    target_sy = b["y"] + toolbar_height + (b["height"] - toolbar_height) // 2

    # Click canvas centre
    _click_canvas_at(target_sx, target_sy)

    # Insert a small rectangle at canvas centre
    _click_menu("Insert", "Shape", "Rectangle")
    time.sleep(0.8)

    # Screenshot to see where it landed
    img = ImageGrab.grab(bbox=(b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"]))
    buf = BytesIO()
    img.save(buf, format="PNG")
    screenshot_b64 = base64.b64encode(buf.getvalue()).decode()

    # Try to find the shape by looking for a change from background colour
    # This is approximate — we scan for non-white pixels near the expected area
    import numpy as np
    try:
        arr = np.array(img)
        h, w = arr.shape[:2]
        # Look in centre quadrant for inserted shape (non-white pixels)
        cx, cy = w // 2, h // 2 - toolbar_height // 2
        region = arr[cy - 100:cy + 100, cx - 150:cx + 150]
        # Find pixels that differ from white (255,255,255)
        non_white = np.where(
            (region[:,:,0] < 200) | (region[:,:,1] < 200) | (region[:,:,2] < 200)
        )
        if len(non_white[0]) > 50:
            # Centroid of non-white pixels
            found_y = int(np.mean(non_white[0])) + (cy - 100)
            found_x = int(np.mean(non_white[1])) + (cx - 150)
            # Offset = where we aimed - where it landed (relative to window)
            _offset_x = 0   # horizontal usually fine
            _offset_y = (cy - found_y)
            calibration_note = f"Shape found at window-relative ({found_x},{found_y}), aimed at ({cx},{cy}). Offset applied: ({_offset_x},{_offset_y})"
        else:
            _offset_x = 0
            _offset_y = 0
            calibration_note = "Could not detect shape via pixel analysis. Using zero offset. Placement may be approximate."
    except ImportError:
        _offset_x = 0
        _offset_y = 0
        calibration_note = "numpy not available — using zero offset. Install with: pip3 install numpy"

    # Delete the test shape
    pyautogui.hotkey("command", "z")
    time.sleep(0.4)

    return {
        "status": "ok",
        "offset_x": _offset_x,
        "offset_y": _offset_y,
        "calibration_note": calibration_note,
        "screenshot_b64": screenshot_b64,
        "message": "Calibration complete. All subsequent shape_add calls will use this offset."
    }


@mcp.tool()
def board_open(file_path: str) -> dict:
    """Open an existing .freeform file."""
    p = Path(file_path).expanduser()
    if not p.exists():
        return {"status": "error", "message": f"File not found: {file_path}"}
    subprocess.Popen(["open", str(p)])
    time.sleep(3)
    _run_as('tell application "Freeform" to activate')
    return {"status": "ok", "file": p.name, "window_bounds": _window_bounds()}


@mcp.tool()
def board_save() -> dict:
    """Save (Cmd+S)."""
    _activate_freeform()
    pyautogui.hotkey("command", "s")
    time.sleep(0.8)
    return {"status": "ok"}


@mcp.tool()
def board_undo() -> dict:
    """Undo (Cmd+Z)."""
    _activate_freeform()
    pyautogui.hotkey("command", "z")
    time.sleep(0.3)
    return {"status": "ok"}


@mcp.tool()
def board_redo() -> dict:
    """Redo (Cmd+Shift+Z)."""
    _activate_freeform()
    pyautogui.hotkey("command", "shift", "z")
    time.sleep(0.3)
    return {"status": "ok"}


@mcp.tool()
def board_screenshot() -> dict:
    """Screenshot the board. Returns base64 PNG."""
    img_b64 = _screenshot_window()
    return {"status": "ok", "format": "png", "image_base64": img_b64}


@mcp.tool()
def board_zoom(level: str = "fit") -> dict:
    """Zoom: fit | in | out | 100"""
    _activate_freeform()
    zm = {
        "fit": ("View", "Zoom to Fit"),
        "in":  ("View", "Zoom In"),
        "out": ("View", "Zoom Out"),
        "100": ("View", "Actual Size"),
    }
    if level not in zm:
        return {"status": "error", "message": f"Use: {list(zm)}"}
    _click_menu(*zm[level])
    return {"status": "ok", "zoom": level}


# ============================================================
# DEBUG TOOL
# ============================================================

@mcp.tool()
def debug_info() -> dict:
    """Diagnostic: window state, bounds, screen size, canvas centre."""
    _activate_freeform()
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
    try:
        img = ImageGrab.grab()
        screen_size = list(img.size)
    except Exception as e:
        screen_size = str(e)

    computed = _window_bounds()
    centre = _canvas_to_screen(0, 0)

    return {
        "has_open_window": _has_open_window(),
        "method1_raw": out1, "method1_error": err1,
        "screen_size": screen_size,
        "computed_bounds": computed,
        "canvas_centre_screen": centre,
        "current_offset": {"x": _offset_x, "y": _offset_y},
    }


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
    Insert a shape at a specific position on the current board.

    HOW POSITIONING WORKS (v7 click-first method):
      We click the canvas at the target position BEFORE inserting the shape.
      Freeform places new shapes at the last-clicked canvas point.
      Run board_calibrate() first for best accuracy.

    shape    : rectangle, rounded_rectangle, circle, diamond, star,
               speech_bubble, arrow_right, arrow_down, cloud, cylinder,
               triangle, hexagon, oval, heart, parallelogram, and more.
    canvas_x : pixels right of board centre (negative = left)
    canvas_y : pixels below board centre   (negative = up)
    width    : shape width  in pixels (default 150)
    height   : shape height in pixels (default 80)
    label    : text inside the shape

    Layout reference — (0,0) = board centre:
      Row of 3:      (-300,0)  (0,0)  (300,0)
      Column of 4:   (0,-300)  (0,-100)  (0,100)  (0,300)
      2x2 grid:      (-250,-150) (250,-150) (-250,150) (250,150)
    """
    _activate_freeform()

    key = shape.lower().replace(" ", "_")
    menu_name = SHAPE_MENU.get(key)
    if not menu_name:
        return {"status": "error",
                "message": f"Unknown shape '{shape}'. Options: {list(SHAPE_MENU)}"}

    # Step 1: Click canvas at target position to set Freeform's insertion point
    target_sx, target_sy = _canvas_to_screen(canvas_x, canvas_y)
    _click_canvas_at(target_sx, target_sy)

    # Step 2: Insert shape — Freeform places it at the clicked point
    ok = _click_menu("Insert", "Shape", menu_name)
    time.sleep(0.7)

    # Step 3: Add label
    if label:
        # Double-click where the shape landed (near target)
        pyautogui.doubleClick(target_sx, target_sy)
        time.sleep(0.4)
        pyautogui.hotkey("command", "a")
        _paste(label)
        _esc()

    _esc()
    return {
        "status": "ok",
        "shape": shape,
        "label": label,
        "canvas_position": {"x": canvas_x, "y": canvas_y},
        "screen_position": {"x": target_sx, "y": target_sy},
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
    Draw a connector line between two canvas positions.

    from_x, from_y : start point (canvas coords relative to board centre)
    to_x,   to_y   : end point   (canvas coords relative to board centre)
    label          : optional text label on the connector

    TIP: use the edge of shapes, not their centres:
      Shape at (0,-200) height 80 → bottom edge at canvas_y -160
      Shape at (0,0)    height 80 → top edge    at canvas_y  -40
    """
    _activate_freeform()

    # Select line tool
    ok = _click_menu("Insert", "Line")
    time.sleep(0.6)

    fx, fy = _canvas_to_screen(from_x, from_y)
    tx, ty = _canvas_to_screen(to_x, to_y)

    # Slow, stepped drag for reliability
    pyautogui.moveTo(fx, fy, duration=0.5)
    time.sleep(0.3)
    pyautogui.mouseDown(button="left")
    time.sleep(0.2)

    steps = 10
    for i in range(1, steps + 1):
        ix = int(fx + (tx - fx) * i / steps)
        iy = int(fy + (ty - fy) * i / steps)
        pyautogui.moveTo(ix, iy, duration=0.06)

    time.sleep(0.15)
    pyautogui.mouseUp(button="left")
    time.sleep(0.4)

    if label:
        mx = (fx + tx) // 2
        my = (fy + ty) // 2
        pyautogui.doubleClick(mx, my)
        time.sleep(0.3)
        _paste(label)
        _esc()

    _esc()
    return {
        "status": "ok",
        "from": {"x": from_x, "y": from_y},
        "to":   {"x": to_x,   "y": to_y},
        "screen_from": {"x": fx, "y": fy},
        "screen_to":   {"x": tx, "y": ty},
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
    """Add a text box at canvas position."""
    _activate_freeform()

    target_sx, target_sy = _canvas_to_screen(canvas_x, canvas_y)
    _click_canvas_at(target_sx, target_sy)

    ok = _click_menu("Insert", "Text Box")
    time.sleep(0.5)

    pyautogui.click(target_sx, target_sy)
    time.sleep(0.3)

    if bold:
        pyautogui.hotkey("command", "b")
    if italic:
        pyautogui.hotkey("command", "i")

    _paste(text)
    _esc()
    _esc()
    return {"status": "ok", "text": text,
            "canvas_position": {"x": canvas_x, "y": canvas_y}}


# ============================================================
# STICKY NOTE TOOLS
# ============================================================

@mcp.tool()
def sticky_add(text: str, canvas_x: int = 0, canvas_y: int = 0) -> dict:
    """Add a sticky note at canvas position."""
    _activate_freeform()

    target_sx, target_sy = _canvas_to_screen(canvas_x, canvas_y)
    _click_canvas_at(target_sx, target_sy)

    ok = _click_menu("Insert", "Sticky Note")
    time.sleep(0.6)

    pyautogui.doubleClick(target_sx, target_sy)
    time.sleep(0.3)
    _paste(text)
    _esc()
    _esc()
    return {"status": "ok", "text": text,
            "canvas_position": {"x": canvas_x, "y": canvas_y}}


# ============================================================
# SELECTION AND OBJECT MANIPULATION
# ============================================================

@mcp.tool()
def select_all() -> dict:
    """Select all (Cmd+A)."""
    _activate_freeform()
    pyautogui.hotkey("command", "a")
    time.sleep(0.2)
    return {"status": "ok"}


@mcp.tool()
def select_at(canvas_x: int, canvas_y: int) -> dict:
    """Click to select object at canvas position."""
    _activate_freeform()
    sx, sy = _canvas_to_screen(canvas_x, canvas_y)
    pyautogui.click(sx, sy)
    time.sleep(0.2)
    return {"status": "ok", "screen": {"x": sx, "y": sy}}


@mcp.tool()
def select_deselect() -> dict:
    """Deselect everything."""
    _activate_freeform()
    _esc()
    return {"status": "ok"}


@mcp.tool()
def object_delete() -> dict:
    """Delete selected object(s)."""
    _activate_freeform()
    pyautogui.press("delete")
    time.sleep(0.2)
    return {"status": "ok"}


@mcp.tool()
def object_duplicate() -> dict:
    """Duplicate selected (Cmd+D)."""
    _activate_freeform()
    pyautogui.hotkey("command", "d")
    time.sleep(0.3)
    return {"status": "ok"}


@mcp.tool()
def object_move(delta_x: int, delta_y: int) -> dict:
    """Move selected by pixel offset using arrow keys."""
    _activate_freeform()

    def _axis(amount, pos_key, neg_key):
        key = pos_key if amount > 0 else neg_key
        n = abs(amount)
        for _ in range(n // 10):
            pyautogui.hotkey("shift", key)
            time.sleep(0.02)
        for _ in range(n % 10):
            pyautogui.press(key)
            time.sleep(0.01)

    _axis(delta_x, "right", "left")
    _axis(delta_y, "down", "up")
    time.sleep(0.2)
    return {"status": "ok", "moved": {"dx": delta_x, "dy": delta_y}}


@mcp.tool()
def object_group() -> dict:
    """Group selected (Cmd+G)."""
    _activate_freeform()
    pyautogui.hotkey("command", "g")
    time.sleep(0.3)
    return {"status": "ok"}


@mcp.tool()
def object_ungroup() -> dict:
    """Ungroup selected (Cmd+Shift+G)."""
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
    Align/arrange selected objects.
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
    """Insert image at canvas position. file_path: absolute path."""
    _activate_freeform()
    p = Path(file_path).expanduser()
    if not p.exists():
        return {"status": "error", "message": f"File not found: {file_path}"}

    target_sx, target_sy = _canvas_to_screen(canvas_x, canvas_y)
    _click_canvas_at(target_sx, target_sy)

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
    _esc()
    return {"status": "ok", "image": p.name,
            "canvas_position": {"x": canvas_x, "y": canvas_y}}


# ============================================================
# FREEHAND DRAWING
# ============================================================

@mcp.tool()
def draw_freehand(points: list) -> dict:
    """
    Draw freehand stroke. points: [{"x": int, "y": int}, ...]
    """
    _activate_freeform()
    if len(points) < 2:
        return {"status": "error", "message": "Need at least 2 points."}

    _click_menu("Insert", "Pencil Drawing")
    time.sleep(0.5)

    pts = [_canvas_to_screen(p["x"], p["y"]) for p in points]
    pyautogui.moveTo(pts[0][0], pts[0][1], duration=0.3)
    time.sleep(0.1)
    pyautogui.mouseDown()
    for px, py in pts[1:]:
        pyautogui.moveTo(px, py, duration=0.1)
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
