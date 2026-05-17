"""
freeform_mcp_server.py
======================
MCP server connecting Claude AI to Apple Freeform.
Lets Claude draw shapes, connectors, sticky notes, text boxes,
arrange objects, and read/screenshot boards.

macOS only. Python 3.10+.
"""

import base64
import os
import subprocess
import time
from io import BytesIO
from pathlib import Path

import pyautogui
from mcp.server.fastmcp import FastMCP
from PIL import ImageGrab

# -- Server setup --
mcp = FastMCP("Freeform MCP")
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.15


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _run_as(script):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.stdout.strip()


def _ensure_freeform():
    running = _run_as(
        'tell application "System Events" to (name of processes) contains "Freeform"'
    )
    if running != "true":
        subprocess.Popen(["open", "-a", "Freeform"])
        time.sleep(3)
    _run_as('tell application "Freeform" to activate')
    time.sleep(0.4)


def _window_bounds():
    script = """
    tell application "System Events"
        tell process "Freeform"
            set w to front window
            set p to position of w
            set s to size of w
            return (item 1 of p) & "," & (item 2 of p) & "," & (item 1 of s) & "," & (item 2 of s)
        end tell
    end tell
    """
    raw = _run_as(script)
    parts = [int(v.strip()) for v in raw.split(",")]
    return {"x": parts[0], "y": parts[1], "width": parts[2], "height": parts[3]}


def _canvas_to_screen(cx, cy):
    b = _window_bounds()
    sx = b["x"] + b["width"] // 2 + cx
    sy = b["y"] + 50 + b["height"] // 2 + cy
    return int(sx), int(sy)


def _screenshot_window():
    _ensure_freeform()
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
        end tell
        """
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
        end tell
        """
    else:
        return False
    r = subprocess.run(["osascript", "-e", script], capture_output=True)
    time.sleep(0.4)
    return r.returncode == 0


def _esc():
    pyautogui.press("escape")
    time.sleep(0.15)


def _paste_text(text):
    script = 'set the clipboard to "' + text.replace('"', '\\"') + '"'
    subprocess.run(["osascript", "-e", script])
    pyautogui.hotkey("command", "v")
    time.sleep(0.2)


# ============================================================
# BOARD MANAGEMENT
# ============================================================

@mcp.tool()
def board_new() -> dict:
    """
    Open Freeform and create a brand-new blank board.
    ALWAYS call this first before drawing anything on a new diagram.
    Returns the window bounds so you know the canvas size.
    """
    _ensure_freeform()
    _click_menu("File", "New Board")
    time.sleep(1.0)
    return {"status": "ok", "window_bounds": _window_bounds()}


@mcp.tool()
def board_open(file_path: str) -> dict:
    """
    Open an existing .freeform file from disk.
    file_path: absolute path, e.g. /Users/you/Documents/MyDiagram.freeform
    After opening, use board_screenshot() to see what is on it.
    """
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
    _ensure_freeform()
    pyautogui.hotkey("command", "s")
    time.sleep(0.8)
    return {"status": "ok"}


@mcp.tool()
def board_undo() -> dict:
    """Undo the last action (Cmd+Z)."""
    _ensure_freeform()
    pyautogui.hotkey("command", "z")
    time.sleep(0.3)
    return {"status": "ok"}


@mcp.tool()
def board_redo() -> dict:
    """Redo the last undone action (Cmd+Shift+Z)."""
    _ensure_freeform()
    pyautogui.hotkey("command", "shift", "z")
    time.sleep(0.3)
    return {"status": "ok"}


@mcp.tool()
def board_screenshot() -> dict:
    """
    Take a screenshot of the current Freeform board and return it as a
    base64-encoded PNG image. Use this to READ what is on the board.
    Claude can analyse the image to understand the diagram layout.
    """
    img_b64 = _screenshot_window()
    return {
        "status": "ok",
        "format": "png",
        "image_base64": img_b64,
        "note": "Pass image_base64 to Claude vision to read the board contents."
    }


