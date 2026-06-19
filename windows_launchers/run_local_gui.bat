@echo off
setlocal EnableExtensions

rem Double-click this file on Windows to launch the local processing GUI with a visible console.
rem This is useful for debugging startup errors. For no console window, use run_local_gui.vbs.

set "LAUNCHER_DIR=%~dp0"
for %%I in ("%LAUNCHER_DIR%..") do set "REPO_ROOT=%%~fI"
set "APP_PATH=%REPO_ROOT%\apps\local_run.py"
set "PYTHON_EXE="
set "ACTIVATE_BAT="

rem Edit this path if your conda installation is elsewhere.
if exist "%USERPROFILE%\miniconda3\envs\sci\python.exe" set "PYTHON_EXE=%USERPROFILE%\miniconda3\envs\sci\python.exe"
if not defined PYTHON_EXE if exist "%USERPROFILE%\anaconda3\envs\sci\python.exe" set "PYTHON_EXE=%USERPROFILE%\anaconda3\envs\sci\python.exe"
if not defined PYTHON_EXE if exist "%USERPROFILE%\mambaforge\envs\sci\python.exe" set "PYTHON_EXE=%USERPROFILE%\mambaforge\envs\sci\python.exe"
if not defined PYTHON_EXE if exist "%USERPROFILE%\miniforge3\envs\sci\python.exe" set "PYTHON_EXE=%USERPROFILE%\miniforge3\envs\sci\python.exe"

if not defined PYTHON_EXE (
    echo Could not find python.exe for the sci conda env.
    echo Edit %~nx0 and set PYTHON_EXE to your sci env python.exe path.
    pause
    exit /b 1
)

for %%I in ("%PYTHON_EXE%") do set "PYTHON_DIR=%%~dpI"
set "PATH=%PYTHON_DIR%;%PYTHON_DIR%Library\bin;%PYTHON_DIR%Scripts;%PATH%"
set "QT_PLUGIN_PATH=%PYTHON_DIR%Library\lib\qt6\plugins"
set "QT_QPA_PLATFORM_PLUGIN_PATH=%PYTHON_DIR%Library\lib\qt6\plugins\platforms"
if exist "%PYTHON_DIR%..\..\Scripts\activate.bat" set "ACTIVATE_BAT=%PYTHON_DIR%..\..\Scripts\activate.bat"

if not exist "%APP_PATH%" (
    echo Could not find local_run.py at:
    echo %APP_PATH%
    pause
    exit /b 1
)

echo Running local pipeline GUI:
if defined ACTIVATE_BAT (
    echo call "%ACTIVATE_BAT%" sci ^&^& python "%APP_PATH%"
) else (
    echo "%PYTHON_EXE%" "%APP_PATH%"
)
echo.
if defined ACTIVATE_BAT (
    call "%ACTIVATE_BAT%" sci
    python "%APP_PATH%"
) else (
    "%PYTHON_EXE%" "%APP_PATH%"
)

if errorlevel 1 (
    echo.
    echo local_run.py exited with errorlevel %errorlevel%.
    pause
)

endlocal
