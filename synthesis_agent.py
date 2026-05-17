import json
import os
import subprocess
import time
import threading
from dotenv import load_dotenv
import anthropic
import requests
import unified_state as us

load_dotenv()
client = anthropic.Anthropic()

AUDIO_PATH = "/tmp/ballboy_alert.mp3"
MUTE_URL = "http://localhost:5001/mute"

results = {}
lock = threading.Lock()
last_spoken_headline = None


def is_muted():
    try:
        r = requests.get(MUTE_URL, timeout=1)
        return r.json().get("muted", False)
    except Exception:
        return False


def speak(text):
    key = os.getenv("ELEVENLABS_API_KEY")
    if not key:
        return
    if is_muted():
        print("[voice] muted — skipping")
        return
    try:
        r = requests.post(
            "https://api.elevenlabs.io/v1/text-to-speech/pNInz6obpgDQGcFmaJgB",
            headers={
                "xi-api-key": key,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": "eleven_turbo_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
            timeout=10,
        )
        r.raise_for_status()
        with open(AUDIO_PATH, "wb") as f:
            f.write(r.content)
        subprocess.Popen(["afplay", AUDIO_PATH])
    except Exception as e:
        print(f"[voice] error: {e}")

MODEL = "Qwen3.5-397B-A17B"

analyst_times = {}


def call_model(prompt, max_tokens=300):
    r = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": f"Reply with valid JSON only, no other text.\n\n{prompt}"}],
        extra_body={"enable_thinking": False},
    )
    content = r.content[0].text.strip()
    start = content.find("{")
    end = content.rfind("}") + 1
    if start != -1 and end > start:
        content = content[start:end]
    parsed = json.loads(content)
    urgency = parsed.get("urgency", "medium").lower()
    parsed["urgency"] = "high" if "high" in urgency else "low" if "low" in urgency else "medium"
    return json.dumps(parsed)


def _possession_trend(unified_state_data):
    history = unified_state_data.get("possession_history", [])
    if len(history) < 2:
        return "stable"
    if history[-1] > history[-2]:
        return "rising"
    if history[-1] < history[-2]:
        return "falling"
    return "stable"


def _build_analyst_prompt(name, unified_state_data):
    match = unified_state_data.get("match", {})
    vision = unified_state_data.get("vision", {})
    minute = match.get("minute", 0)
    score_home = match.get("score", {}).get("home", 0)
    score_away = match.get("score", {}).get("away", 0)
    team_home = match.get("team_home", "Home")
    team_away = match.get("team_away", "Away")
    poss = vision.get("possession_home", unified_state_data.get("stats", {}).get("possession_home", 50))
    ball_zone = vision.get("ball_zone", "unknown")
    team_shape = vision.get("team_shape", "unknown")
    trend = _possession_trend(unified_state_data)

    if name == "defensive":
        return f"""You are a defensive analyst. In ONE sentence under 20 words, identify
the single biggest defensive risk RIGHT NOW based on:
Minute: {minute} | Score: {score_home}-{score_away} | Ball: {ball_zone} |
Shape: {team_shape} | Possession: {poss}%
Do NOT repeat the match context back. Give the tactical insight only.
Bad: 'At minute 35 the ball is in...'
Good: 'Back four exposed on left channel with Spain pressing high'
Return JSON: {{"insight": "...", "urgency": "high|medium|low", "action": "..."}}"""

    if name == "offensive":
        return f"""You are an attacking analyst. In ONE sentence under 20 words, identify
the single biggest attacking opportunity RIGHT NOW based on:
Minute: {minute} | Score: {score_home}-{score_away} | Ball: {ball_zone} |
Shape: {team_shape} | Possession: {poss}%
Do NOT repeat context. Give the opportunity only.
Bad: 'With 52% possession at minute 35...'
Good: 'Space behind Spain right back — Saka can exploit now'
Return JSON: {{"insight": "...", "urgency": "high|medium|low", "action": "..."}}"""

    if name == "physical":
        return f"""You are a fitness analyst. In ONE sentence under 20 words, identify
substitution or fatigue risk RIGHT NOW based on:
Minute: {minute} | Score: {score_home}-{score_away} | Possession trend: {trend}
Do NOT repeat context. Give the fitness insight only.
Bad: 'At minute 35 with the score...'
Good: 'Minute 35 — midfielders covering excess ground, sub window opening'
Return JSON: {{"insight": "...", "urgency": "high|medium|low", "action": "..."}}"""

    return ""


def run_analyst(name, unified_state_data):
    start = time.time()
    vision = unified_state_data.get("vision", {})
    confidence = vision.get("confidence", 0)

    if confidence < 0.5:
        with lock:
            results[name] = {"insight": "Low confidence reading", "urgency": "low", "action": "monitor"}
            analyst_times[name] = round((time.time() - start) * 1000)
        return

    prompt = _build_analyst_prompt(name, unified_state_data)
    if not prompt:
        with lock:
            results[name] = {"insight": f"{name} unavailable", "urgency": "low", "action": "monitor"}
            analyst_times[name] = round((time.time() - start) * 1000)
        return

    try:
        raw = call_model(prompt, max_tokens=150)
        with lock:
            results[name] = json.loads(raw)
            analyst_times[name] = round((time.time() - start) * 1000)
        print(f"  [{name}] ✓ {analyst_times[name]}ms")
    except Exception as e:
        print(f"  [{name}] error: {e}")
        with lock:
            results[name] = {"insight": f"{name} unavailable", "urgency": "low", "action": "monitor"}
            analyst_times[name] = round((time.time() - start) * 1000)