@mcp.tool()
def board_zoom(level: str = "fit") -> dict:
    """
    Zoom the canvas.
    level: fit (zoom to fit all), in (zoom in), out (zoom out), 100 (actual size)
    """
    _ensure_freeform()
    zoom_map = {
        "fit": ("View", "Zoom to Fit"),
        "in":  ("View", "Zoom In"),
        "out": ("View", "Zoom Out"),
        "100": ("View", "Actual Size"),
    }
    if level not in zoom_map:
        return {"status": "error", "message": f"level must be one of: {list(zoom_map)}"}
    _click_menu(*zoom_map[level])
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
    height: int = 100,
    label: str = "",
) -> dict:
    """
    Insert a shape onto the board.

    shape      : rectangle, rounded_rectangle, circle, oval, triangle,
                 right_triangle, diamond, pentagon, hexagon, octagon,
                 star, heart, speech_bubble, thought_bubble,
                 parallelogram, trapezoid, cylinder, cloud, cross,
                 bracket, brace, arrow_right, arrow_left, arrow_up,
                 arrow_down, double_arrow
    canvas_x   : horizontal position relative to board centre in pixels.
                 Negative = left, positive = right.
    canvas_y   : vertical position relative to board centre in pixels.
                 Negative = up, positive = down.
    width      : shape width in pixels  (default 150)
    height     : shape height in pixels (default 100)
    label      : text label inside the shape (optional)

    Layout tip: treat (0,0) as board centre.
    Three boxes left to right: (-300,0), (0,0), (300,0).
    """
    _ensure_freeform()
    key = shape.lower().replace(" ", "_")
    menu_name = SHAPE_MENU.get(key)
    if not menu_name:
        return {"status": "error", "message": f"Unknown shape '{shape}'. Available: {list(SHAPE_MENU)}"}

    _click_menu("Insert", "Shape", menu_name)
    time.sleep(0.6)

    b = _window_bounds()
    cx = b["x"] + b["width"] // 2
    cy = b["y"] + 50 + b["height"] // 2
    tx, ty = _canvas_to_screen(canvas_x, canvas_y)

    if (tx, ty) != (cx, cy):
        pyautogui.moveTo(cx, cy, duration=0.2)
        pyautogui.dragTo(tx, ty, duration=0.5, button="left")
        time.sleep(0.3)

    if label:
        pyautogui.doubleClick(tx, ty)
        time.sleep(0.3)
        pyautogui.hotkey("command", "a")
        _paste_text(label)
        _esc()

    _esc()
    return {
        "status": "ok",
        "shape": shape,
        "label": label,
        "canvas_position": {"x": canvas_x, "y": canvas_y},
        "size": {"width": width, "height": height},
    }


# ============================================================
# CONNECTOR / LINE TOOLS
# ============================================================

