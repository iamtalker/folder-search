@echo off
cd /d "%~dp0"
python desktop\main.py
if errorlevel 1 pause
