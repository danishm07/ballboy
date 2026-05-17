import json
import queue
import time
import threading
from dotenv import load_dotenv
import anthropic
import unified_state as us

load_dotenv()
client = anthropic.Anthropic()

MODEL = "GLM-5.1"

FORMATION_433 = {
    "home": [
        {"formation_index": 0, "x": 0.08, "y": 0.5},
        {"formation_index": 1, "x": 0.2, "y": 0.2},
        {"formation_index": 2, "x": 0.2, "y": 0.4},
        {"formation_index": 3, "x": 0.2, "y": 0.6},
        {"formation_index": 4, "x": 0.2, "y": 0.8},
        {"formation_index": 5, "x": 0.35, "y": 0.3},
        {"formation_index": 6, "x": 0.35, "y": 0.5},
        {"formation_index": 7, "x": 0.35, "y": 0.7},
        {"formation_index": 8, "x": 0.45, "y": 0.2},
        {"formation_index": 9, "x": 0.45, "y": 0.5},
        {"formation_index": 10, "x": 0.45, "y": 0.8},
    ],
    "away": [
        {"formation_index": 0, "x": 0.92, "y": 0.5},
        {"formation_index": 1, "x": 0.8, "y": 0.2},
        {"formation_index": 2, "x": 0.8, "y": 0.4},
        {"formation_index": 3, "x": 0.8, "y": 0.6},
        {"formation_index": 4, "x": 0.8, "y": 0.8},
        {"formation_index": 5, "x": 0.65, "y": 0.3},
        {"formation_index": 6, "x": 0.65, "y": 0.5},
        {"formation_index": 7, "x": 0.65, "y": 0.7},
        {"formation_index": 8, "x": 0.55, "y": 0.2},
        {"formation_index": 9, "x": 0.55, "y": 0.5},
        {"formation_index": 10, "x": 0.55, "y": 0.8},
    ],
}


def build_scenario_seeds(state):
    match = state.get("match", {})
    home = match.get("team_home", "Home")
    away = match.get("team_away", "Away")
    home_short = home.split()[0]
    away_short = away.split()[0]
    return [
        f"{home_short} scores a goal",
        f"{away_short} equalizes",
        f"Double substitution for {home_short}",
        f"{home_short} switches to high press",
        "Both teams drop into low block",
        "No major change — stalemate continues",
    ]


def _fallback_detail(state, seed, index):
    match = state.get("match", {})
    vision = state.get("vision", {})
    prediction = state.get("prediction", {})
    stats = state.get("stats", {})
    possession = vision.get("possession_home", stats.get("possession_home", 50))
    goal_prob = prediction.get("goal_probability", 0)
    sub_prob = prediction.get("substitution_probability", 0)
    minute = match.get("minute", 60)
    home = match.get("team_home", "Home").split()[0]
    away = match.get("team_away", "Away").split()[0]
    base = max(5, 35 - index * 4)

    reasons = [
        f"{home} hold {possession}% possession at minute {minute}",
        f"Goal probability model reads {goal_prob}% in next 10 minutes",
        f"Tactical read: {(vision.get('tactical_description') or 'balanced play')[:80]}",
    ]
    predictions = [
        {"label": f"{home} scores in next 10 min", "pct": min(45, base + 8)},
        {"label": f"Substitution before {minute + 10}'", "pct": min(40, sub_prob or 22)},
        {"label": f"{away} equalizes", "pct": max(5, base - 6)},
    ]
    key_stat = f"Possession {possession}% {home}"
    thinking = (
        f"Scenario '{seed}': at {minute}' with {possession}% home possession and "
        f"{goal_prob}% goal probability, the model weights {key_stat} as the primary driver."
    )
    return {
        "reasons": reasons,
        "predictions": predictions,
        "key_stat": key_stat,
        "thinking": thinking,
    }


def _normalize_predictions(raw, fallback):
    if not isinstance(raw, list):
        return fallback
    out = []
    for item in raw[:3]:
        if isinstance(item, dict) and item.get("label"):
            pct = item.get("pct", item.get("probability", 0))
            try:
                pct = int(pct)
            except (TypeError, ValueError):
                pct = 0
            out.append({"label": str(item["label"]), "pct": max(0, min(100, pct))})
        elif isinstance(item, str) and item.strip():
            out.append({"label": item.strip(), "pct": 0})
    while len(out) < 3:
        out.append(fallback[len(out)])
    return out[:3]


