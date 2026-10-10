@echo off
cd /d "%~dp0"
rem Prefer the py launcher: on some machines "python" is only the Microsoft
rem Store stub, which prints "Python" and exits without running anything.
set PY=python
where py >nul 2>nul && set PY=py
%PY% desktop\main.py
if errorlevel 1 pause
