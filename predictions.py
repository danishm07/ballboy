import math


def time_factor(minute):
    """Scale remaining goal threat by match phase (lower early, higher late)."""
    if minute < 45:
        return 0.7
    if minute < 60:
        return 1.0
    if minute < 75:
        return 1.2
    return 1.4


def goal_probability(
    minute,
    possession_home,
    subs_made=0,
    live_xg_home=0,
    live_xg_away=0,
    home_xg_season=1.8,
    away_xg_season=1.4,
):
    minutes_remaining = max(0, 90 - minute)

    if live_xg_home > 0 or live_xg_away > 0:
        remaining_xg = max(0, (home_xg_season - live_xg_home)) + max(
            0, (away_xg_season - live_xg_away)
        )
    else:
        home_rate = (home_xg_season / 90) * (possession_home / 50)
        away_rate = (away_xg_season / 90) * ((100 - possession_home) / 50)
        remaining_xg = (home_rate + away_rate) * minutes_remaining

    tf = time_factor(minute)
    prob = 1 - math.exp(-remaining_xg * tf)
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


ZONE_MOMENTUM = {
    "home_attack": 75,
    "home_mid": 60,
    "away_mid": 40,
    "away_attack": 25,
    "home_defense": 20,
    "away_defense": 70,
    "unknown": 50,
}


def momentum_score(unified_state):
    ball_zone = unified_state.get("vision", {}).get("ball_zone", "unknown")
    base = ZONE_MOMENTUM.get(ball_zone, 50)
    score = unified_state.get("match", {}).get("score", {})
    goal_diff = score.get("home", 0) - score.get("away", 0)
    score_boost = min(10, goal_diff * 3)
    return max(5, min(95, base + score_boost))


def get_all_predictions(unified_state):
    minute = unified_state.get("match", {}).get("minute", 60)
    stats = unified_state.get("stats", {})
    possession_home = stats.get("possession_home", 50)
    subs_made = stats.get("subs_made_home", 0)
    shots_home = stats.get("shots_home", 0)
    shots_on_target_home = stats.get("shots_on_target_home", 0)
    live_xg_home = stats.get("live_xg_home", 0)
    live_xg_away = stats.get("live_xg_away", 0)
    home_xg_season = stats.get("home_xg_season", 1.8)
    away_xg_season = stats.get("away_xg_season", 1.4)
    return {
        "goal_probability": goal_probability(
            minute,
            possession_home,
            subs_made,
            live_xg_home,
            live_xg_away,
            home_xg_season,
            away_xg_season,
        ),
        "substitution_probability": substitution_probability(minute, subs_made),
        "shots_on_target_probability": shots_on_target_probability(
            minute, shots_home, shots_on_target_home, possession_home
        ),
        "momentum": momentum_score(unified_state),
        "minutes_remaining": max(0, 90 - minute),
    }


if __name__ == "__main__":
    from unified_state import read

    state = read()
    state["match"]["minute"] = 60
    state["stats"]["possession_home"] = 55
    print(get_all_predictions(state))
