@echo off
REM Aggiornamento automatico (Windows). Per eseguirlo ogni giorno:
REM Utilita di pianificazione > Crea attivita di base > Ogni giorno > Avvia programma > questo file
cd /d "%~dp0"
for /f %%d in ('powershell -NoProfile -Command "(Get-Date).DayOfWeek"') do set DOW=%%d
if "%DOW%"=="Monday" (python run.py --backtest) else (python run.py)
