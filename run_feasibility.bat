@echo off
rem Create the venv if needed, then run the feasibility test.
rem Usage: run_feasibility.bat [profile]   (default: all profiles)
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || exit /b 1
  .venv\Scripts\python -m pip install -q -r requirements.txt || exit /b 1
)
set PROFILE=%1
if "%PROFILE%"=="" set PROFILE=all
.venv\Scripts\python -m uiauto feasibility %PROFILE%
