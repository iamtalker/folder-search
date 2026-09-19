@echo off
cd /d "%~dp0"
pip install -r requirements.txt pyinstaller
pyinstaller --onefile --windowed --name FolderSearch --add-data "../폴더검색.html;." main.py
echo.
echo Done. See desktop\dist\FolderSearch.exe
pause
