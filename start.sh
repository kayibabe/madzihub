#!/bin/bash
# MadziHub - Startup Script
echo "Installing dependencies..."
pip install -r requirements.txt

echo ""
echo "Starting MadziHub..."
echo "Open your browser at: http://localhost:8000"
echo ""
uvicorn app.main:app --host 0.0.0.0 --port 8000
