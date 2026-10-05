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

echo [ERROR] HPMMO_Launcher.exe not found. Please build it:
echo   cmake -S launcher_cpp -B launcher_cpp/build -G Ninja
echo   ninja -C launcher_cpp/build
echo Falling back to direct launch...
call play.bat
