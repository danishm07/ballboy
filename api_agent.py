import os
import time
import requests
from dotenv import load_dotenv
import unified_state as us
from predictions import get_all_predictions

load_dotenv()

BASE_URL = "https://v3.football.api-sports.io"
API_KEY = os.getenv("FOOTBALL_API_KEY", "")
LIVE_STATUSES = {"1H", "2H", "HT", "ET", "P", "LIVE", "BT"}

POSITION_LABELS = {
    "G": "GK",
    "D": ["RB", "CB", "CB", "LB"],
    "M": ["CM", "CM", "CM"],
    "F": ["RW", "ST", "LW"],
}


def api_get(endpoint, params=None):
    if not API_KEY:
        return None
    headers = {"x-apisports-key": API_KEY}
    try:
        r = requests.get(f"{BASE_URL}{endpoint}", headers=headers, params=params or {}, timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            print(f"[api] errors: {data['errors']}")
            return None
        return data.get("response")
    except Exception as e:
        print(f"[api] request failed: {e}")
        return None


def parse_stat_value(val):
    if val is None:
        return 0
    if isinstance(val, (int, float)):
        return val
    s = str(val).replace("%", "").strip()
    try:
        return int(float(s))
    except ValueError:
        return 0


def parse_statistics(response):
    stats = {
        "shots_home": 0, "shots_away": 0,
        "shots_on_target_home": 0, "shots_on_target_away": 0,
        "possession_home": 50, "possession_away": 50,
        "fouls_home": 0, "fouls_away": 0,
        "live_xg_home": 0.0, "live_xg_away": 0.0,
    }
    if not response or len(response) < 2:
        return stats

    for i, side in enumerate(response[:2]):
        prefix = "home" if i == 0 else "away"
        for item in side.get("statistics", []):
            t = (item.get("type") or "").lower()
            v = item.get("value")
            if "shots on goal" in t or "shots on target" in t:
                stats[f"shots_on_target_{prefix}"] = parse_stat_value(v)
            elif t == "total shots" or t == "shots total":
                stats[f"shots_{prefix}"] = parse_stat_value(v)
            elif "ball possession" in t or t == "possession":
                stats[f"possession_{prefix}"] = parse_stat_value(v)
            elif "fouls" in t:
                stats[f"fouls_{prefix}"] = parse_stat_value(v)
            elif "expected goals" in t or t == "expected_goals":
                try:
                    stats[f"live_xg_{prefix}"] = float(str(v).replace(",", "."))
                except (ValueError, TypeError):
                    pass
    return stats


def parse_events(response, home_team_id, away_team_id):
    events = []
    subs_home = 0
    subs_away = 0

    if not response:
        return events, subs_home, subs_away

    for ev in response:
        team_id = ev.get("team", {}).get("id")
        team = "home" if team_id == home_team_id else "away" if team_id == away_team_id else None
        if team is None:
            continue

        minute = ev.get("time", {}).get("elapsed") or 0
        detail = (ev.get("detail") or "").lower()
        ev_type = (ev.get("type") or "").lower()

        if ev_type == "goal":
            player = ev.get("player", {}).get("name", "Unknown")
            events.append({"type": "goal", "minute": minute, "team": team, "player": player})
        elif ev_type == "card" and "yellow" in detail:
            player = ev.get("player", {}).get("name", "Unknown")
            events.append({"type": "yellow_card", "minute": minute, "team": team, "player": player})
        elif ev_type == "subst":
            player_in = ev.get("player", {}).get("name", "")
            player_out = ev.get("assist", {}).get("name", "")
            events.append({
                "type": "substitution",
                "minute": minute,
                "team": team,
                "player_in": player_in,
                "player_out": player_out,
            })
            if team == "home":
                subs_home += 1
            else:
                subs_away += 1

    return events, subs_home, subs_away


def _grid_key(player):
    grid = player.get("grid") or ""
    if ":" in str(grid):
        row, col = str(grid).split(":", 1)
        try:
            return (int(row), int(col))
        except ValueError:
            pass
    pos = (player.get("pos") or "M").upper()
    order = {"G": 0, "D": 1, "M": 2, "F": 3}
    return (order.get(pos, 2), player.get("number") or 99)


def _position_label(pos_code, index_in_group, group_size):
    pos = (pos_code or "M").upper()
    if pos == "G":
        return "GK"
    labels = POSITION_LABELS.get(pos, ["CM"] * max(group_size, 1))
    if isinstance(labels, list):
        return labels[min(index_in_group, len(labels) - 1)]
    return labels


def parse_lineup_side(team_lineup, side_key):
    default = us.DEFAULT_STATE["lineup"].get(side_key, [])
    start_xi = team_lineup.get("startXI") or []
    if not start_xi:
        return default

    players_raw = []
    for entry in start_xi:
        p = entry.get("player") or entry
        players_raw.append({
            "name": p.get("name", "Unknown"),
            "number": p.get("number") or 0,
            "pos": p.get("pos", "M"),
            "grid": p.get("grid", ""),
        })

    players_raw.sort(key=_grid_key)

    by_pos = {"G": [], "D": [], "M": [], "F": []}
    for p in players_raw:
        code = (p["pos"] or "M").upper()
        if code not in by_pos:
            code = "M"
        by_pos[code].append(p)

    ordered = by_pos["G"][:1] + by_pos["D"][:4] + by_pos["M"][:3] + by_pos["F"][:3]
    while len(ordered) < 11 and len(players_raw) > len(ordered):
        for p in players_raw:
            if p not in ordered:
                ordered.append(p)
            if len(ordered) >= 11:
                break
    ordered = ordered[:11]

    pos_counts = {}
    result = []
    for idx, p in enumerate(ordered):
        code = (p["pos"] or "M").upper()
        pos_counts[code] = pos_counts.get(code, 0)
        label = _position_label(code, pos_counts[code] - 1, len(by_pos.get(code, [])))
        result.append({
            "name": p["name"],
            "position": label,
            "number": p["number"],
            "formation_index": idx,
        })
    return result


def parse_lineups(response):
    if not response or len(response) < 2:
        return None
    home = parse_lineup_side(response[0], "home")
    away = parse_lineup_side(response[1], "away")
    return {"home": home, "away": away}


def get_next_fixture():
    data = api_get("/fixtures", {"team": 57, "next": 1})
    if not data:
        return None
    fixture = data[0]
    fix = fixture.get("fixture", {})
    teams = fixture.get("teams", {})
    goals = fixture.get("goals", {})
    return {
        "fixture_id": fix.get("id"),
        "status": fix.get("status", {}).get("short", ""),
        "minute": fix.get("status", {}).get("elapsed") or 0,
        "home_id": teams.get("home", {}).get("id"),
        "away_id": teams.get("away", {}).get("id"),
        "team_home": teams.get("home", {}).get("name", "Arsenal FC"),
        "team_away": teams.get("away", {}).get("name", "Manchester City FC"),
        "score_home": goals.get("home") or 0,
        "score_away": goals.get("away") or 0,
    }


def apply_fallback():
    state = us.read()
    state["stats"].update({
        "possession_home": state["stats"].get("possession_home", 50),
        "possession_away": 100 - state["stats"].get("possession_home", 50),
        "live_xg_home": 0,
        "live_xg_away": 0,
    })
    state["prediction"] = get_all_predictions(state)
    us.write(state)
    print("[api] fallback mode — using default Arsenal vs Man City data")


def poll_live(fixture_id, home_id, away_id):
    stats_resp = api_get("/fixtures/statistics", {"fixture": fixture_id})
    events_resp = api_get("/fixtures/events", {"fixture": fixture_id})
    fixture_resp = api_get("/fixtures", {"id": fixture_id})

    state = us.read()
    parsed_stats = parse_statistics(stats_resp)
    state["stats"].update(parsed_stats)

    events, subs_home, subs_away = parse_events(events_resp, home_id, away_id)
    state["events"] = events
    state["stats"]["subs_made_home"] = subs_home
    state["stats"]["subs_made_away"] = subs_away

    if fixture_resp:
        fix = fixture_resp[0]
        f = fix.get("fixture", {})
        goals = fix.get("goals", {})
        state["match"]["minute"] = f.get("status", {}).get("elapsed") or state["match"]["minute"]
        state["match"]["score"] = {
            "home": goals.get("home") if goals.get("home") is not None else state["match"]["score"]["home"],
            "away": goals.get("away") if goals.get("away") is not None else state["match"]["score"]["away"],
        }

    state["prediction"] = get_all_predictions(state)
    us.write(state)
    s = state["stats"]
    print(f"[api] stats shots={s['shots_home']}-{s['shots_away']} poss={s['possession_home']}% subs={subs_home}/{subs_away}")


def run():
    print("[api] starting API-Sports agent...")
    us.write(us.read())

    fixture = get_next_fixture()
    live_mode = False
    fixture_id = None
    home_id = away_id = None

    if fixture and fixture.get("fixture_id"):
        fixture_id = fixture["fixture_id"]
        home_id = fixture["home_id"]
        away_id = fixture["away_id"]
        live_mode = fixture["status"] in LIVE_STATUSES

        state = us.read()
        state["match"].update({
            "team_home": fixture["team_home"],
            "team_away": fixture["team_away"],
            "minute": fixture["minute"],
            "score": {"home": fixture["score_home"], "away": fixture["score_away"]},
        })
        us.write(state)
        print(f"[api] fixture {fixture_id} ({fixture['team_home']} vs {fixture['team_away']}) status={fixture['status']} live={live_mode}")

        lineups = api_get("/fixtures/lineups", {"fixture": fixture_id})
        parsed = parse_lineups(lineups)
        if parsed:
            state = us.read()
            state["lineup"] = parsed
            us.write(state)
            print("[api] lineups loaded from API")
    else:
        print("[api] no fixture from API — fallback mode")
        apply_fallback()
        return

    if not live_mode:
        print("[api] match not live — fallback mode (video testing)")
        apply_fallback()
        return

    while True:
        try:
            poll_live(fixture_id, home_id, away_id)
        except Exception as e:
            print(f"[api] poll error: {e}")
        time.sleep(60)


if __name__ == "__main__":
    run()
