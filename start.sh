#!/bin/bash

echo "🟢 Starting Ballboy..."

pkill -f vision_agent.py 2>/dev/null
pkill -f history_agent.py 2>/dev/null
pkill -f synthesis_agent.py 2>/dev/null
pkill -f detection_agent.py 2>/dev/null
pkill -f soccer_tracker.py 2>/dev/null
pkill -f api_agent.py 2>/dev/null
pkill -f server.py 2>/dev/null

sleep 1

PYTHON="/Users/danish/Documents/ballboy/venv/bin/python3"
HOME_TEAM="${1:-Portugal}"
AWAY_TEAM="${2:-Spain}"

echo "⚽ $HOME_TEAM vs $AWAY_TEAM"
echo "📺 Open match video on screen now"
echo ""

echo "Loading pre-match data..."
$PYTHON prematch.py "$HOME_TEAM" "$AWAY_TEAM"
echo "Pre-match data loaded."
sleep 2

$PYTHON vision_agent.py "$HOME_TEAM" "$AWAY_TEAM" &
VISION_PID=$!
echo "👁  Vision agent (PID $VISION_PID)"

sleep 2

$PYTHON history_agent.py &
HISTORY_PID=$!
echo "📊 History agent (PID $HISTORY_PID)"

$PYTHON synthesis_agent.py &
SYNTH_PID=$!
echo "🧠 Synthesis agent (PID $SYNTH_PID)"

$PYTHON api_agent.py &
API_PID=$!
echo "📡 API agent (PID $API_PID)"

$PYTHON server.py &
SERVER_PID=$!
echo "🌐 Server at localhost:5001 (PID $SERVER_PID)"

echo ""
echo "✅ Backend running."
echo "Run in separate terminals:"
echo "  cd ballboy-overlay && npm start"
echo "  python3 soccer_tracker.py"
echo ""
echo "Ctrl+C to stop backend"

trap "kill $VISION_PID $HISTORY_PID $SYNTH_PID $API_PID $SERVER_PID 2>/dev/null; exit" INT
wait