@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "Atelier Photo" ".venv\Scripts\pythonw.exe" main.py
) else (
    echo Installez d'abord l'application en suivant README.md.
    pause
)
