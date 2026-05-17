import json
import sys
import requests
import sqlite3
import time

import unified_state as us

API_KEY = "cae0743864ad4d41bd2d2116856a436a"
BASE_URL = "https://api.football-data.org/v4"
HEADERS = {"X-Auth-Token": API_KEY}

if len(sys.argv) >= 3:
    TEAM_A = sys.argv[1]
    TEAM_B = sys.argv[2]
else:
    TEAM_A = "Arsenal"
    TEAM_B = "Manchester City"

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
    "arsenal": us.DEFAULT_STATE["lineup"]["home"],
    "manchester city": us.DEFAULT_STATE["lineup"]["away"],
}


def _lineup_for_team(name):
    key = name.lower().strip()
    for k, lineup in TEAM_LINEUPS.items():
        if k in key or key in k:
            return lineup
    return [
        {"name": None, "position": pos, "number": None, "formation_index": i}
        for i, pos in enumerate(["GK", "RB", "CB", "CB", "LB", "CM", "CM", "CM", "RW", "ST", "LW"])
    ]


def write_unified_state_lineup():
    state = us.read()
    state["match"]["team_home"] = TEAM_A
    state["match"]["team_away"] = TEAM_B
    state["match"]["minute"] = 0
    state["match"]["score"] = {"home": 0, "away": 0}
    state["lineup"] = {
        "home": _lineup_for_team(TEAM_A),
        "away": _lineup_for_team(TEAM_B),
    }
    us.write(state)
    print(f"Updated unified_state: {TEAM_A} vs {TEAM_B} lineups written")


conn = sqlite3.connect("ballboy.db")
cursor = conn.cursor()


def api_get(endpoint):
    r = requests.get(f"{BASE_URL}{endpoint}", headers=HEADERS)
    available = int(r.headers.get("X-Requests-Available", 10))
    if available < 3:
        reset = int(r.headers.get("X-RequestCounter-Reset", 60))
        print(f"Rate limit low, waiting {reset}s...")
        time.sleep(reset)
    return r.json()


def load_team_history(team_name: str):
    data = api_get("/teams?limit=100")
    team_id = None
    for team in data.get("teams", []):
        if team_name.lower() in team["name"].lower():
            team_id = team["id"]
            print(f"Found: {team['name']} (id={team_id})")
            break

    if not team_id:
        print(f"Team not found: {team_name}")
        return

    for season in ["2024", "2023"]:
        data = api_get(f"/teams/{team_id}/matches?season={season}&status=FINISHED")
        matches = data.get("matches", [])
        print(f"{team_name} {season}: {len(matches)} matches found")

        for m in matches:
            home = m["homeTeam"]["name"]
            away = m["awayTeam"]["name"]
            score_home = m["score"]["fullTime"]["home"]
            score_away = m["score"]["fullTime"]["away"]
            date = m["utcDate"][:10]
            match_id = str(m["id"])

            for minute in [45, 60, 70, 80, 90]:
                cursor.execute(
                    """
                INSERT OR IGNORE INTO match_states
                (match_id, team_home, team_away, season, minute,
                 score_home, score_away, possession_home, possession_away,
                 press_intensity, ball_zone, conceded_next_15,
                 scored_next_15, substitution_next_10, match_date)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                    (
                        f"{match_id}_{minute}",
                        home,
                        away,
                        season,
                        minute,
                        score_home or 0,
                        score_away or 0,
                        50.0,
                        50.0,
                        "unknown",
                        "unknown",
                        0,
                        0,
                        0,
                        date,
                    ),
                )

        conn.commit()
        time.sleep(6)

    print(f"Done loading {team_name}")


if __name__ == "__main__":
    print(f"Loading history for {TEAM_A} and {TEAM_B}...")
    load_team_history(TEAM_A)
    load_team_history(TEAM_B)
    write_unified_state_lineup()
