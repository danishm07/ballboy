import mss
import base64
import json
import time
from PIL import Image
from io import BytesIO
from openai import OpenAI
from dotenv import load_dotenv
import os
import unified_state as us
from predictions import get_all_predictions

load_dotenv()

vision_client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

last_known_possession = 50

def capture_frame():
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        region = {
            "top": monitor["top"],
            "left": monitor["left"],
            "width": int(monitor["width"] * 0.7),
            "height": monitor["height"]
        }
        screenshot = sct.grab(region)
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        img = img.resize((854, 480))
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=80)
        return base64.b64encode(buffer.getvalue()).decode()

def analyze_frame(frame_b64):
    r = vision_client.chat.completions.create(
        model="google/gemini-2.0-flash-001",
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{frame_b64}"
                    }
                },
                {
                    "type": "text",
                    "text": """Analyze this soccer match screenshot. Extract visible information and return ONLY valid JSON:
{
  "minute": <match minute as integer, null if not visible>,
  "score_home": <integer, null if not visible>,
  "score_away": <integer, null if not visible>,
  "possession_home": <integer 0-100 if visible on screen, null if not>,
  "ball_zone": "<home_defense|home_mid|home_attack|away_defense|away_mid|away_attack|unknown>",
  "team_shape": "<high_press|mid_block|low_block|transitioning|unknown>",
  "tactical_description": "<one sentence describing what is tactically happening right now>",
  "pressing_intensity": "<high|medium|low>",
  "visible_events": ["<any visible text overlays like yellow card, substitution, VAR, goal>"],
  "confidence": <0.0 to 1.0>
}
Return ONLY the JSON object, nothing else."""
                }
            ]
        }],
        max_tokens=300
    )

    content = r.choices[0].message.content.strip()
    start = content.find("{")
    end = content.rfind("}") + 1
    if start != -1 and end > start:
        content = content[start:end]
    return json.loads(content)

def resolve_possession_home(vision_data):
    """Use last good possession when HUD is missing (50 + low confidence)."""
    global last_known_possession
    confidence = float(vision_data.get("confidence", 0.5) or 0.5)
    raw = vision_data.get("possession_home")

    if confidence > 0.7 and raw is not None:
        try:
            val = int(raw)
            if 0 < val < 100:
                last_known_possession = val
                return val
        except (TypeError, ValueError):
            pass

    if raw is not None:
        try:
            val = int(raw)
            if val == 50 and confidence < 0.7:
                return last_known_possession
            if 0 < val < 100:
                return val
        except (TypeError, ValueError):
            pass

    if confidence < 0.7:
        return last_known_possession

    history = us.read().get("possession_history", [])
    if len(history) >= 3:
        weights = list(range(1, len(history) + 1))
        possession_home = round(
            sum(h * w for h, w in zip(history, weights)) / sum(weights)
        )
        return max(30, min(70, possession_home))

    return last_known_possession


def write_state(vision_data, team_home, team_away):
    minute = vision_data.get("minute") or 0
    score_home = vision_data.get("score_home") or 0
    score_away = vision_data.get("score_away") or 0
    possession_home = resolve_possession_home(vision_data)

    us.update("match", {
        "minute": minute,
        "score": {"home": score_home, "away": score_away},
        "team_home": team_home,
        "team_away": team_away
    })

    us.update("vision", {
        "possession_home": possession_home,
        "ball_zone": vision_data.get("ball_zone", "unknown"),
        "team_shape": vision_data.get("team_shape", "unknown"),
        "tactical_description": vision_data.get("tactical_description", ""),
        "pressing_intensity": vision_data.get("pressing_intensity", "medium"),
        "confidence": vision_data.get("confidence", 0.5)
    })

    state = us.read()
    history = state.get("possession_history", [])
    history.append(possession_home)
    if len(history) > 10:
        history = history[-10:]
    state["possession_history"] = history

    if possession_home != 50:
        state.setdefault("stats", {})["possession_home"] = possession_home
        state["stats"]["possession_away"] = 100 - possession_home

    predictions = get_all_predictions(state)
    raw_momentum = predictions.get("momentum", 50)
    predictions["momentum"] = us.smooth_momentum(state, raw_momentum)
    state["smoothed_momentum"] = predictions["momentum"]
    state["prediction"] = predictions
    us.write(state)
    return state

def run(team_home="Arsenal FC", team_away="Manchester City FC"):
    print(f"[vision] starting — {team_home} vs {team_away}")
    print("[vision] open match video on screen now")

    while True:
        try:
            start = time.time()
            frame = capture_frame()
            data = analyze_frame(frame)
            state = write_state(data, team_home, team_away)
            match = state.get("match", {})
            elapsed = round((time.time() - start) * 1000)
            print(f"[vision] min={match.get('minute')} score={match.get('score')} conf={data.get('confidence', 0):.1f} {elapsed}ms")
        except Exception as e:
            print(f"[vision] error: {e}")

        time.sleep(3)

if __name__ == "__main__":
    import sys
    home = sys.argv[1] if len(sys.argv) > 1 else "Arsenal FC"
    away = sys.argv[2] if len(sys.argv) > 2 else "Manchester City FC"
    run(home, away)
