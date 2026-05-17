#!/bin/bash

echo "🟢 Starting Ballboy..."

pkill -f vision_agent.py 2>/dev/null
pkill -f history_agent.py 2>/dev/null
pkill -f synthesis_agent.py 2>/dev/null
pkill -f detection_agent.py 2>/dev/null
pkill -f api_agent.py 2>/dev/null
pkill -f server.py 2>/dev/null

sleep 1

PYTHON="/Users/danish/Documents/ballboy/venv/bin/python3"
HOME_TEAM="${1:-Arsenal FC}"
AWAY_TEAM="${2:-Manchester City FC}"

echo "⚽ $HOME_TEAM vs $AWAY_TEAM"
echo "📺 Open match video on screen now"
echo ""

HOME_TEAM="$HOME_TEAM" AWAY_TEAM="$AWAY_TEAM" $PYTHON -c "
import os, unified_state as us
s = us.read()
s.setdefault('match', {})['team_home'] = os.environ['HOME_TEAM']
s['match']['team_away'] = os.environ['AWAY_TEAM']
us.write(us.ensure_lineup(s))
" 2>/dev/null

$PYTHON vision_agent.py "$HOME_TEAM" "$AWAY_TEAM" &
VISION_PID=$!
echo "👁  Vision agent (PID $VISION_PID)"

sleep 2

$PYTHON api_agent.py &
API_PID=$!
echo "📡 API agent started (PID $API_PID)"

$PYTHON history_agent.py &
HISTORY_PID=$!
echo "📊 History agent (PID $HISTORY_PID)"

$PYTHON synthesis_agent.py &
SYNTH_PID=$!
echo "🧠 Synthesis agent (PID $SYNTH_PID)"

$PYTHON detection_agent.py &
DETECT_PID=$!
echo "🔍 Detection agent (PID $DETECT_PID)"

$PYTHON server.py &
SERVER_PID=$!
echo "🌐 Server at localhost:5001 (PID $SERVER_PID)"

echo ""
echo "✅ All running. Now: cd ../ballboy-overlay && npm start"
echo "Ctrl+C to stop"

trap "kill $VISION_PID $API_PID $HISTORY_PID $SYNTH_PID $DETECT_PID $SERVER_PID 2>/dev/null; exit" INT
wait
