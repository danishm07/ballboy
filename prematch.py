#!/usr/bin/env python3
"""
Load real pre-match data from StatsBomb (open data) into unified_state.json.

Usage:
    python3 prematch.py "Portugal" "Spain"
"""

import json
import sys
import traceback
from pathlib import Path

import unified_state as us

COMPETITION_ID = 43  # FIFA World Cup
SEASON_ID = 3  # 2018
PREMATCH_FILE = Path(__file__).resolve().parent / "prematch_data.json"

POSITION_MAP = {
    "Goalkeeper": "GK",
    "Right Back": "RB",
    "Left Back": "LB",
    "Right Center Back": "CB",
    "Left Center Back": "CB",
    "Center Back": "CB",
    "Center Defensive Midfield": "CM",
    "Right Center Midfield": "CM",
    "Left Center Midfield": "CM",
    "Right Wing": "RW",
    "Left Wing": "LW",
    "Left Midfield": "LW",
    "Center Forward": "ST",
    "Left Center Forward": "ST",
    "Right Center Forward": "ST",
}


def normalize_team(s):
    return (s or "").strip().lower()


def _search_match(matches, team_home, team_away):
    th, ta = normalize_team(team_home), normalize_team(team_away)
    for _, row in matches.iterrows():
        home = normalize_team(row.get("home_team", ""))
        away = normalize_team(row.get("away_team", ""))
        if th in home and ta in away:
            return row, team_home, team_away, row["home_team"], row["away_team"]
    return None


def find_match(team_home, team_away):
    """Try home/away as given, then swap arguments before giving up."""
    try:
        from statsbombpy import sb

        matches = sb.matches(competition_id=COMPETITION_ID, season_id=SEASON_ID)
    except Exception as e:
        print(f"[prematch] StatsBomb unavailable: {e}")
        return None

    result = _search_match(matches, team_home, team_away)
    if result:
        return result

    result = _search_match(matches, team_away, team_home)
    if result:
        return result

    return None


def display_name(lineup_df, jersey_number, fallback):
    if lineup_df is not None:
        hit = lineup_df[lineup_df["jersey_number"] == jersey_number]
        if not hit.empty:
            nick = hit.iloc[0].get("player_nickname")
            if nick and str(nick) != "nan":
                return str(nick)
            return str(hit.iloc[0].get("player_name", fallback))
    parts = fallback.split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[-1]}"
    return fallback


def map_position(sb_pos):
    return POSITION_MAP.get(sb_pos, "CM")


def lineup_from_starting_xi(events, team_name, lineup_df):
    xi_rows = events[events["type"] == "Starting XI"]
    for _, row in xi_rows.iterrows():
        if row.get("team") != team_name:
            continue
        tactics = row.get("tactics") or {}
        slots = tactics.get("lineup") or []
        players = []
        for i, slot in enumerate(slots):
            player = slot.get("player") or {}
            pos = slot.get("position") or {}
            full = player.get("name", "")
            number = int(slot.get("jersey_number", 0))
            players.append({
                "name": display_name(lineup_df, number, full),
                "position": map_position(pos.get("name", "")),
                "number": number,
                "formation_index": i,
            })
        return players
    return []


def match_xg(events, home_team, away_team):
    shots = events[events["type"] == "Shot"].copy()
    if shots.empty or "shot_statsbomb_xg" not in shots.columns:
        return 0.0, 0.0
    xg = shots.groupby("team")["shot_statsbomb_xg"].sum()
    return round(float(xg.get(home_team, 0)), 2), round(float(xg.get(away_team, 0)), 2)


def possession_by_team(events, home_team, away_team):
    ev = events[events["duration"].notna() & events["possession_team"].notna()].copy()
    if ev.empty:
        return 50.0, {}

    dur = ev.groupby("possession_team")["duration"].sum()
    total = dur.sum()
    home_pct = round(float(dur.get(home_team, 0) / total * 100), 1) if total else 50.0

    by_period = {}
    if "period" in ev.columns:
        for period in sorted(ev["period"].dropna().unique()):
            sub = ev[ev["period"] == period]
            d = sub.groupby("possession_team")["duration"].sum()
            t = d.sum()
            if t > 0:
                by_period[int(period)] = {
                    home_team: round(float(d.get(home_team, 0) / t * 100), 1),
                    away_team: round(float(d.get(away_team, 0) / t * 100), 1),
                }

    return home_pct, by_period


def press_counts(events, home_team, away_team):
    press = events[events["type"] == "Pressure"]
    if press.empty:
        return 0, 0
    counts = press.groupby("team").size()
    return int(counts.get(home_team, 0)), int(counts.get(away_team, 0))


def press_intensity_label(home_press, away_press):
    if home_press + away_press == 0:
        return "medium"
    ratio = home_press / max(away_press, 1)
    if ratio >= 1.25:
        return "high"
    if ratio <= 0.8:
        return "low"
    return "medium"


def format_lineup_names(players, limit=5):
    return ", ".join(p["name"] for p in players[:limit])


