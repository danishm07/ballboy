# Ballboy 🏃

AI-powered real-time soccer coach assistant. Watches any live match through your screen and tells coaches what's about to happen — before the broadcast catches up.

Ballboy combines **screen vision**, **player detection**, **historical match patterns**, and **parallel LLM analysts** into a single always-on-top desktop overlay. Point it at a YouTube stream, a TV feed, or a browser tab; calibrate the video region once; get tactical insights, probability readouts, and voice alerts in under two seconds per synthesis cycle.

---

## What it does

| Layer | What happens | Cadence |
|-------|----------------|---------|
| **Vision** | Gemini 2.0 Flash reads the match frame (score, minute, possession, ball zone, shape) | ~3s per frame |
| **Detection** | YOLOv8s + ByteTrack locates players on the calibrated video crop | ~13 FPS (`soccer_tracker.py`) |
| **History** | SQLite queries similar score/minute situations for win-rate context | Every 10s |
| **Predictions** | Poisson goal model + empirical sub distribution + zone-based momentum | On every vision write |
| **Analysts** | 3 specialist prompts (DEF / ATK / PHY) run in parallel via Wafer | Every 10s |
| **Synthesis** | One Wafer call merges analysts + vision + history into a coach headline | ~1–1.5s after analysts |
| **Voice** | ElevenLabs speaks high-urgency alerts (macOS `afplay`) | On new high-urgency insight |

End-to-end: vision capture → unified state update → parallel analysts → synthesizer → overlay poll is designed to feel **sub-2-second** for the coaching insight loop.

---

## Stack

