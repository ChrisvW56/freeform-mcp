# freeform-mcp

**MCP server that connects Claude AI to Apple Freeform** so Claude can draw diagrams, flowcharts, and mind maps for you — and read boards you have already created.

> macOS only. Works with Claude Desktop (the free app from Anthropic).

---

## What can Claude do with this?

Once installed, you can ask Claude things like:

- *"Draw me a flowchart of my software architecture"*
- *"Create a mind map of my project plan with sticky notes"*
- *"Read the diagram I built in Freeform and describe it"*
- *"Add a rectangle labelled 'Database' connected to a circle labelled 'API'"*

Claude will open Apple Freeform and draw it for you automatically.

---

## Before you start — what you need

1. A **Mac** running macOS 16 (Sequoia) or later with Apple Freeform installed (it is free, pre-installed on modern Macs)
2. **Claude Desktop** — download free from [claude.ai/download](https://claude.ai/download)
3. **Python 3.10 or later** — check by opening Terminal and typing `python3 --version`

If you do not have Python, download it from [python.org/downloads](https://www.python.org/downloads/) and run the installer.

---

## Installation — Step by Step

### Step 1 — Download this project

1. On this GitHub page, click the green **Code** button
2. Click **Download ZIP**
3. Find the downloaded ZIP in your Downloads folder and double-click it to unzip
4. You will get a folder called `freeform-mcp-main`

### Step 2 — Open Terminal

Press **Command + Space**, type **Terminal**, and press Enter. A black/white window will open.

### Step 3 — Navigate to the project folder

In Terminal, type the following and press Enter:

```
cd ~/Downloads/freeform-mcp-main
```

### Step 4 — Install the required Python packages

In Terminal, type this and press Enter. It will download and install everything needed (takes 1–3 minutes):

```
pip3 install -r requirements.txt
```

If you see a permission error, try:

```
pip3 install --user -r requirements.txt
```

### Step 5 — Grant macOS permissions

The server moves the mouse to control Freeform, so macOS needs to trust it.

1. Open **System Settings** → **Privacy & Security** → **Accessibility**
2. Click the **+** button and add **Terminal** (or your terminal app)
3. Go to **Privacy & Security** → **Screen Recording**
4. Add **Terminal** there too

### Step 6 — Connect to Claude Desktop

1. Open **Claude Desktop**
2. Click **Claude** in the menu bar → **Settings**
3. Click **Developer** → **Edit Config**
4. A file called `claude_desktop_config.json` will open in TextEdit
5. Replace everything in that file with the following (change the path to match where you saved the project):

```json
{
  "mcpServers": {
    "freeform": {
      "command": "python3",
      "args": ["/Users/YOURUSERNAME/Downloads/freeform-mcp-main/freeform_mcp_server.py"]
    }
  }
}
```

**Important:** Replace `YOURUSERNAME` with your actual Mac username. You can find it by typing `whoami` in Terminal.

6. Save the file (Command+S) and close TextEdit
7. **Quit Claude Desktop completely** (right-click the Dock icon → Quit)
8. Re-open Claude Desktop

### Step 7 — Test it!

In Claude Desktop, type:

> *"Open Freeform and draw me a simple flowchart with Start, Process, and End boxes connected by arrows"*

Claude will open Freeform and draw the diagram automatically!

---

## How to read an existing Freeform board

Open the board in Freeform first, then ask Claude:

> *"Take a screenshot of my Freeform board and tell me what's on it"*

Claude will capture the board and describe the diagram to you.

---

## Available Tools (what Claude can do)

| Tool | What it does |
|------|-------------|
| `board_new` | Open Freeform and create a new blank board |
| `board_open` | Open an existing .freeform file |
| `board_save` | Save the current board |
| `board_screenshot` | Take a screenshot so Claude can read the board |
| `board_zoom` | Zoom in, out, or fit all content |
| `board_undo` / `board_redo` | Undo or redo the last action |
| `shape_add` | Add a shape (rectangle, circle, diamond, star, arrow, and 20+ more) with an optional text label |
| `connector_add` | Draw a line/connector between two positions |
| `text_add` | Add a floating text box |
| `sticky_add` | Add a sticky note |
| `image_insert` | Insert a PNG/JPG image onto the board |
| `draw_freehand` | Draw a freehand pen stroke |
| `select_at` | Click to select an object at a position |
| `select_all` | Select all objects |
| `object_delete` | Delete selected object(s) |
| `object_duplicate` | Duplicate selected object(s) |
| `object_move` | Move selected object(s) by a pixel offset |
| `object_group` / `object_ungroup` | Group or ungroup objects |
| `arrange` | Align, distribute, or reorder objects |

---

## Troubleshooting

**Claude says "no MCP tools available"**
→ Make sure you quit and re-opened Claude Desktop after editing the config file.

**Freeform opens but nothing is drawn**
→ Make sure Terminal has Accessibility permission in System Settings.

**`python3` command not found**
→ Install Python from python.org, or try using `python` instead of `python3`.

**Shapes appear in the wrong place**
→ The coordinates are relative to the centre of your screen. If your display resolution is unusual, shapes may be slightly off. Use `object_move` to reposition them.

---

## How coordinates work

All positions are relative to the **centre of the Freeform window**:

- `(0, 0)` = centre of the board
- `(-300, 0)` = 300 pixels to the left of centre
- `(300, 0)` = 300 pixels to the right of centre
- `(0, -200)` = 200 pixels above centre
- `(0, 200)` = 200 pixels below centre

When planning a diagram, tell Claude the layout and it will calculate positions automatically.

---

## Important limitations

Apple Freeform has no official programming API, so this tool works by controlling the app the same way a human would — moving the mouse and using keyboard shortcuts. This means:

- **Do not move the mouse or click while Claude is drawing** — it will interfere
- Colour changes require the Format sidebar and may need manual adjustment
- The tool works best when the Freeform window is maximised
- Tested on macOS Sequoia with Freeform 2.x

---

## Repository

[github.com/ChrisvW56/freeform-mcp](https://github.com/ChrisvW56/freeform-mcp)
