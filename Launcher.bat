@echo off
title HPMMO Launcher
cd /d "%~dp0"

:: Prefer native C++ standalone launcher
if exist "HPMMO_Launcher.exe" (
    start "" "HPMMO_Launcher.exe"
    exit /b 0
)

if exist "launcher_cpp\build\HPMMO_Launcher.exe" (
    start "" "launcher_cpp\build\HPMMO_Launcher.exe"
    exit /b 0
)

:: Fallback to python launcher if native binary is missing
where pythonw >nul 2>nul
if %errorlevel% equ 0 (
    start "" pythonw launcher\hpmmo_launcher.py
    exit /b 0
)

where python >nul 2>nul
if %errorlevel% equ 0 (
    start "" python launcher\hpmmo_launcher.py
    exit /b 0
)

echo [WARNING] HPMMO_Launcher.exe or Python not found.
echo Launching HPMMO directly...
call play.bat
