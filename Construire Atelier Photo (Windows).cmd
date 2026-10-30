@echo off
rem Construit l'application Windows autonome puis l'installateur, depuis ce dossier.
rem Prerequis : l'environnement .venv prepare (voir README.md) et une connexion Internet
rem pour Nuitka et le compilateur Inno Setup lors de la premiere construction.
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo Environnement .venv introuvable : suivez d'abord "Installer depuis les sources" dans README.md.
    goto :fail
)
"%PY%" scripts\windows_builder.py || goto :fail
pause
exit /b 0
:fail
echo.
echo La construction a echoue : conservez les messages ci-dessus.
pause
exit /b 1
