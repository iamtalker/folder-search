@echo off
cd /d "%~dp0"
rem Prefer the py launcher (see run.bat); pip and pyinstaller are run as
rem modules because their own commands are often not on PATH.
set PY=python
where py >nul 2>nul && set PY=py
%PY% -m pip install -r requirements.txt pyinstaller
%PY% -m PyInstaller --onefile --windowed --name FolderSearch main.py
copy /Y "..\폴더검색.html" "dist\폴더검색.html"
echo.
echo Done. dist\FolderSearch.exe and dist\폴더검색.html must stay together.
pause
