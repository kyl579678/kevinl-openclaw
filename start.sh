#!/bin/bash
# kevinl-openclaw startup script
# Serves tutorial at port 9101 + chatbot API at port 9200

cd "$(dirname "$0")"

# Start tutorial static server (port 9101)
python3 -m http.server 9101 &
HTTP_PID=$!

# Start chatbot backend (port 9200)
cd backend
# Copy .env from project root if not exists
if [ ! -f .env ] && [ -f ../.env ]; then
    cp ../.env .env
fi
python3 main.py &
BOT_PID=$!

echo "Tutorial:  http://localhost:9101 (PID $HTTP_PID)"
echo "Chatbot:   http://localhost:9200 (PID $BOT_PID)"
echo "Chatbot API: http://localhost:9200/api/chat"

# Wait for both
wait
