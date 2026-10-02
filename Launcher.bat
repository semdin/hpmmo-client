@echo off
title PotterMetin MMO Launcher
cd /d "%~dp0"

:: Try launching with pythonw (no console window) if available, otherwise python
where pythonw >nul 2>nul
if %errorlevel% equ 0 (
    start "" pythonw launcher\pottermetin_launcher.py
    exit /b 0
)

where python >nul 2>nul
if %errorlevel% equ 0 (
    start "" python launcher\pottermetin_launcher.py
    exit /b 0
)

echo [WARNING] Python not found in PATH.
echo Launching PotterMetin directly...
call play.bat