def synthesize_parallel(unified_state_data, history):
    start = time.time()
    results.clear()
    analyst_times.clear()

    threads = []
    for name in ("defensive", "offensive", "physical"):
        t = threading.Thread(target=run_analyst, args=(name, unified_state_data))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    analyst_time = round((time.time() - start) * 1000)
    minute = unified_state_data.get("match", {}).get("minute", 0)

    match = unified_state_data.get("match", {})
    vision = unified_state_data.get("vision", {})
    team_home = match.get("team_home", "Home")
    team_away = match.get("team_away", "Away")
    score = match.get("score", {})
    ball_zone = vision.get("ball_zone", "unknown")
    tactical_desc = vision.get("tactical_description", "")

    combined_prompt = f"""Three analysts assessed minute {minute}, {team_home} {score.get('home', 0)}–{score.get('away', 0)} {team_away}, ball zone {ball_zone}:

Defensive: {json.dumps(results.get('defensive', {}))}
Offensive: {json.dumps(results.get('offensive', {}))}
Physical: {json.dumps(results.get('physical', {}))}

Vision tactical read: "{tactical_desc}"
Historical context: {history.get('pattern', 'no data')}

Pick the MOST URGENT analyst insight. Preserve its exact minute, score, ball zone, and tactical detail — do not generalize.

Return JSON: headline (5 words max, specific not generic), body (max 2 sentences, must repeat minute {minute}, score, zone, and vision tactic), urgency, action.

GOOD body: "Ball lost in own half at minute 62, Spain 3–2 Portugal — Spain pressing high; Portugal back four exposed on the right channel."
BAD body: "High risk of conceding. Drop deeper." """

    synth_start = time.time()
    try:
        raw = call_model(combined_prompt, max_tokens=300)
        insight = json.loads(raw)
    except Exception as e:
        print(f"  [synthesizer] error: {e}")
        insight = {"headline": "Analysis error", "body": str(e), "urgency": "low", "action": "check logs"}
    synthesizer_ms = round((time.time() - synth_start) * 1000)

    total_time = round((time.time() - start) * 1000)
    prediction = unified_state_data.get("prediction", {})
    insight["generated_ms"] = total_time
    insight["analyst_ms"] = analyst_time
    insight["analyst_times"] = dict(analyst_times)
    insight["synthesizer_ms"] = synthesizer_ms
    insight["minute"] = minute
    insight["timestamp"] = time.time()
    insight["analysts"] = {k: v for k, v in results.items()}
    insight["prediction"] = {
        "goal_probability": prediction.get("goal_probability", 0),
        "sub_probability": prediction.get("substitution_probability", 0),
        "momentum": prediction.get("momentum", 50),
        "minutes_remaining": prediction.get("minutes_remaining", 0),
    }

    with open("current_insight.json", "w") as f:
        json.dump(insight, f, indent=2)

    global last_spoken_headline
    urgency = str(insight.get("urgency", "low")).lower()
    headline = insight.get("headline", "")
    action = insight.get("action", "")

    if urgency == "high" and headline and headline != last_spoken_headline:
        speak_text = f"{headline}. {action}"
        threading.Thread(target=speak, args=(speak_text,), daemon=True).start()
        last_spoken_headline = headline
        print(f"[voice] speaking: {headline}")

    print(f"[synthesis] '{insight.get('headline')}' — {insight.get('urgency')} — {total_time}ms total ({analyst_time}ms analysts)")
    return insight


STATE_FRESH_SEC = 10


def state_is_fresh(state, max_age=STATE_FRESH_SEC):
    ts = state.get("timestamp")
    if ts is None:
        return False
    try:
        return (time.time() - float(ts)) <= max_age
    except (TypeError, ValueError):
        return False


def run():
    print("[synthesis] starting parallel loop...")
    while True:
        try:
            with open(us.STATE_FILE) as f:
                game_state = json.load(f)
            if not state_is_fresh(game_state):
                age = time.time() - float(game_state.get("timestamp", 0)) if game_state.get("timestamp") else None
                print(f"[synthesis] skip — state not updated recently ({age:.0f}s ago)" if age else "[synthesis] skip — no state timestamp")
            else:
                minute = game_state.get("match", {}).get("minute", 0)
                score = game_state.get("match", {}).get("score", {})
                possession = game_state.get("vision", {}).get("possession_home", 50)
                ball_zone = game_state.get("vision", {}).get("ball_zone", "unknown")
                tactical_description = game_state.get("vision", {}).get("tactical_description", "")
                print(
                    f"[synthesis] min={minute} score={score} poss={possession}% "
                    f"zone={ball_zone} tactic={tactical_description[:40]!r}"
                )
                with open("history_context.json") as f:
                    history = json.load(f)
                synthesize_parallel(game_state, history)
        except FileNotFoundError:
            print("[synthesis] waiting for unified_state.json / history_context.json...")
        except Exception as e:
            print(f"[synthesis] error: {e}")
        time.sleep(10)


if __name__ == "__main__":
    run()
