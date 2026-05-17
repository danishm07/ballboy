import copy
import json
import threading
import time

STATE_FILE = "unified_state.json"
_lock = threading.Lock()

PORTUGAL_LINEUP = [
    {"name": "Rui Patricio", "position": "GK", "number": 1, "formation_index": 0},
    {"name": "Cedric Soares", "position": "RB", "number": 21, "formation_index": 1},
    {"name": "Pepe", "position": "CB", "number": 3, "formation_index": 2},
    {"name": "Jose Fonte", "position": "CB", "number": 6, "formation_index": 3},
    {"name": "Raphael Guerreiro", "position": "LB", "number": 5, "formation_index": 4},
    {"name": "Adrien Silva", "position": "CM", "number": 23, "formation_index": 5},
    {"name": "William Carvalho", "position": "CM", "number": 14, "formation_index": 6},
    {"name": "Joao Moutinho", "position": "CM", "number": 8, "formation_index": 7},
    {"name": "Bernardo Silva", "position": "RW", "number": 10, "formation_index": 8},
    {"name": "Cristiano Ronaldo", "position": "ST", "number": 7, "formation_index": 9},
    {"name": "Goncalo Guedes", "position": "LW", "number": 11, "formation_index": 10},
]

SPAIN_LINEUP = [
    {"name": "David de Gea", "position": "GK", "number": 1, "formation_index": 0},
    {"name": "Dani Carvajal", "position": "RB", "number": 2, "formation_index": 1},
    {"name": "Gerard Pique", "position": "CB", "number": 3, "formation_index": 2},
    {"name": "Sergio Ramos", "position": "CB", "number": 15, "formation_index": 3},
    {"name": "Jordi Alba", "position": "LB", "number": 18, "formation_index": 4},
    {"name": "Sergio Busquets", "position": "CM", "number": 5, "formation_index": 5},
    {"name": "Koke", "position": "CM", "number": 6, "formation_index": 6},
    {"name": "Andres Iniesta", "position": "CM", "number": 8, "formation_index": 7},
    {"name": "David Silva", "position": "RW", "number": 21, "formation_index": 8},
    {"name": "Diego Costa", "position": "ST", "number": 19, "formation_index": 9},
    {"name": "Isco", "position": "LW", "number": 22, "formation_index": 10},
]

DEFAULT_STATE = {
    "match": {
        "minute": 0,
        "score": {"home": 0, "away": 0},
        "team_home": "Portugal",
        "team_away": "Spain"
    },
    "vision": {
        "possession_home": 50,
        "ball_zone": "unknown",
        "team_shape": "unknown",
        "tactical_description": "",
        "confidence": 0.5,
        "pressing_intensity": "medium",
    },
    "stats": {
        "shots_home": 0,
        "shots_away": 0,
        "shots_on_target_home": 0,
        "shots_on_target_away": 0,
        "possession_home": 50,
        "possession_away": 50,
        "fouls_home": 0,
        "fouls_away": 0,
        "subs_made_home": 0,
        "subs_made_away": 0,
        "live_xg_home": 0,
        "live_xg_away": 0
    },
    "lineup": {
        "home": PORTUGAL_LINEUP,
        "away": SPAIN_LINEUP,
    },
    "prediction": {
        "goal_probability": 0,
        "substitution_probability": 0,
        "shots_on_target_probability": 0,
        "momentum": 50
    },
    "possession_history": [],
    "smoothed_momentum": 50,
    "events": []
}


def smooth_momentum(state, new_value, key="smoothed_momentum"):
    """EMA smooth momentum so the bar moves gradually between vision reads."""
    try:
        current = float(state.get(key, new_value))
        new_value = float(new_value)
    except (TypeError, ValueError):
        return max(5, min(95, round(float(new_value or 50))))
    smoothed = current * 0.7 + new_value * 0.3
    return max(5, min(95, round(smoothed)))

TEAM_LINEUPS = {
    "portugal": PORTUGAL_LINEUP,
    "spain": SPAIN_LINEUP,
}


def _lineup_for_team(name):
    key = (name or "").lower().strip()
    for team_key, lineup in TEAM_LINEUPS.items():
        if team_key in key or key in team_key:
            return copy.deepcopy(lineup)
    return None


def _lineup_has_names(side):
    return bool(side) and any(p.get("name") for p in side)


def ensure_lineup(state):
    state = copy.deepcopy(state)
    match = state.setdefault("match", {})
    lineup = state.setdefault("lineup", {"home": [], "away": []})
    home_team = match.get("team_home", "")
    away_team = match.get("team_away", "")

    if not _lineup_has_names(lineup.get("home")):
        fb = _lineup_for_team(home_team)
        if fb:
            lineup["home"] = fb

    if not _lineup_has_names(lineup.get("away")):
        fb = _lineup_for_team(away_team)
        if fb:
            lineup["away"] = fb

    return state


def _default_copy():
    return copy.deepcopy(DEFAULT_STATE)


def read():
    with _lock:
        try:
            with open(STATE_FILE) as f:
                content = f.read().strip()
                if not content:
                    return _default_copy()
                return json.loads(content)
        except (FileNotFoundError, json.JSONDecodeError):
            return _default_copy()


def write(state):
    state["timestamp"] = time.time()
    with _lock:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)


def update(section, data):
    state = read()
    if section not in state:
        state[section] = {}
    if isinstance(state[section], dict) and isinstance(data, dict):
        state[section].update(data)
    else:
        state[section] = data
    write(state)


if __name__ == "__main__":
    write(_default_copy())
    print("Initialized", STATE_FILE)
