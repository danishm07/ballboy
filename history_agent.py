import sqlite3
import json
import time
import unified_state as us

conn = sqlite3.connect("ballboy.db")
cursor = conn.cursor()

def query_history(game_state: dict) -> dict:
    team_home = game_state.get("team_home", "Arsenal FC")
    minute = game_state.get("minute") or 60
    score_home = game_state.get("score", {}).get("home") or 0
    score_away = game_state.get("score", {}).get("away") or 0

    if score_home > score_away:
        situation = "leading"
        score_filter = "score_home > score_away"
    elif score_home == score_away:
        situation = "drawing"
        score_filter = "score_home = score_away"
    else:
        situation = "losing"
        score_filter = "score_home < score_away"

    goal_diff = abs(score_home - score_away)

    # Query 1: same situation, same time window
    cursor.execute(f"""
    SELECT COUNT(*) as n,
           SUM(CASE WHEN score_home > score_away THEN 1 ELSE 0 END) as wins,
           SUM(CASE WHEN score_home = score_away THEN 1 ELSE 0 END) as draws,
           SUM(CASE WHEN score_home < score_away THEN 1 ELSE 0 END) as losses,
           AVG(score_home) as avg_scored,
           AVG(score_away) as avg_conceded
    FROM match_states
    WHERE team_home LIKE ?
    AND minute BETWEEN ? AND ?
    AND {score_filter}
""", (f"%{team_home.split()[0]}%", minute - 10, minute + 10))

    row = cursor.fetchone()
    n, wins, draws, losses, avg_scored, avg_conceded = row


    # Query 2: late game specific (minute > 75)
    late_pattern = None
    if minute >= 70:
        cursor.execute(f"""
            SELECT COUNT(*) as n,
                   SUM(CASE WHEN score_home > score_away THEN 1 ELSE 0 END) as final_wins
            FROM match_states
            WHERE team_home LIKE ?
            AND minute BETWEEN 85 AND 95
            AND {score_filter}
        """, (f"%{team_home.split()[0]}%",))
        late_row = cursor.fetchone()
        if late_row and late_row[0] > 0:
            win_rate = round((late_row[1] or 0) / late_row[0] * 100)
            late_pattern = f"When in this situation after minute 70, they hold on {win_rate}% of the time"

    if not n or n < 2:
        result = {
            "pattern": "Limited historical data",
            "situations": 0,
            "situation_type": situation
        }
    else:
        win_rate = round((wins or 0) / n * 100) if n > 0 else 0
        result = {
            "team": team_home,
            "situations": int(n),
            "situation_type": situation,
            "goal_difference": goal_diff,
            "minute": minute,
            "win_rate_from_here": win_rate,
            "avg_goals_scored": round(avg_scored or 0, 1),
            "avg_goals_conceded": round(avg_conceded or 0, 1),
            "late_pattern": late_pattern,
            "pattern": f"{team_home.split()[0]} {situation} by {goal_diff} around minute {minute}: "
                       f"win rate {win_rate}% from this point across {int(n)} similar situations. "
                       f"Avg final score {round(avg_scored or 0, 1)}-{round(avg_conceded or 0, 1)}."
                       + (f" {late_pattern}." if late_pattern else "")
        }

    with open("history_context.json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"[history] {result['pattern'][:80]}...")
    return result

def unified_to_game_state(state):
    match = state.get("match", {})
    return {
        "team_home": match.get("team_home", "Arsenal FC"),
        "team_away": match.get("team_away", "Manchester City FC"),
        "minute": match.get("minute") or 60,
        "score": match.get("score", {"home": 0, "away": 0}),
    }

print("[history] starting loop...")
while True:
    try:
        game_state = unified_to_game_state(us.read())
        query_history(game_state)
    except FileNotFoundError:
        print("[history] waiting...")
    except Exception as e:
        print(f"[history] error: {e}")
    time.sleep(10)