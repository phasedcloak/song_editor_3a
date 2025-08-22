#!/bin/bash
# Script to launch Song Editor 3 with the correct environment

echo "🚀 Launching Song Editor 3..."
echo "Environment: .venv_wav_to_karaoke_base"
echo "Python version: 3.9.6"
echo "Transcription: Working with faster-whisper"
echo ""

# Activate the environment
source .venv_wav_to_karaoke_base/bin/activate

# Set environment variables for better performance
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
export QT_MAC_WANTS_LAYER=1  # For better macOS compatibility

# Run the application
echo "Launching Song Editor 3..."
python -m song_editor.app
