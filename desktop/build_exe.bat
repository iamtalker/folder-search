@echo off
cd /d "%~dp0"
pip install -r requirements.txt pyinstaller
pyinstaller --onefile --windowed --name FolderSearch main.py
copy /Y "..\폴더검색.html" "dist\폴더검색.html"
echo.
echo Done. dist\FolderSearch.exe and dist\폴더검색.html must stay together.
pause
