# Ballboy Overlay

A native always-on-top desktop overlay for macOS. Sits beside a match video playing on screen. Reads from a local Flask server at `localhost:5001`. Feels like Wispr Flow — clean, minimal, native.

## Tech Stack
- Electron (latest)
- Plain HTML/CSS/JS inside the renderer
- No React, no bundler, keep it simple
- Talks to Flask backend at localhost:5001

## Setup

### Install Dependencies
```bash
npm install
```

### Start the Flask Server First
The Flask server must be running at localhost:5001 before starting the overlay:
```bash
cd ../ballboy
python3 server.py
```

### Start the Electron Overlay
In a new terminal:
```bash
cd ballboy-overlay
npm start
```

## Features
- **Always-on-top floating window** pinned to right side of screen
- **Live match info** with team names, score, and minute
- **2D pitch visualization** with player dots in 4-3-3 formation
- **Dynamic team shapes** - dots shift based on game state (high_press, low_block, transitioning)
- **Real-time insights** with urgency indicators and action recommendations
- **Analyst chat feed** showing individual agent messages
- **Keyboard shortcut** - `Cmd+Shift+B` to toggle overlay visibility

## Visual Design
- Dark semi-transparent background (`rgba(0, 0, 0, 0.85)`)
- 380px fixed width, full screen height
- Rounded corners (12px)
- No window chrome, no titlebar
- Draggable via header bar
- Native macOS feel with SF Pro Display font

## Data Endpoints
- `GET http://localhost:5001/state` - Match state (polled every 3s)
- `GET http://localhost:5001/insight` - Current insight (polled every 2s)

## Keyboard Shortcuts
- `Cmd+Shift+B` - Toggle overlay visibility (hide/show)
