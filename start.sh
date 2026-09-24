#!/bin/bash
# SRWB Operations Dashboard - Startup Script
echo "Installing dependencies..."
pip install -r requirements.txt

echo ""
echo "Starting SRWB Dashboard..."
echo "Open your browser at: http://localhost:8000"
echo ""
uvicorn app.main:app --host 0.0.0.0 --port 8000