- **Vision:** Gemini 2.0 Flash (`google/gemini-2.0-flash-001`) via [OpenRouter](https://openrouter.ai/)
- **Detection:** YOLOv8s + ByteTrack + PyQt5 calibrated screen overlay (`soccer_tracker.py`)
- **Inference:** GLM-class models via [Wafer](https://wafer.ai) — 3 parallel analyst calls + 1 synthesizer (Anthropic-compatible API; see [Configuration](#configuration))
- **Predictions:** Poisson distribution + empirical substitution curves + StatsBomb open xG baselines
- **Historical:** SQLite (`ballboy.db`) seeded from football-data.org match archives
- **Pre-match:** StatsBomb open data (2018 World Cup) for lineups, xG, possession, press counts
- **Frontend:** Electron two-panel overlay (lineup + analysis), always-on-top on macOS
- **Voice:** ElevenLabs Turbo v2 for high-urgency coach alerts
- **API (optional):** API-Sports live stats when `FOOTBALL_API_KEY` is set and a fixture is live

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         LIVE MATCH ON SCREEN                             │
│              (browser / TV app — left ~70% of display captured)          │
└───────────────┬───────────────────────────────┬─────────────────────────┘
                │ mss screen grab               │ PIL crop (calibrated)
                ▼                               ▼
        ┌───────────────┐               ┌──────────────────┐
        │ vision_agent  │               │ soccer_tracker   │
        │ Gemini Flash  │               │ YOLOv8s+ByteTrack│
        └───────┬───────┘               └────────┬─────────┘
                │                                  │
                │         ┌────────────────────────┘
                │         │  detections.json
                ▼         ▼
        ┌───────────────────────────────────┐
        │      unified_state.json           │  ← single source of truth
        │  match · vision · stats · lineup  │
        │  prediction · possession_history  │
        └───────────┬───────────────────────┘
                    │
     ┌──────────────┼──────────────┬─────────────────┐
     ▼              ▼              ▼                 ▼
 history_agent  predictions.py  api_agent      prematch.py
 (SQLite)       (pure math)     (optional)     (StatsBomb)
     │              │              │                 │
     └──────────────┴──────────────┴─────────────────┘
                    │
                    ▼
           ┌─────────────────┐
           │ synthesis_agent │  3× parallel DEF/ATK/PHY
           │  + synthesizer  │  → current_insight.json
           └────────┬────────┘
                    │ ElevenLabs (high urgency)
                    ▼
           ┌─────────────────┐
           │   server.py     │  Flask :5001
           │  REST + SSE     │
           └────────┬────────┘
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
  overlay/players.html    overlay/analysis.html
  (lineup panel)          (insight, momentum, simulate)
```

### Unified state (`unified_state.json`)

All agents read and write through `unified_state.py` (thread-safe JSON I/O). Sections:

- **`match`** — teams, minute, score
- **`vision`** — possession, ball zone, team shape, tactical one-liner, confidence
- **`stats`** — shots, xG, fouls, subs (from API or defaults)
- **`lineup`** — 11 starters per side with formation indices
- **`prediction`** — goal %, sub %, momentum (smoothed EMA)
- **`possession_history`** — rolling window for trend-aware prompts
- **`events`** — goals, cards, subs (from API when live)

### Vision agent (`vision_agent.py`)

1. Captures the **left 70%** of the primary monitor via `mss` (matches typical video-player layout).
2. Resizes to 854×480 JPEG and sends to Gemini with a strict JSON schema (minute, score, possession, ball zone, shape, etc.).
3. **Possession smoothing:** ignores bogus 50% reads when confidence is low; falls back to weighted history.
4. Calls `get_all_predictions()` and writes the full state with a fresh `timestamp` (required for synthesis to run).

### Synthesis agent (`synthesis_agent.py`)

1. Waits for `unified_state.json` with `timestamp` younger than 10 seconds.
2. Spawns three threads: **defensive**, **offensive**, **physical** — each gets a focused one-sentence JSON prompt.
3. Runs a **synthesizer** pass that picks the most urgent analyst output and preserves minute/score/zone detail.
4. Writes `current_insight.json` with latency breakdown (`analyst_times`, `synthesizer_ms`, `generated_ms`).
5. On **high** urgency, fires ElevenLabs TTS unless `/mute` is active.

Wafer is used through the Anthropic Python SDK:

```bash
ANTHROPIC_BASE_URL=https://pass.wafer.ai
ANTHROPIC_API_KEY=<your-wafer-key>
```

Default model in code: `Qwen3.5-397B-A17B` (configurable in `synthesis_agent.py` / `simulate_agent.py`).

### Predictions (`predictions.py`)

Pure math — no LLM:

- **Goal probability:** Poisson model from remaining xG (StatsBomb season rates or live xG when available), scaled by `time_factor(minute)` (higher late game).
- **Substitution probability:** empirical minute→% curve (peaks ~85–90').
- **Momentum:** ball-zone base score + goal-difference boost, EMA-smoothed in vision writes.

### History agent (`history_agent.py`)

Queries `ballboy.db` → `match_states` for situations matching:

- Same home team (fuzzy name match)
- Minute ±10
- Same score state (leading / drawing / losing)

Writes `history_context.json` with win rate and optional late-game hold pattern (minute ≥ 70).

### Detection paths

| Component | Role |
|-----------|------|
| **`soccer_tracker.py`** (recommended) | PyQt5 transparent overlay on calibrated video rectangle; writes `detections.json`; ~13 FPS; persists `calibration.json` |
| **`detection_agent.py`** | Headless YOLO + homography to pitch coords; not started by `start.sh` |

### Flask server (`server.py` — port **5001**)

| Endpoint | Purpose |
|----------|---------|
| `GET /unified_state` | Full state + lineup normalization |
| `GET /state` | Legacy match summary for older clients |
| `GET /insight` | Latest coach insight |
| `GET /history` | Historical pattern blob |
| `GET /detections` | Player boxes + FPS |
| `GET /calibration` | Video crop rectangle |
| `GET /data_sources` | Pipeline latency dashboard |
| `GET/POST /mute` | Voice alert mute toggle |
| `GET /simulate` | 3-scenario “next 5 minutes” Wafer simulation |
| `GET /simulate/progress` | SSE progress for simulate UI |
| `GET /simulate/stream` | SSE streamed scenario results |

---

## Prerequisites

- **macOS** (screen capture, `afplay`, PyQt5 overlay, Electron always-on-top)
- **Python 3.10+**
- **Node.js 18+** (Electron overlay)
- API keys (see below)

---

## Configuration

Create a `.env` file in the project root:

```env
OPENROUTER_API_KEY=          # Gemini vision
ANTHROPIC_API_KEY=           # Wafer (set ANTHROPIC_BASE_URL=https://pass.wafer.ai)
ANTHROPIC_BASE_URL=https://pass.wafer.ai
ELEVENLABS_API_KEY=          # Voice alerts (optional)
FOOTBALL_API_KEY=            # API-Sports live stats (optional)
```

| Key | Used by | Required |
|-----|---------|----------|
| `OPENROUTER_API_KEY` | `vision_agent.py` | Yes (for live vision) |
| `ANTHROPIC_API_KEY` + `ANTHROPIC_BASE_URL` | `synthesis_agent.py`, `simulate_agent.py` | Yes (for insights / simulate) |
| `ELEVENLABS_API_KEY` | `synthesis_agent.py` | No (silent without it) |
| `FOOTBALL_API_KEY` | `api_agent.py` | No (falls back to vision-only stats) |

---

## Run

### 1. Python environment

```bash
cd /Users/danish/Documents/ballboy
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Extra deps for the calibrated tracker overlay
pip install PyQt5
```

### 2. Pre-match data (StatsBomb)

Loads real 2018 World Cup lineups, match xG, possession, and press events when team names match StatsBomb records; otherwise falls back to built-in Portugal/Spain defaults.

```bash
python3 prematch.py "Portugal" "Spain"
```

Outputs: `unified_state.json`, `prematch_data.json`.

### 3. Backend pipeline

```bash
./start.sh "Portugal" "Spain"
```

`start.sh` kills stale agents, runs `prematch.py`, then launches:

- `vision_agent.py` — screen → Gemini → unified state
- `history_agent.py` — SQLite context loop
- `synthesis_agent.py` — parallel analysts + synthesizer
- `api_agent.py` — optional live API-Sports (or fallback)
- `server.py` — Flask on **localhost:5001**

**Before starting:** open your match video full-screen or in a browser tab on the **left side** of the display.

> **Note:** `start.sh` uses `venv/bin/python3` at a fixed path. Edit line 15 if your venv lives elsewhere.

### 4. Electron overlay (separate terminal)

```bash
cd overlay
npm install
npm start
```

Two always-on-top windows:

- **Lineup panel** — home/away XI from `/unified_state`
- **Analysis panel** — headline, momentum bar, predictions, data-source latencies, “Predict Next 5 Minutes” simulate flow

**Shortcut:** `Cmd+Shift+B` toggles overlay visibility.

### 5. Player detection overlay (separate terminal)

```bash
python3 soccer_tracker.py
```

First run: click **top-left** and **bottom-right** of the video player to save `calibration.json`. Orange boxes track players; detections feed `detections.json` for the lineup panel.

- **Recalibrate:** `C` or the control window button  
- **Quit:** `Q`

```bash
python3 soccer_tracker.py --recalibrate   # force new crop
```

---

## Optional: seed historical database

`history_agent.py` needs rows in `ballboy.db`. Initialize schema and load seasons from football-data.org:

```bash
python3 db.py
python3 loader.py "Portugal" "Spain"
```

Without this step, history patterns show “Limited historical data” but the rest of the pipeline still runs.

---

## Project layout

```
ballboy/
├── start.sh                 # Launch backend agents + server
├── prematch.py              # StatsBomb pre-match loader
├── unified_state.py         # Shared state read/write
├── predictions.py           # Poisson + empirical models
├── vision_agent.py          # Screen capture + Gemini
├── synthesis_agent.py       # Parallel Wafer analysts + voice
├── history_agent.py         # SQLite pattern queries
├── api_agent.py             # Optional API-Sports poller
├── detection_agent.py       # Headless YOLO (alternative)
├── soccer_tracker.py        # PyQt5 calibrated overlay (preferred)
├── simulate_agent.py        # Wafer scenario simulation
├── server.py                # Flask API :5001
├── loader.py                # football-data.org → SQLite
├── db.py                    # Create match_states table
├── overlay/                 # Electron UI
│   ├── main.js              # Two-window shell
│   ├── players.html/js      # Lineup panel
│   ├── analysis.html/js     # Coach insight panel
│   └── shared.js            # API base URL
├── unified_state.json       # Live state (generated)
├── current_insight.json     # Latest synthesis (generated)
├── detections.json          # Player tracks (generated)
├── calibration.json         # Video crop (generated)
└── ballboy.db               # Historical matches (optional)
```

---

## Demo workflow

1. Queue a full-match replay (e.g. Portugal vs Spain 2018) on screen — **left-aligned**, scoreboard visible.
2. `python3 prematch.py "Portugal" "Spain"`
3. `./start.sh "Portugal" "Spain"`
4. `cd overlay && npm start`
5. `python3 soccer_tracker.py` → calibrate video rectangle
6. Watch the analysis panel: minute/score update from vision, insight refreshes every ~10s, momentum and goal/sub % move with predictions.
7. Expand **Predict Next 5 Minutes** for parallel Wafer scenario branches (SSE progress in UI).
8. Trigger a high-urgency insight to hear ElevenLabs; use the 🔊 mute button to silence.

---

## Tracks

Ballboy is built for hackathon/demo tracks that reward **real-time multimodal AI**, **fast inference**, and **unusual UX**:

### Best Inference (Wafer)

- **3 parallel specialist calls** (defensive / offensive / physical) plus a **synthesizer** — all through Wafer’s Anthropic-compatible endpoint.
- Typical breakdown exposed in `current_insight.json`: `analyst_ms` (parallel wall time) + `synthesizer_ms` + `generated_ms` total.
- **`/data_sources`** and the analysis footer show per-agent latency; simulate mode runs additional parallel Wafer calls for branching “next 5 minutes” scenarios.
- Thinking disabled (`enable_thinking: false`) for minimum latency on analyst passes.

### ElevenLabs

- High-urgency insights trigger **spoken coach alerts** (`eleven_turbo_v2`) via `afplay` on macOS.
- Mute is **server-side** (`GET/POST /mute`) and wired to the analysis panel button — no restart required.
- Copy is short by design: headline (≤5 words) + action line, optimized for TTS in a noisy sideline environment.

### Most Uncommon

- **Watches your screen** instead of an official data feed — works on any broadcast or stream.
- **Dual overlay stack:** Electron coach UI + PyQt5 pixel-aligned detection boxes on the actual video.
- **Math + memory + vision + LLM** in one loop: Poisson predictions and SQLite history ground the models so insights aren’t pure hallucination.
- Pre-match grounding from **StatsBomb open data** ties lineups and xG to real matches even when the video is a replay.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Insight stuck on “Waiting…” | Ensure `vision_agent` is running and `unified_state.json` has a recent `timestamp` |
| `[synthesis] skip — state not updated` | Vision agent not writing; check `OPENROUTER_API_KEY` and that match video is visible on screen |
| Wrong minute/score | Improve video size/quality; scoreboard must be readable by Gemini |
| No player boxes | Run `soccer_tracker.py`; confirm `calibration.json` matches current video position |
| No voice | Set `ELEVENLABS_API_KEY`; check mute state; macOS only (`afplay`) |
| `start.sh` python not found | Create `venv` or edit `PYTHON=` path in `start.sh` |
| Overlay can’t reach API | Backend must be on `http://localhost:5001` before `npm start` |
| StatsBomb prematch fails | Falls back to default lineups — still runnable; check network for `statsbombpy` |

---

## License

ISC (Electron overlay package). Third-party models and APIs (OpenRouter, Wafer, ElevenLabs, StatsBomb, Ultralytics YOLO) are subject to their respective terms.
