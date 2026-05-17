import copy
import json
import threading

STATE_FILE = "unified_state.json"
_lock = threading.Lock()

DEFAULT_STATE = {
    "match": {
        "minute": 0,
        "score": {"home": 0, "away": 0},
        "team_home": "Arsenal FC",
        "team_away": "Manchester City FC"
    },
    "vision": {
        "possession_home": 50,
        "ball_zone": "unknown",
        "team_shape": "unknown",
        "tactical_description": "",
        "confidence": 0.5
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
        "home": [
            {"name": "Raya", "position": "GK", "number": 22, "formation_index": 0},
            {"name": "White", "position": "RB", "number": 4, "formation_index": 1},
            {"name": "Saliba", "position": "CB", "number": 12, "formation_index": 2},
            {"name": "Gabriel", "position": "CB", "number": 6, "formation_index": 3},
            {"name": "Zinchenko", "position": "LB", "number": 35, "formation_index": 4},
            {"name": "Odegaard", "position": "CM", "number": 8, "formation_index": 5},
            {"name": "Partey", "position": "CM", "number": 5, "formation_index": 6},
            {"name": "Rice", "position": "CM", "number": 41, "formation_index": 7},
            {"name": "Saka", "position": "RW", "number": 7, "formation_index": 8},
            {"name": "Havertz", "position": "ST", "number": 29, "formation_index": 9},
            {"name": "Martinelli", "position": "LW", "number": 11, "formation_index": 10}
        ],
        "away": [
            {"name": "Ederson", "position": "GK", "number": 31, "formation_index": 0},
            {"name": "Walker", "position": "RB", "number": 2, "formation_index": 1},
            {"name": "Dias", "position": "CB", "number": 3, "formation_index": 2},
            {"name": "Akanji", "position": "CB", "number": 25, "formation_index": 3},
            {"name": "Gvardiol", "position": "LB", "number": 24, "formation_index": 4},
            {"name": "Rodri", "position": "CM", "number": 16, "formation_index": 5},
            {"name": "De Bruyne", "position": "CM", "number": 17, "formation_index": 6},
            {"name": "Silva", "position": "CM", "number": 20, "formation_index": 7},
            {"name": "Mahrez", "position": "RW", "number": 26, "formation_index": 8},
            {"name": "Haaland", "position": "ST", "number": 9, "formation_index": 9},
            {"name": "Grealish", "position": "LW", "number": 10, "formation_index": 10}
        ]
    },
    "prediction": {
        "goal_probability": 0,
        "substitution_probability": 0,
        "shots_on_target_probability": 0,
        "momentum": 50
    },
    "possession_history": [],
    "events": []
}

TEAM_LINEUPS = {
    "portugal": [
        {"name": "Costa", "position": "GK", "number": 22, "formation_index": 0},
        {"name": "Cancelo", "position": "RB", "number": 20, "formation_index": 1},
        {"name": "Dias", "position": "CB", "number": 4, "formation_index": 2},
        {"name": "Pepe", "position": "CB", "number": 3, "formation_index": 3},
        {"name": "Guerreiro", "position": "LB", "number": 5, "formation_index": 4},
        {"name": "Neves", "position": "CM", "number": 18, "formation_index": 5},
        {"name": "Vitinha", "position": "CM", "number": 23, "formation_index": 6},
        {"name": "B. Fernandes", "position": "CM", "number": 8, "formation_index": 7},
        {"name": "Bernardo", "position": "RW", "number": 10, "formation_index": 8},
        {"name": "Ronaldo", "position": "ST", "number": 7, "formation_index": 9},
        {"name": "Leao", "position": "LW", "number": 17, "formation_index": 10},
    ],
    "spain": [
        {"name": "Simon", "position": "GK", "number": 23, "formation_index": 0},
        {"name": "Carvajal", "position": "RB", "number": 2, "formation_index": 1},
        {"name": "Laporte", "position": "CB", "number": 24, "formation_index": 2},
        {"name": "Le Normand", "position": "CB", "number": 3, "formation_index": 3},
        {"name": "Cucurella", "position": "LB", "number": 22, "formation_index": 4},
        {"name": "Rodri", "position": "CM", "number": 16, "formation_index": 5},
        {"name": "Ruiz", "position": "CM", "number": 8, "formation_index": 6},
        {"name": "Olmo", "position": "CM", "number": 10, "formation_index": 7},
        {"name": "Yamal", "position": "RW", "number": 19, "formation_index": 8},
        {"name": "Morata", "position": "ST", "number": 7, "formation_index": 9},
        {"name": "Williams", "position": "LW", "number": 17, "formation_index": 10},
    ],
    "arsenal": DEFAULT_STATE["lineup"]["home"],
    "manchester city": DEFAULT_STATE["lineup"]["away"],
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
