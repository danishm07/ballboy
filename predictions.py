import math

ARSENAL_XG_PER90 = 2.1
MANCITY_XG_PER90 = 1.8


def goal_probability(minute, possession_home, subs_made=0, live_xg_home=0, live_xg_away=0):
    minutes_remaining = max(0, 90 - minute)

    if live_xg_home > 0 or live_xg_away > 0:
        remaining_xg = max(0, (ARSENAL_XG_PER90 - live_xg_home)) + max(0, (MANCITY_XG_PER90 - live_xg_away))
    else:
        home_rate = (ARSENAL_XG_PER90 / 90) * (possession_home / 50)
        away_rate = (MANCITY_XG_PER90 / 90) * ((100 - possession_home) / 50)
        remaining_xg = (home_rate + away_rate) * minutes_remaining

    prob = 1 - math.exp(-remaining_xg)
    return round(prob * 100)


def substitution_probability(minute, subs_made):
    remaining_subs = 5 - subs_made
    if remaining_subs <= 0:
        return 0
    dist = {
        0: 2, 45: 20, 50: 30, 55: 45, 60: 60,
        65: 75, 70: 85, 75: 80, 80: 70, 85: 90, 90: 95
    }
    closest = min(dist.keys(), key=lambda x: abs(x - minute))
    return dist[closest]


def shots_on_target_probability(minute, shots_home, shots_on_target_home, possession_home):
    minutes_remaining = max(0, 90 - minute)
    if minute > 0:
        current_rate = shots_on_target_home / minute
    else:
        current_rate = 0.15
    expected_additional = current_rate * minutes_remaining * (possession_home / 50)
    prob = 1 - math.exp(-expected_additional)
    return round(prob * 100)


def momentum_score(possession_history):
    if not possession_history or len(possession_history) < 2:
        return 50
    recent = possession_history[-5:] if len(possession_history) >= 5 else possession_history
    trend = recent[-1] - recent[0]
    base = recent[-1]
    score = base + (trend * 1.5)
    return max(0, min(100, round(score)))


def get_all_predictions(unified_state):
    minute = unified_state.get("match", {}).get("minute", 60)
    stats = unified_state.get("stats", {})
    possession_home = stats.get("possession_home", 50)
    subs_made = stats.get("subs_made_home", 0)
    shots_home = stats.get("shots_home", 0)
    shots_on_target_home = stats.get("shots_on_target_home", 0)
    live_xg_home = stats.get("live_xg_home", 0)
    live_xg_away = stats.get("live_xg_away", 0)
    possession_history = unified_state.get("possession_history", [possession_home])

    return {
        "goal_probability": goal_probability(minute, possession_home, subs_made, live_xg_home, live_xg_away),
        "substitution_probability": substitution_probability(minute, subs_made),
        "shots_on_target_probability": shots_on_target_probability(minute, shots_home, shots_on_target_home, possession_home),
        "momentum": momentum_score(possession_history),
        "minutes_remaining": max(0, 90 - minute)
    }


if __name__ == "__main__":
    from unified_state import read
    state = read()
    state["match"]["minute"] = 60
    state["stats"]["possession_home"] = 55
    print(get_all_predictions(state))
