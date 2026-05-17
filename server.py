from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS
import json
import os
import time
from dotenv import load_dotenv

MUTE_FILE = "/tmp/ballboy_mute"

load_dotenv()

app = Flask(__name__)
CORS(app)


def read_unified():
    try:
        with open("unified_state.json") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def unified_to_legacy(state):
    if not state:
        return {}
    match = state.get("match", {})
    vision = state.get("vision", {})
    possession = vision.get("possession_home", state.get("stats", {}).get("possession_home", 50))
    return {
        "team_home": match.get("team_home", "Arsenal FC"),
        "team_away": match.get("team_away", "Manchester City FC"),
        "minute": match.get("minute", 0),
        "score": match.get("score", {"home": 0, "away": 0}),
        "possession_pct": {"home": possession, "away": 100 - possession},
        "ball_zone": vision.get("ball_zone", "unknown"),
        "team_shape": vision.get("team_shape", "unknown"),
        "tactical_description": vision.get("tactical_description", ""),
        "confidence": vision.get("confidence", 0.5),
        "timestamp": time.time(),
    }


@app.route("/unified_state")
def unified_state_endpoint():
    import unified_state as us

    state = read_unified()
    if not state:
        state = us._default_copy()
    return jsonify(us.ensure_lineup(state))


@app.route("/state")
def state():
    legacy = unified_to_legacy(read_unified())
    if legacy:
        return jsonify(legacy)
    try:
        with open("current_state.json") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({})


@app.route("/insight")
def insight():
    try:
        with open("current_insight.json") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({
            "headline": "Waiting...",
            "body": "Start pipeline.",
            "urgency": "low",
            "action": "Run start.sh",
            "generated_ms": 0,
            "analyst_ms": 0,
            "minute": None,
        })


@app.route("/history")
def history():
    try:
        with open("history_context.json") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({})


@app.route("/detections")
def detections():
    try:
        with open("detections.json") as f:
            content = f.read().strip()
            if not content:
                return jsonify({"players": [], "ball": None, "total": 0})
            return jsonify(json.loads(content))
    except Exception:
        return jsonify({"players": [], "ball": None, "total": 0})


@app.route("/simulate")
def simulate():
    from simulate_agent import run_simulate
    try:
        return jsonify(run_simulate())
    except Exception as e:
        return jsonify({"scenarios": [], "error": str(e), "generated_ms": 0}), 500


@app.route("/data_sources")
def data_sources():
    try:
        state = json.loads(open("unified_state.json").read())
        insight = json.loads(open("current_insight.json").read())

        vision = state.get("vision", {})
        stats = state.get("stats", {})
        prediction = state.get("prediction", {})
        analyst_times = insight.get("analyst_times", {})
        total_ms = insight.get("generated_ms", 0)
        match = state.get("match", {})
        score = match.get("score", {})

        return jsonify({
            "sources": [
                {
                    "name": "Vision",
                    "model": "Gemini 2.0 Flash",
                    "provider": "OpenRouter",
                    "data": f"minute: {match.get('minute', '?')}, score: {score}, possession: {vision.get('possession_home', '?')}%",
                    "latency_ms": None,
                    "wafer": False,
                },
                {
                    "name": "Detection",
                    "model": "YOLOv8s + ByteTrack",
                    "provider": "Local",
                    "data": "players detected, 13fps",
                    "latency_ms": None,
                    "wafer": False,
                },
                {
                    "name": "History",
                    "model": "SQLite query",
                    "provider": "Local DB",
                    "data": "win rate from similar situations",
                    "latency_ms": None,
                    "wafer": False,
                },
                {
                    "name": "Predictions",
                    "model": "Poisson + empirical distributions",
                    "provider": "Pure math",
                    "data": f"goal: {prediction.get('goal_probability', '?')}%, sub: {prediction.get('substitution_probability', '?')}%",
                    "latency_ms": None,
                    "wafer": False,
                },
                {
                    "name": "DEF analyst",
                    "model": "GLM-5.1",
                    "provider": "Wafer",
                    "data": "defensive tactical observation",
                    "latency_ms": analyst_times.get("defensive"),
                    "wafer": True,
                },
                {
                    "name": "ATK analyst",
                    "model": "GLM-5.1",
                    "provider": "Wafer",
                    "data": "attacking opportunity",
                    "latency_ms": analyst_times.get("offensive"),
                    "wafer": True,
                },
                {
                    "name": "PHY analyst",
                    "model": "GLM-5.1",
                    "provider": "Wafer",
                    "data": "fitness and substitution",
                    "latency_ms": analyst_times.get("physical"),
                    "wafer": True,
                },
                {
                    "name": "Synthesizer",
                    "model": "GLM-5.1",
                    "provider": "Wafer",
                    "data": "final insight",
                    "latency_ms": insight.get("synthesizer_ms") or total_ms,
                    "wafer": True,
                },
            ],
            "total_ms": total_ms,
            "pipeline": "Vision → Detection → History → Predictions → 3x Wafer analysts (parallel) → Wafer synthesizer",
        })
    except Exception:
        return jsonify({"sources": [], "total_ms": 0, "pipeline": ""})


@app.route("/mute", methods=["POST"])
def mute():
    data = request.get_json(silent=True) or {}
    if data.get("muted"):
        open(MUTE_FILE, "w").close()
    else:
        try:
            os.remove(MUTE_FILE)
        except OSError:
            pass
    return jsonify({"ok": True})


@app.route("/simulate/stream")
def simulate_stream():
    from simulate_agent import run_simulate_stream

    def generate():
        try:
            for chunk in run_simulate_stream():
                yield chunk
        except Exception as e:
            yield f"event: simulate_error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    app.run(port=5001, debug=False)
