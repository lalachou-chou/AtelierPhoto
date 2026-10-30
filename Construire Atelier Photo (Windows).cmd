@echo off
rem Construit l'application Windows autonome puis l'installateur, depuis ce dossier.
rem Prerequis : l'environnement .venv prepare (voir README.md) et une connexion Internet
rem pour Nuitka et le compilateur Inno Setup lors de la premiere construction.
setlocal
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe
if not exist "%PY%" (
    echo Environnement .venv introuvable : suivez d'abord "Installer depuis les sources" dans README.md.
    goto :fail
)
for /f "delims=" %%v in ('"%PY%" -c "import atelier; print(atelier.__version__)"') do set VERSION=%%v
echo Construction d'Atelier Photo %VERSION%...
"%PY%" -m pip install --disable-pip-version-check -q Nuitka==4.1.1 || goto :fail
"%PY%" -m pytest -q || goto :fail
"%PY%" scripts\build_release.py || goto :fail
for /f "delims=" %%i in ('powershell -NoProfile -ExecutionPolicy Bypass -File scripts\prepare_inno.ps1') do set ISCC=%%i
"%ISCC%" "/DAppVersion=%VERSION%" "/DBundleDir=%CD%\dist\%VERSION%\AtelierPhoto.dist" packaging\windows.iss || goto :fail
if not exist test-output mkdir test-output
start "" /wait "dist\%VERSION%\AtelierPhoto.dist\AtelierPhoto.exe" --self-test "%CD%\test-output\packaged-%VERSION%.json"
if not exist "test-output\packaged-%VERSION%.json" goto :fail
echo.
echo Termine : dist\AtelierPhoto-%VERSION%-Windows-x64-Setup.exe
pause
exit /b 0
:fail
echo.
echo La construction a echoue : conservez les messages ci-dessus.
pause
exit /b 1
