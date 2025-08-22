#!/bin/bash

# Simple launcher for Song Editor 3
# This script runs the application directly without building an executable

echo "Launching Song Editor 3..."

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed or not in PATH"
    exit 1
fi

# Check if virtual environment exists and activate it if found
if [ -d ".venv_working" ]; then
    echo "Activating virtual environment..."
    source .venv_working/bin/activate
elif [ -d ".venv_wav_to_karaoke_base" ]; then
    echo "Activating base virtual environment..."
    source .venv_wav_to_karaoke_base/bin/activate
else
    echo "No virtual environment found, using system Python"
fi

# Run the application
echo "Starting Song Editor 3..."
python3 run_song_editor_direct.py

# Keep terminal open if there's an error
if [ $? -ne 0 ]; then
    echo "Press Enter to continue..."
    read
fi
