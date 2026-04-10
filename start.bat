@echo off
setlocal

cd /d "%~dp0"

echo.
echo  Pruefe Python-Installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo  [FEHLER] Python nicht gefunden. Bitte Python 3.10+ installieren.
    echo  Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist "venv\Scripts\activate.bat" (
    echo  Erstelle virtuelle Umgebung...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo  Installiere Abhaengigkeiten...
pip install -q --upgrade pip
pip install -q -r requirements.txt

if not exist "data" mkdir data
if not exist "uploads\icons" mkdir uploads\icons

echo.
echo  ================================================
echo    FoxEx Network Monitor v1.0.0
echo  ================================================
echo    URL:    http://localhost:8000
echo    Login:  admin / admin
echo  ================================================
echo.

uvicorn main:app --host 0.0.0.0 --port 8000 --reload

pause