def _enrich_scenario(scenario, state, seed, index, thinking=""):
    detail = _fallback_detail(state, seed, index)
    reasons = scenario.get("reasons")
    if not isinstance(reasons, list) or len(reasons) < 3:
        scenario["reasons"] = detail["reasons"]
    else:
        scenario["reasons"] = reasons[:3]
    scenario["predictions"] = _normalize_predictions(
        scenario.get("predictions"), detail["predictions"]
    )
    if not scenario.get("key_stat"):
        scenario["key_stat"] = detail["key_stat"]
    scenario["thinking"] = (thinking or scenario.get("thinking") or detail["thinking"]).strip()
    return scenario


def _fallback_scenario(state, seed, index):
    base = FORMATION_433
    snapshots = []
    shift = (index % 3) * 0.03
    for frame in range(5):
        t = frame / 4.0
        home = []
        away = []
        for p in base["home"]:
            home.append({
                "formation_index": p["formation_index"],
                "x": min(0.95, p["x"] + shift * t),
                "y": p["y"],
            })
        for p in base["away"]:
            away.append({
                "formation_index": p["formation_index"],
                "x": max(0.05, p["x"] - shift * t * 0.5),
                "y": p["y"],
            })
        snapshots.append({"home": home, "away": away})

    detail = _fallback_detail(state, seed, index)
    return {
        "title": seed[:40],
        "probability": max(5, 35 - index * 4),
        "reasons": detail["reasons"],
        "predictions": detail["predictions"],
        "key_stat": detail["key_stat"],
        "thinking": detail["thinking"],
        "snapshots": snapshots,
    }


def _extract_reasoning(response):
    for block in getattr(response, "content", []) or []:
        block_type = getattr(block, "type", None)
        if block_type == "thinking":
            text = getattr(block, "thinking", None) or getattr(block, "text", None)
            if text:
                return str(text).strip()
    reasoning = getattr(response, "reasoning_content", None)
    if reasoning:
        return str(reasoning).strip()
    extra = getattr(response, "model_extra", None) or {}
    if isinstance(extra, dict):
        reasoning = extra.get("reasoning_content")
        if reasoning:
            return str(reasoning).strip()
    return ""


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _build_scenario_prompt(state, seed):
    match = state.get("match", {})
    vision = state.get("vision", {})
    prediction = state.get("prediction", {})
    team_home = match.get("team_home", "Home")
    team_away = match.get("team_away", "Away")

    return f"""You are simulating the next 10 minutes of a Premier League match.

Match: {team_home} vs {team_away}
Scenario: {seed}
Current: minute {match.get('minute', 60)}, score {match.get('score', {}).get('home', 0)}-{match.get('score', {}).get('away', 0)}
Possession home: {vision.get('possession_home', 50)}%
Tactical: {vision.get('tactical_description', '')}
Goal probability: {prediction.get('goal_probability', 0)}%

Return ONLY valid JSON:
{{
  "title": "short scenario title using team names",
  "probability": <integer 5-40, likelihood this scenario happens>,
  "reasons": ["bullet 1", "bullet 2", "bullet 3"],
  "predictions": [
    {{"label": "specific outcome 1", "pct": <integer 0-100>}},
    {{"label": "specific outcome 2", "pct": <integer 0-100>}},
    {{"label": "specific outcome 3", "pct": <integer 0-100>}}
  ],
  "key_stat": "single stat driving this prediction e.g. Possession 62% home",
  "snapshots": [
    {{"home": [{{"formation_index": 0, "x": 0.08, "y": 0.5}}, ...11 players], "away": [...11 players]}},
    ...exactly 5 snapshots showing dot movement over 10 minutes
  ]
}}

Use normalized x,y from 0.0 to 1.0 (home attacks right, x increases). Each snapshot must have exactly 11 home and 11 away positions with formation_index 0-10."""


def _parse_scenario_json(text):
    content = (text or "").strip()
    start = content.find("{")
    end = content.rfind("}") + 1
    if start != -1 and end > start:
        content = content[start:end]
    return json.loads(content)