@mcp.tool()
def connector_add(
    from_x: int,
    from_y: int,
    to_x: int,
    to_y: int,
    label: str = "",
) -> dict:
    """
    Draw a connector line between two canvas positions.
    Use this to link shapes in flowcharts and diagrams.

    from_x, from_y : start point (canvas coords relative to centre)
    to_x,   to_y   : end point   (canvas coords relative to centre)
    label          : optional text label on the connector
    """
    _ensure_freeform()
    _click_menu("Insert", "Line")
    time.sleep(0.5)

    fx, fy = _canvas_to_screen(from_x, from_y)
    tx, ty = _canvas_to_screen(to_x, to_y)

    pyautogui.moveTo(fx, fy, duration=0.2)
    pyautogui.dragTo(tx, ty, duration=0.6, button="left")
    time.sleep(0.4)

    if label:
        mx = (fx + tx) // 2
        my = (fy + ty) // 2
        pyautogui.doubleClick(mx, my)
        time.sleep(0.3)
        _paste_text(label)
        _esc()

    _esc()
    return {
        "status": "ok",
        "from": {"x": from_x, "y": from_y},
        "to":   {"x": to_x,   "y": to_y},
        "label": label,
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
    Add a free-floating text box to the board.

    text     : the text to display
    canvas_x : horizontal position relative to board centre
    canvas_y : vertical position relative to board centre
    bold     : make text bold
    italic   : make text italic
    """
    _ensure_freeform()
    _click_menu("Insert", "Text Box")
    time.sleep(0.5)

    sx, sy = _canvas_to_screen(canvas_x, canvas_y)
    pyautogui.click(sx, sy)
    time.sleep(0.3)

    if bold:
        pyautogui.hotkey("command", "b")
    if italic:
        pyautogui.hotkey("command", "i")

    _paste_text(text)
    _esc()
    _esc()
    return {
        "status": "ok",
        "text": text,
        "canvas_position": {"x": canvas_x, "y": canvas_y},
    }


# ============================================================
# STICKY NOTE TOOLS
# ============================================================

@mcp.tool()
def sticky_add(text: str, canvas_x: int = 0, canvas_y: int = 0) -> dict:
    """
    Add a sticky note to the board.

    text     : content of the sticky note
    canvas_x : horizontal position relative to board centre
    canvas_y : vertical position relative to board centre
    """
    _ensure_freeform()
    _click_menu("Insert", "Sticky Note")
    time.sleep(0.6)

    b = _window_bounds()
    cx = b["x"] + b["width"] // 2
    cy = b["y"] + 50 + b["height"] // 2
    tx, ty = _canvas_to_screen(canvas_x, canvas_y)

    pyautogui.moveTo(cx, cy, duration=0.2)
    pyautogui.dragTo(tx, ty, duration=0.5, button="left")
    time.sleep(0.3)

    pyautogui.doubleClick(tx, ty)
    time.sleep(0.3)
    _paste_text(text)
    _esc()
    _esc()
    return {
        "status": "ok",
        "text": text,
        "canvas_position": {"x": canvas_x, "y": canvas_y},
    }


# ============================================================
# SELECTION AND OBJECT MANIPULATION
# ============================================================

@mcp.tool()
def select_all() -> dict:
    """Select all objects on the board (Cmd+A)."""
    _ensure_freeform()
    pyautogui.hotkey("command", "a")
    time.sleep(0.2)
    return {"status": "ok"}


@mcp.tool()
def select_at(canvas_x: int, canvas_y: int) -> dict:
    """Click to select an object at the given canvas position."""
    _ensure_freeform()
    sx, sy = _canvas_to_screen(canvas_x, canvas_y)
    pyautogui.click(sx, sy)
    time.sleep(0.2)
    return {"status": "ok", "clicked": {"x": canvas_x, "y": canvas_y}}


@mcp.tool()
def select_deselect() -> dict:
    """Deselect everything (Escape)."""
    _ensure_freeform()
    _esc()
    return {"status": "ok"}


@mcp.tool()
def object_delete() -> dict:
    """Delete the currently selected object(s)."""
    _ensure_freeform()
    pyautogui.press("delete")
    time.sleep(0.2)
    return {"status": "ok"}


@mcp.tool()
def object_duplicate() -> dict:
    """Duplicate selected object(s) (Cmd+D)."""
    _ensure_freeform()
    pyautogui.hotkey("command", "d")
    time.sleep(0.3)
    return {"status": "ok"}


@mcp.tool()
def object_move(delta_x: int, delta_y: int) -> dict:
    """
    Move selected object(s) by a relative offset using arrow keys.
    delta_x: pixels right (negative = left)
    delta_y: pixels down  (negative = up)
    """
    _ensure_freeform()

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
    _ensure_freeform()
    pyautogui.hotkey("command", "g")
    time.sleep(0.3)
    return {"status": "ok"}


@mcp.tool()
def object_ungroup() -> dict:
    """Ungroup a selected group (Cmd+Shift+G)."""
    _ensure_freeform()
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

    action options:
      align_left, align_right, align_top, align_bottom,
      center_h (centre horizontally), center_v (centre vertically),
      distribute_h, distribute_v,
      bring_front, bring_forward, send_back, send_backward,
      group, ungroup
    """
    _ensure_freeform()
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
        return {"status": "error", "message": f"Unknown action. Choose from: {list(actions)}"}
    ok = _click_menu(*actions[action])
    return {"status": "ok" if ok else "error", "action": action}


# ============================================================
# IMAGE INSERTION
# ============================================================

@mcp.tool()
def image_insert(file_path: str, canvas_x: int = 0, canvas_y: int = 0) -> dict:
    """
    Insert a PNG, JPG, or GIF image file onto the board.
    file_path: absolute path to the image file.
    canvas_x, canvas_y: where to place it (relative to board centre).
    """
    _ensure_freeform()
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
    time.sleep(1)

    b = _window_bounds()
    cx = b["x"] + b["width"] // 2
    cy = b["y"] + 50 + b["height"] // 2
    tx, ty = _canvas_to_screen(canvas_x, canvas_y)
    pyautogui.moveTo(cx, cy, duration=0.2)
    pyautogui.dragTo(tx, ty, duration=0.5, button="left")
    time.sleep(0.3)
    _esc()
    return {"status": "ok", "image": p.name, "canvas_position": {"x": canvas_x, "y": canvas_y}}


# ============================================================
# FREEHAND DRAWING
# ============================================================

@mcp.tool()
def draw_freehand(points: list) -> dict:
    """
    Draw a freehand pen stroke through a series of canvas points.
    points: list of {"x": int, "y": int} dicts defining the path.
    Example: [{"x": -100, "y": 0}, {"x": 0, "y": -50}, {"x": 100, "y": 0}]
    """
    _ensure_freeform()
    if len(points) < 2:
        return {"status": "error", "message": "Need at least 2 points."}

    _click_menu("Insert", "Pencil Drawing")
    time.sleep(0.5)

    screen_pts = [_canvas_to_screen(p["x"], p["y"]) for p in points]
    sx, sy = screen_pts[0]
    pyautogui.moveTo(sx, sy, duration=0.2)
    pyautogui.mouseDown()
    for px, py in screen_pts[1:]:
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
