@echo off
rem Offline run, no Python install needed: run_offline.bat run ^| explain ^<gid^> ^| check ^| test ^| app
chcp 65001 >nul
cd /d "%~dp0"
set "PY=portable\win\python.exe"
set PYTHONUTF8=1
set PYTHONNOUSERSITE=1
set PYTHONPATH=
set PYTHONHOME=
if not exist "%PY%" (echo Missing %PY% - unzip moneygraph-win-x64.zip completely & exit /b 1)
if not exist "portable\win\Lib\encodings\__init__.py" (echo Archive is not fully extracted. Re-extract: tar -xf moneygraph-win-x64.zip -C C:\mg & exit /b 1)
set "CMD=%~1"
if "%CMD%"=="" set "CMD=run"
if /i "%CMD%"=="run"     "%PY%" -m moneygraph run --data data --out output & goto :eof
if /i "%CMD%"=="explain" "%PY%" -m moneygraph explain %2 & goto :eof
if /i "%CMD%"=="check"   "%PY%" -m moneygraph check --out output & goto :eof
if /i "%CMD%"=="test"    "%PY%" -m pytest -q tests & goto :eof
if /i "%CMD%"=="app"     "%PY%" -m streamlit run app\streamlit_app.py & goto :eof
echo run ^| explain ^<gid^> ^| check ^| test ^| app