def _consume_stream(stream, on_thinking=None):
    thinking = ""
    text = ""
    for event in stream:
        if getattr(event, "type", None) != "content_block_delta":
            continue
        delta = event.delta
        delta_type = getattr(delta, "type", None)
        if delta_type == "thinking_delta":
            chunk = getattr(delta, "thinking", None) or getattr(delta, "text", None) or ""
            if chunk:
                thinking += chunk
                if on_thinking:
                    on_thinking(chunk)
        elif delta_type == "text_delta":
            chunk = getattr(delta, "text", None) or ""
            if chunk:
                text += chunk
    return thinking.strip(), text.strip()


def _run_one_scenario(state, seed, index, on_thinking=None):
    prompt = _build_scenario_prompt(state, seed)
    started = time.time()

    try:
        stream = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            extra_body={"enable_thinking": True},
        )
        thinking, content = _consume_stream(stream, on_thinking=on_thinking)
        parsed = _parse_scenario_json(content)
        if "snapshots" in parsed and len(parsed.get("snapshots", [])) >= 1:
            result = _enrich_scenario(parsed, state, seed, index, thinking=thinking)
            result["response_ms"] = round((time.time() - started) * 1000)
            return result
    except Exception as e:
        print(f"[simulate] scenario {index} error: {e}")

    result = _fallback_scenario(state, seed, index)
    result["response_ms"] = round((time.time() - started) * 1000)
    return result


def _mark_most_likely(scenarios):
    best_prob = -1
    best_idx = 0
    for i, s in enumerate(scenarios):
        prob = s.get("probability", 0)
        if prob > best_prob:
            best_prob = prob
            best_idx = i
    for i, s in enumerate(scenarios):
        s["most_likely"] = i == best_idx
    return scenarios


def run_simulate():
    start = time.time()
    state = us.read()
    seeds = build_scenario_seeds(state)
    scenarios = [None] * len(seeds)
    lock = threading.Lock()

    def worker(i, seed):
        result = _run_one_scenario(state, seed, i)
        with lock:
            scenarios[i] = result

    threads = []
    for i, seed in enumerate(seeds):
        t = threading.Thread(target=worker, args=(i, seed))
        threads.append(t)
        t.start()
        time.sleep(0.5)
    for t in threads:
        t.join()

    valid = [s for s in scenarios if s]
    if not valid:
        valid = [_fallback_scenario(state, seed, i) for i, seed in enumerate(seeds)]

    _mark_most_likely(valid)
    elapsed = round((time.time() - start) * 1000)
    return {"scenarios": valid, "generated_ms": elapsed}


def run_simulate_stream():
    """Yield Server-Sent Events for thinking tokens and completed scenarios."""
    start = time.time()
    state = us.read()
    seeds = build_scenario_seeds(state)
    scenarios = [None] * len(seeds)
    event_queue = queue.Queue()
    done_lock = threading.Lock()
    remaining = len(seeds)

    def worker(i, seed):
        nonlocal remaining
        started = time.time()
        try:
            event_queue.put(("scenario_start", {"index": i, "seed": seed}))

            def on_thinking(token):
                event_queue.put(("thinking", {"index": i, "token": token}))

            result = _run_one_scenario(state, seed, i, on_thinking=on_thinking)
            if "response_ms" not in result:
                result["response_ms"] = round((time.time() - started) * 1000)
            scenarios[i] = result
            event_queue.put(
                ("scenario_done", {"index": i, "scenario": result, "response_ms": result["response_ms"]})
            )
        except Exception as e:
            print(f"[simulate] stream worker {i} error: {e}")
            fallback = _fallback_scenario(state, seed, i)
            scenarios[i] = fallback
            event_queue.put(("scenario_done", {"index": i, "scenario": fallback}))
        finally:
            with done_lock:
                remaining -= 1
                if remaining == 0:
                    event_queue.put(("__done__", None))

    for i, seed in enumerate(seeds):
        threading.Thread(target=worker, args=(i, seed), daemon=True).start()
        time.sleep(0.5)

    finished = False
    while not finished:
        kind, payload = event_queue.get()
        if kind == "__done__":
            finished = True
            continue
        yield _sse(kind, payload)

    valid = [s for s in scenarios if s]
    if not valid:
        valid = [_fallback_scenario(state, seed, i) for i, seed in enumerate(seeds)]

    _mark_most_likely(valid)
    elapsed = round((time.time() - start) * 1000)
    yield _sse("complete", {"scenarios": valid, "generated_ms": elapsed})
