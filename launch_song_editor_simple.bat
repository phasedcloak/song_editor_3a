@echo off
REM Simple launcher for Song Editor 3 on Windows
REM This script runs the application directly without building an executable

echo Launching Song Editor 3...

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python from https://python.org
    pause
    exit /b 1
)

REM Check if virtual environment exists and activate it if found
if exist ".venv_working\Scripts\activate.bat" (
    echo Activating virtual environment...
    call .venv_working\Scripts\activate.bat
) else if exist ".venv_wav_to_karaoke_base\Scripts\activate.bat" (
    echo Activating base virtual environment...
    call .venv_wav_to_karaoke_base\Scripts\activate.bat
) else (
    echo No virtual environment found, using system Python
)

REM Run the application
echo Starting Song Editor 3...
python run_song_editor_direct.py

REM Keep terminal open if there's an error
if errorlevel 1 (
    echo.
    echo Press any key to continue...
    pause >nul
)
