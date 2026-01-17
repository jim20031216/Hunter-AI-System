#!/bin/bash
echo "==============================================="
echo "=== Starting Hunter AI Flagship System... ==="
echo "==============================================="
echo ""
echo "Navigating to project directory..."
cd "$(dirname "$0")"

echo "Activating Python virtual environment..."
source .venv/bin/activate

echo "Starting Flask web server on http://127.0.0.1:8080"
echo "You can now open a web browser and go to http://127.0.0.1:8080"
echo "Press CTRL+C in this window to stop the server."
echo ""
python main.py