def apply_fallback(team_home, team_away, error_note=None):
    print("Match not found in StatsBomb. Using default data.")
    if error_note:
        print(f"[prematch] {error_note}")

    state = us._default_copy()
    state["match"]["team_home"] = team_home
    state["match"]["team_away"] = team_away
    state["match"]["minute"] = 0
    state["match"]["score"] = {"home": 0, "away": 0}
    state = us.ensure_lineup(state)

    stats = state.setdefault("stats", {})
    stats.setdefault("home_xg_season", 1.8)
    stats.setdefault("away_xg_season", 1.4)
    stats.setdefault("home_possession_avg", 50)
    stats.setdefault("away_possession_avg", 50)

    vision = state.setdefault("vision", {})
    vision.setdefault("pressing_intensity", "medium")
    vision.setdefault("possession_home", 50)

    prematch_data = {
        "source": "default",
        "team_home": team_home,
        "team_away": team_away,
        "error": error_note or "fallback",
        "lineup": state.get("lineup", {}),
    }

    us.write(state)
    PREMATCH_FILE.write_text(json.dumps(prematch_data, indent=2))

    home_xg = stats.get("home_xg_season", 1.8)
    away_xg = stats.get("away_xg_season", 1.4)
    home_lineup = state["lineup"].get("home", [])
    print(f"✅ {team_home} xG: {home_xg} | {team_away} xG: {away_xg} (defaults)")
    if home_lineup:
        print(f"✅ Lineup loaded: {format_lineup_names(home_lineup)}...")
    print("✅ Ready to start match")
    print(f"   Wrote {us.STATE_FILE} and {PREMATCH_FILE.name}")
    return 0


def load_statsbomb_match(team_home_arg, team_away_arg):
    from statsbombpy import sb

    found = find_match(team_home_arg, team_away_arg)
    if not found:
        return None

    match_row, home_label, away_label, sb_home, sb_away = found
    match_id = int(match_row["match_id"])

    events = sb.events(match_id=match_id)
    lineups_raw = sb.lineups(match_id=match_id)
    home_df = lineups_raw.get(sb_home)
    away_df = lineups_raw.get(sb_away)

    home_lineup = lineup_from_starting_xi(events, sb_home, home_df)
    away_lineup = lineup_from_starting_xi(events, sb_away, away_df)

    if len(home_lineup) < 11 or len(away_lineup) < 11:
        return None

    home_xg, away_xg = match_xg(events, sb_home, sb_away)
    home_poss, poss_by_period = possession_by_team(events, sb_home, sb_away)
    home_press, away_press = press_counts(events, sb_home, sb_away)
    press_level = press_intensity_label(home_press, away_press)

    return {
        "match_row": match_row,
        "match_id": match_id,
        "home_label": home_label,
        "away_label": away_label,
        "home_lineup": home_lineup,
        "away_lineup": away_lineup,
        "home_xg": home_xg,
        "away_xg": away_xg,
        "home_poss": home_poss,
        "poss_by_period": poss_by_period,
        "home_press": home_press,
        "away_press": away_press,
        "press_level": press_level,
    }


def write_success(data):
    match_row = data["match_row"]
    home_label = data["home_label"]
    away_label = data["away_label"]

    prematch_data = {
        "source": "statsbomb",
        "competition_id": COMPETITION_ID,
        "season_id": SEASON_ID,
        "match_id": data["match_id"],
        "match_date": str(match_row.get("match_date", "")),
        "team_home": home_label,
        "team_away": away_label,
        "home_xg": data["home_xg"],
        "away_xg": data["away_xg"],
        "home_possession_avg": data["home_poss"],
        "away_possession_avg": round(100 - data["home_poss"], 1),
        "possession_by_period": data["poss_by_period"],
        "press_events": {"home": data["home_press"], "away": data["away_press"]},
        "lineup": {"home": data["home_lineup"], "away": data["away_lineup"]},
    }

    state = us._default_copy()
    state["match"] = {
        "minute": 0,
        "score": {"home": 0, "away": 0},
        "team_home": home_label,
        "team_away": away_label,
    }
    state["lineup"] = {"home": data["home_lineup"], "away": data["away_lineup"]}
    state["stats"].update({
        "home_xg_season": data["home_xg"],
        "away_xg_season": data["away_xg"],
        "home_possession_avg": data["home_poss"],
        "away_possession_avg": round(100 - data["home_poss"], 1),
        "press_events_home": data["home_press"],
        "press_events_away": data["away_press"],
        "possession_home": int(round(data["home_poss"])),
        "possession_away": int(round(100 - data["home_poss"])),
        "live_xg_home": 0,
        "live_xg_away": 0,
    })
    state["vision"]["possession_home"] = int(round(data["home_poss"]))
    state["vision"]["pressing_intensity"] = data["press_level"]
    state["possession_history"] = []
    state["events"] = []

    us.write(state)
    PREMATCH_FILE.write_text(json.dumps(prematch_data, indent=2))

    print(f"✅ {home_label} xG: {data['home_xg']} | {away_label} xG: {data['away_xg']}")
    print(f"✅ Possession avg: {home_label} {data['home_poss']}% | Press: {data['home_press']} / {data['away_press']}")
    print(f"✅ Lineup loaded: {format_lineup_names(data['home_lineup'])}...")
    print(f"✅ Away lineup: {format_lineup_names(data['away_lineup'])}...")
    print("✅ Ready to start match")
    print(f"   Wrote {us.STATE_FILE} and {PREMATCH_FILE.name}")


def main():
    if len(sys.argv) < 3:
        print('Usage: python3 prematch.py "Portugal" "Spain"')
        sys.exit(1)

    team_home_arg, team_away_arg = sys.argv[1], sys.argv[2]
    print(f"[prematch] StatsBomb WC 2018 — loading {team_home_arg} vs {team_away_arg}...")

    try:
        data = load_statsbomb_match(team_home_arg, team_away_arg)
        if not data:
            return apply_fallback(team_home_arg, team_away_arg, "match or lineups not found")

        print(
            f"[prematch] Match id {data['match_id']} ({data['match_row'].get('match_date')}) — "
            f"{data['home_label']} vs {data['away_label']}"
        )
        write_success(data)
        return 0

    except Exception as e:
        print(f"[prematch] Error: {e}")
        traceback.print_exc()
        return apply_fallback(team_home_arg, team_away_arg, str(e))


if __name__ == "__main__":
    sys.exit(main() or 0)
